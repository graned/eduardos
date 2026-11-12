"""Loopback HTTP capability contract: preview cannot authorize installation."""
import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge_gui


class CapabilityHTTPTests(unittest.TestCase):
    def setUp(self):
        self.token = "capability-test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), forge_gui.make_handler(self.token))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)

    def get(self, path, *, token=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {
            "Host": host or f"127.0.0.1:{self.server.server_port}",
            "X-Forge-Token": self.token if token is None else token,
        }
        try:
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_server_capability_contract_is_non_executable(self):
        status, body = self.get("/api/capabilities")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["version"], "eduardos.forge.capabilities.v1")
        self.assertEqual(data["mode"], "dry-run-only")
        for name in ("installation_available", "physical_disk_writes_enabled",
                     "credential_collection_enabled", "privileged_executor_connected",
                     "automatic_retry_enabled"):
            self.assertIs(data[name], False)
        self.assertEqual(len(data["required_gates"]), 4)
        self.assertNotIn("password", body.decode().lower())

    def test_capability_endpoint_requires_token_and_fixed_host(self):
        self.assertEqual(self.get("/api/capabilities", token="wrong")[0], 403)
        self.assertEqual(self.get("/api/capabilities", host="attacker.example")[0], 403)

    def test_no_install_endpoint_is_created(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request("POST", "/api/install", body=b"{}",
                         headers={"Host": f"127.0.0.1:{self.server.server_port}",
                                  "X-Forge-Token": self.token})
            response = conn.getresponse()
            self.assertEqual(response.status, 405)
            response.read()
        finally:
            conn.close()

    def test_preview_script_reads_capabilities_but_does_not_execute(self):
        script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text()
        self.assertIn('getJSON("/api/capabilities")', script)
        self.assertIn("capability.installation_available !== false", script)
        self.assertNotIn('fetch("/api/install"', script)


if __name__ == "__main__":
    unittest.main()
