#!/usr/bin/env python3
"""Drive real disposable QEMU install via the Forge lab GUI's HTTP contract.

No passwords are sent over HTTP. The QEMU lab root operator supplies an
independent startup confirmation and the existing root-owned /run fixture.
The frontend uses these same endpoints; browser-click acceptance is tracked
separately for the next frozen roadmap milestone.
"""
import http.client
import json
import os
import re
import select
import subprocess
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from urllib.parse import urlsplit

COMPLETE = "installed-lab-only"


def main(binary: str, chromium: str, chromedriver: str) -> None:
    proc = subprocess.Popen(
        [binary, "--operator-confirm", "ERASE DISPOSABLE /dev/vda"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, bufsize=0, start_new_session=True,
    )
    try:
        end = time.monotonic() + 30
        pending = bytearray()
        url = None
        assert proc.stdout is not None
        while time.monotonic() < end and url is None:
            readable, _, _ = select.select([proc.stdout], [], [], 0.5)
            if readable:
                packet = os.read(proc.stdout.fileno(), 4096)
                if not packet:
                    raise AssertionError("QEMU lab GUI exited before startup URL")
                pending.extend(packet)
                if len(pending) > 16 * 1024:
                    raise AssertionError("Oversized QEMU lab startup")
                while b"\n" in pending:
                    raw, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    if raw.startswith(b"Open locally: "):
                        url = raw.removeprefix(b"Open locally: ").decode("ascii").strip()
                        break
            if proc.poll() is not None and url is None:
                raise AssertionError("Lab GUI quit before announcing HTTP endpoint")
        if url is None:
            raise AssertionError("QEMU lab GUI startup timeout")
        parsed = urlsplit(url)
        assert parsed.hostname == "127.0.0.1" and parsed.scheme == "http"
        assert re.fullmatch(r"/\?token=[A-Za-z0-9_-]{32,}", parsed.path + "?" + parsed.query)
        token = parsed.query.removeprefix("token=")

        def request(method, path, data=None, *, auth=token, origin=True):
            conn = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=12)
            headers = {"X-Forge-Token": auth}
            if data is not None:
                headers.update({
                    "Content-Type": "application/json",
                    "Origin": f"http://127.0.0.1:{parsed.port}" if origin else "http://evil.example",
                })
            try:
                conn.request(method, path,
                             body=json.dumps(data) if data is not None else None,
                             headers=headers)
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        # The real GUI must be able to SELECT the 12-GiB VM target and
        # reach ready-for-review; production requires a 32-GiB disk.
        code, vm_inventory = request("GET", "/api/inventory")
        assert code == 200 and vm_inventory["lab_only"] is True
        assert vm_inventory["mode"] == "dry-run-only"
        assert vm_inventory["write_operations_enabled"] is False
        assert len(vm_inventory["disks"]) == 1
        disk = vm_inventory["disks"][0]
        assert disk["path"] == "/dev/vda" and disk["eligible"] is True, disk
        assert disk["by_id"] == "/dev/disk/by-id/virtio-root", disk
        code, preview = request("GET", "/api/preview?id=/dev/disk/by-id/virtio-root")
        assert code == 200 and preview["status"] == "ready-for-review", preview
        assert preview["lab_only"] is True
        assert preview["would_write_to_disk"] is False
        assert preview["blockers"] == []
        code, denied = request("GET", "/api/preview?id=/dev/vdb")
        assert code == 503
        assert denied["error"].startswith("Hardware discovery failed:")

        code, result = request("GET", "/api/lab/status")
        assert code == 200 and result["status"] == "awaiting-lab-trigger"
        assert result["authorization_to_write"] is False
        assert request("GET", "/api/lab/status", auth="wrong")[0] == 403
        assert request("POST", "/api/lab/start", {"operation": "wrong"})[0] == 409
        assert request("POST", "/api/lab/start", {
            "operation": "start-disposable-qemu-install",
            "confirmation": "ERASE DISPOSABLE /dev/vda",
            "disk_by_id": "/dev/disk/by-id/virtio-root",
            "username": "testpilot",
            "hostname": "edos-installed-lab",
        }, origin=False)[0] == 403
        # FROM THIS POINT: actual Chromium browser clicks through the
        # entire Forge wizard, including the JavaScript confirmation modal.
        # No direct POST /api/lab/start is made by the test harness.
        options = Options()
        options.binary_location = chromium
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--window-size=1440,900"):
            options.add_argument(arg)
        options.set_capability("goog:loggingPrefs", {"browser": "SEVERE"})
        browser = webdriver.Chrome(service=Service(executable_path=chromedriver),
                                   options=options)
        try:
            browser.set_page_load_timeout(30)
            browser.get(url)
            wait = WebDriverWait(browser, 45)
            def click_when_ready(selector):
                element = wait.until(lambda d: next((
                    e for e in d.find_elements(By.CSS_SELECTOR, selector)
                    if e.is_displayed() and e.is_enabled()), None))
                element.click()
            click_when_ready("#start")
            click_when_ready("#to-storage")
            click_when_ready("#disks .disk-option:not(:disabled)")
            click_when_ready("#to-config")
            host = browser.find_element(By.ID, "hostname")
            host.clear()
            host.send_keys("edos-installed-lab")
            account = browser.find_element(By.ID, "username")
            account.clear()
            account.send_keys("testpilot")
            click_when_ready("#validate-config")
            click_when_ready("#summary button.primary")
            alert = wait.until(lambda d: d.switch_to.alert)
            assert "DISPOSABLE /dev/vda" in alert.text
            alert.accept()
            wait.until(lambda d: any(
                "State: " + state in element.text
                for state in ("running", "preflight", "installed-lab-only")
                for element in d.find_elements(By.CSS_SELECTOR, "#summary .ready-text")
            ))
            print("FORGE_QEMU_BROWSER=clicked-install", flush=True)
            # Keep Chromium alive until the real executor finishes, so
            # progress rendering and status transitions are exercised.
            WebDriverWait(browser, 1300, poll_frequency=1).until(
                lambda d: any(
                    "State: installed-lab-only" in e.text
                    for e in d.find_elements(By.CSS_SELECTOR, "#summary .ready-text")
                )
            )
            severe = [entry for entry in browser.get_log("browser")
                      if entry.get("level") == "SEVERE"]
            assert not severe, severe
            assert browser.find_element(By.CSS_SELECTOR, "#summary .lab-progress").text
        finally:
            browser.quit()
        # The browser performed the only valid /api/lab/start request.
        # Replay must still be denied by the one-shot root controller.
        assert request("POST", "/api/lab/start", {
            "operation": "start-disposable-qemu-install",
            "confirmation": "ERASE DISPOSABLE /dev/vda",
            "disk_by_id": "/dev/disk/by-id/virtio-root",
            "username": "testpilot",
            "hostname": "edos-installed-lab",
        })[0] == 409

        deadline = time.monotonic() + 1300
        while time.monotonic() < deadline:
            code, result = request("GET", "/api/lab/status")
            assert code == 200
            assert result["physical_hardware_supported"] is False
            assert result["authorization_to_write"] is False
            assert result["automatic_retry_enabled"] is False
            if result["status"] not in ("running", "preflight"):
                break
            time.sleep(1)
        else:
            raise AssertionError("QEMU lab GUI install did not finish")
        assert result["status"] == COMPLETE, result
        assert result["complete"] is True
        # Emit the validated controller's observed fixed phases for the
        # existing NixOS test-driver phase assessor to cross-check.
        for phase in result["phases"]:
            print("FORGE_QEMU_PHASE=" + phase, flush=True)
        print("FORGE_QEMU_GUI=installed-via-browser-click", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: forge-lab-gui-in-qemu.py <lab-gui> <chromium> <chromedriver>")
    main(sys.argv[1], sys.argv[2], sys.argv[3])
