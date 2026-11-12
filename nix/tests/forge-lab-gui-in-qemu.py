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
from urllib.parse import urlsplit

COMPLETE = "installed-lab-only"


def main(binary: str) -> None:
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
        # Correct, separately pre-authorized, fixed VM operation.
        code, result = request("POST", "/api/lab/start", {
            "operation": "start-disposable-qemu-install",
            "confirmation": "ERASE DISPOSABLE /dev/vda",
            "disk_by_id": "/dev/disk/by-id/virtio-root",
            "username": "testpilot",
            "hostname": "edos-installed-lab",
        })
        assert code == 202, (code, result)
        # One-shot session: repeat request cannot start a second executor.
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
        print("FORGE_QEMU_GUI=installed-via-http-lab", flush=True)
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
    if len(sys.argv) != 2:
        raise SystemExit("Usage: forge-lab-gui-in-qemu.py <pinned-lab-gui-executable>")
    main(sys.argv[1])
