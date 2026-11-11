#!/usr/bin/env python3
"""Exercise actual Forge GUI HTTP process inside the disposable QEMU installer.

No writes: this uses only preview routes and non-secret validation, BEFORE
the separate lab-only CLI executes Disko on disposable /dev/vda.
"""
import http.client
import json
import re
import select
import subprocess
import sys
import time
from urllib.parse import urlsplit


def main(binary: str) -> None:
    process = subprocess.Popen(
        [binary, "--no-browser"], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1, start_new_session=True,
    )
    try:
        end = time.monotonic() + 20
        url = None
        while time.monotonic() < end:
            readable, _, _ = select.select([process.stdout], [], [], 0.5)
            if readable:
                line = process.stdout.readline().strip()
                if line.startswith("Open locally: "):
                    url = line.removeprefix("Open locally: ")
                    break
            if process.poll() is not None:
                raise AssertionError("Forge GUI terminated before responding")
        if url is None:
            raise AssertionError("Forge GUI did not publish loopback URL")
        parsed = urlsplit(url)
        assert parsed.hostname == "127.0.0.1" and parsed.scheme == "http"
        assert re.fullmatch(r"/\?token=[A-Za-z0-9_-]{32,}", parsed.path + "?" + parsed.query)
        token = parsed.query.removeprefix("token=")

        def request(method, path, body=None, *, origin=None, auth=token):
            connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=8)
            headers = {"X-Forge-Token": auth}
            if body is not None:
                headers.update({"Content-Type": "application/json",
                                "Origin": origin or f"http://127.0.0.1:{parsed.port}"})
                body = json.dumps(body)
            try:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        status, html = request("GET", "/?token=" + token)
        assert status == 200 and b"Forge Installer" in html
        status, inventory = request("GET", "/api/inventory")
        assert status == 200
        data = json.loads(inventory)
        assert data["mode"] == "dry-run-only"
        assert data["write_operations_enabled"] is False
        assert isinstance(data["disks"], list)

        # The disposable test disk is only 12 GiB and must never be an
        # eligible *physical* installer target. No host disk is selected.
        draft = {"hostname": "edos-lab", "username": "testpilot",
                 "disk_by_id": "/dev/disk/by-id/virtio-root"}
        status, response = request("POST", "/api/config/validate", draft)
        assert status == 200
        validated = json.loads(response)
        assert validated["mode"] == "dry-run-only"
        assert validated["write_operations_enabled"] is False
        assert validated["valid"] is True

        assert request("POST", "/api/install", draft)[0] == 405
        assert request("POST", "/api/execute", draft)[0] == 405
        assert request("POST", "/api/config/validate", draft, auth="bad")[0] == 403
        assert request("POST", "/api/config/validate", draft, origin="http://evil.example")[0] == 403
        assert request("GET", "/api/inventory", auth="bad")[0] == 403
        print("FORGE_QEMU_GUI=preview-only-verified", flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: forge-preview-in-qemu.py <trusted-gui-binary>")
    main(sys.argv[1])
