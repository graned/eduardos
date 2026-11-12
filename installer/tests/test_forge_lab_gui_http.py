"""Live localhost HTTP tests for the QEMU GUI launch route.

A fake lab controller is injected; this cannot run Disko. The actual
destructive integration is exercised exclusively by the full QEMU test.
"""
import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_gui


class FakeLab:
    def __init__(self):
        self.starts = 0
        self.cancels = 0

    def report(self):
        return {
            "version": "eduardos.forge.qemu-gui-install.v1",
            "status": "awaiting-lab-trigger",
            "phases": [],
            "authorization_to_write": False,
        }

    def start(self, payload):
        if payload != {"operation": "start-disposable-qemu-install"}:
            raise ValueError("bad")
        self.starts += 1
        if self.starts > 1:
            raise ValueError("replayed")
        return {"status": "running"}

    def cancel(self):
        self.cancels += 1
        return {"status": "cancel-requested"}


class LabHTTPTests(unittest.TestCase):
    def setUp(self):
        self.token = "qemu-lab-test"
        self.lab = FakeLab()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            forge_gui.make_handler(self.token, lab_session=self.lab),
        )
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)

    def request(self, method, path, payload=None, *, token=None, origin=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        host = f"127.0.0.1:{self.server.server_port}"
        headers = {"Host": host, "X-Forge-Token": self.token if token is None else token}
        if payload is not None:
            headers.update({"Content-Type": "application/json",
                            "Origin": f"http://{host}" if origin else "http://evil.example"})
        try:
            conn.request(method, path,
                         body=json.dumps(payload) if payload is not None else None,
                         headers=headers)
            result = conn.getresponse()
            return result.status, result.read()
        finally:
            conn.close()

    def test_fixed_lab_endpoints_obey_token_and_origin(self):
        self.assertEqual(self.request("GET", "/api/lab/status")[0], 200)
        self.assertEqual(self.request("GET", "/api/lab/status", token="bad")[0], 403)
        payload = {"operation": "start-disposable-qemu-install"}
        self.assertEqual(self.request("POST", "/api/lab/start", payload, origin=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/lab/start", payload, token="bad")[0], 403)
        self.assertEqual(self.lab.starts, 0)
        self.assertEqual(self.request("POST", "/api/lab/start", payload)[0], 202)
        self.assertEqual(self.request("POST", "/api/lab/start", payload)[0], 409)
        self.assertEqual(self.lab.starts, 2)

    def test_favicon_probe_has_no_forbidden_response(self):
        status, body = self.request("GET", "/favicon.ico")
        self.assertEqual(status, 204)
        self.assertEqual(body, b"")

    def test_nonsecret_body_and_cancel_route(self):
        self.assertEqual(self.request("POST", "/api/lab/start", {"password": "NEVER_ECHO"})[0], 409)
        status, body = self.request("POST", "/api/lab/cancel", {"operation": "wrong"})
        self.assertEqual(status, 400)
        self.assertNotIn(b"NEVER_ECHO", body)
        self.assertEqual(self.request("POST", "/api/lab/cancel",
                         {"operation": "cancel-disposable-qemu-install"})[0], 200)
        self.assertEqual(self.lab.cancels, 1)

    def test_production_default_has_no_lab_routes(self):
        handler = forge_gui.make_handler("readonly")
        self.assertIsNotNone(handler)
        # The server's default make_handler(token) closure has no controller;
        # all lab POST routes must remain 405, not inherit the test controller.
        other = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        worker = threading.Thread(target=other.serve_forever, daemon=True)
        worker.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", other.server_port, timeout=3)
            host = f"127.0.0.1:{other.server_port}"
            conn.request("POST", "/api/lab/start", body=b"{}",
                         headers={"Host": host, "Origin": f"http://{host}",
                                  "Content-Type": "application/json",
                                  "X-Forge-Token": "readonly"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 405)
            resp.read()
            conn.close()
        finally:
            other.shutdown()
            other.server_close()
            worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
