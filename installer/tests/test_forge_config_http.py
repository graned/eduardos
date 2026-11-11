"""Loopback tests for bounded validation-only Forge POST. No disk access."""
import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_gui

VALID = {"hostname": "edos", "username": "developer",
         "disk_by_id": "/dev/disk/by-id/wwn-0x123"}


class ValidationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.token = "forge-test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), forge_gui.make_handler(self.token))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def send(self, method="POST", path="/api/config/validate", payload=VALID, headers=None):
        content = json.dumps(payload).encode()
        host = f"127.0.0.1:{self.server.server_port}"
        defaults = {"Host": host, "Origin": f"http://{host}", "X-Forge-Token": self.token,
                    "Content-Type": "application/json"}
        defaults.update(headers or {})
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        client.request(method, path, body=content, headers=defaults)
        response = client.getresponse()
        result = response.status, response.read()
        client.close()
        return result

    def test_success_is_validation_only(self):
        code, body = self.send()
        self.assertEqual(code, 200)
        result = json.loads(body)
        self.assertTrue(result["valid"])
        self.assertFalse(result["write_operations_enabled"])
        self.assertEqual(result["mode"], "dry-run-only")

    def test_unauthorized_and_cross_origin_refused(self):
        for overrides in ({"X-Forge-Token": "bad"},
                          {"Origin": "http://evil.example"},
                          {"Host": "evil.example"}):
            with self.subTest(headers=overrides):
                self.assertEqual(self.send(headers=overrides)[0], 403)

    def test_rejects_secret_fields_without_echo(self):
        code, body = self.send(payload={**VALID, "password": "SUPER_SECRET_VALUE"})
        self.assertEqual(code, 200)
        result = json.loads(body)
        self.assertFalse(result["valid"])
        self.assertNotIn(b"SUPER_SECRET_VALUE", body)

    def test_other_post_routes_remain_forbidden(self):
        for path in ("/api/inventory", "/api/install", "/api/execute"):
            self.assertEqual(self.send(path=path)[0], 405)

    def test_invalid_content_type(self):
        self.assertEqual(self.send(headers={"Content-Type": "text/plain"})[0], 415)

    def test_rejects_oversized_payload(self):
        self.assertEqual(self.send(payload={**VALID, "padding": "x" * 3000})[0], 413)


if __name__ == "__main__":
    unittest.main()
