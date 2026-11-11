"""Real loopback HTTP contract tests for Forge's *read-only* preview.

Run: python3 -m unittest discover -s installer/tests -p 'test_forge_http_contract.py'
No storage commands, root privileges or external network access.
"""
import http.client
import sys
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_gui


class ForgeHTTPContract(unittest.TestCase):
    def setUp(self):
        self.token = "unit-test-token-not-a-secret"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), forge_gui.make_handler(self.token))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Host": f"127.0.0.1:{self.server.server_port}", **(headers or {})}
        conn.request(method, path, body=body, headers=headers)
        result = conn.getresponse()
        status, data, response_headers = result.status, result.read(), dict(result.getheaders())
        conn.close()
        return status, data, response_headers

    def test_unauthenticated_api_never_returns_inventory(self):
        with mock.patch.object(forge_gui, "inventory", side_effect=AssertionError("inventory called")):
            status, _, headers = self.request("GET", "/api/inventory")
            self.assertEqual(status, 403)
            self.assertEqual(headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_all_write_methods_refused_even_with_token(self):
        with mock.patch.object(forge_gui, "inventory", side_effect=AssertionError("inventory called")):
            for method in ("POST", "PUT", "DELETE"):
                with self.subTest(method=method):
                    status, _, _ = self.request(method, "/api/inventory",
                        {"X-Forge-Token": self.token}, body=b'{"device":"/dev/sda"}')
                    self.assertEqual(status, 405)

    def test_dns_rebinding_host_refused_before_api(self):
        with mock.patch.object(forge_gui, "inventory", side_effect=AssertionError("inventory called")):
            status, _, _ = self.request("GET", "/api/inventory",
                {"Host": "evil.example", "X-Forge-Token": self.token})
            self.assertEqual(status, 403)

    def test_only_whitelisted_paths_are_served(self):
        for path in ("/../../etc/passwd", "/api/install", "/api/execute",
                     "/api/preview?id=/dev/sda"):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path, {"X-Forge-Token": self.token})
                # Invalid/unknown route cannot become a write endpoint.
                self.assertIn(status, (400, 403, 404))

    def test_tokened_inventory_is_explicitly_read_only(self):
        fixture = {"system": {}, "disks": [], "write_operations_enabled": False, "mode": "dry-run-only"}
        with mock.patch.object(forge_gui, "inventory", return_value=fixture):
            status, body, _ = self.request("GET", "/api/inventory",
                                          {"X-Forge-Token": self.token})
        self.assertEqual(status, 200)
        import json
        response = json.loads(body)
        self.assertEqual(response["mode"], "dry-run-only")
        self.assertIs(response["write_operations_enabled"], False)

    def test_missing_stable_id_is_never_an_installation(self):
        with mock.patch.object(forge_gui.core, "system_preflight", return_value={}), \
             mock.patch.object(forge_gui.core, "run_lsblk", return_value={}), \
             mock.patch.object(forge_gui.core, "stable_ids", return_value={}), \
             mock.patch.object(forge_gui.core, "disk_inventory", return_value=[]):
            response = forge_gui.plan_for_identifier("/dev/disk/by-id/absent")
        self.assertEqual(response["status"], "blocked")
        self.assertIs(response["would_write_to_disk"], False)


if __name__ == "__main__":
    unittest.main()
