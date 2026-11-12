"""Graphical installer API safety tests: loopback only, read-only."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import forge_gui
import forge_installer as core

GIB = 1024**3
ID = "/dev/disk/by-id/virtio-empty-disk"
SYSTEM = {"architecture": "x86_64", "uefi": True, "memory_bytes": 8 * GIB,
          "sufficient_memory": True, "architecture_supported": True}
SOURCE = {"blockdevices": [
    {"name": "vda", "path": "/dev/vda", "type": "disk", "size": 64 * GIB,
     "model": "<unsafe>Virtual Disk", "tran": "virtio", "ro": False, "rm": False,
     "mountpoints": [None], "fstype": None}
]}


class WebPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = "test-secret-token"
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), forge_gui.make_handler(cls.token)
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method, path, token=True, host=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Host": f"127.0.0.1:{self.server.server_port}" if host else "evil.example"}
        if token:
            headers["X-Forge-Token"] = self.token
        conn.request(method, path, headers=headers)
        response = conn.getresponse()
        result = (response.status, response.read(), dict(response.getheaders()))
        conn.close()
        return result

    def test_html_requires_launch_token(self):
        self.assertEqual(self.request("GET", "/")[0], 403)
        status, content, headers = self.request("GET", f"/?token={self.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"FORGED IN DARKNESS", content)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])

    def test_static_assets_and_unknown_path(self):
        self.assertEqual(self.request("GET", "/style.css", token=False)[0], 200)
        self.assertEqual(self.request("GET", "/app.js", token=False)[0], 200)
        self.assertEqual(self.request("GET", "/etc/passwd")[0], 404)

    def test_installer_boot_ui_has_visible_static_content_and_font(self):
        status, html, headers = self.request("GET", f"/?token={self.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"From struggle,", html)
        self.assertIn(b"Read-only installation preview", html)
        self.assertIn(b"Inspect this machine", html)
        self.assertIn("font-src 'self'", headers["Content-Security-Policy"])
        status, css, _ = self.request("GET", "/style.css", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"/forge-font.ttf", css)
        self.assertIn(b"/artwork.png", css)

    def test_installer_artwork_fits_and_font_fallback_is_legible(self):
        status, css, _ = self.request("GET", "/style.css", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"background-size:100% 100%,contain", css)
        self.assertNotIn(b"background-size:cover", css)
        self.assertIn(b"font-weight:400", css)
        self.assertIn(b'"DejaVu Sans",sans-serif', css)
        self.assertIn(b"color:var(--text)", css)

    def test_live_brave_software_text_rendering_is_opt_in(self):
        with patch.dict(forge_gui.os.environ, {"EDOS_FORGE_SOFTWARE_BROWSER": "1"}), \\
             patch.object(forge_gui.shutil, "which", return_value="/nix/store/brave/bin/brave"), \\
             patch.object(forge_gui.subprocess, "Popen") as popen, \\
             patch.object(forge_gui.webbrowser, "open") as fallback:
            forge_gui.open_preview_browser("http://127.0.0.1:12345/?token=example")
            args = popen.call_args.args[0]
            self.assertIn("--disable-gpu", args)
            self.assertIn("--disable-gpu-compositing", args)
            self.assertEqual(popen.call_args.kwargs["env"]["LIBGL_ALWAYS_SOFTWARE"], "1")
            fallback.assert_not_called()
        with patch.dict(forge_gui.os.environ, {"EDOS_FORGE_SOFTWARE_BROWSER": "0"}), \\
             patch.object(forge_gui.webbrowser, "open") as fallback:
            forge_gui.open_preview_browser("http://127.0.0.1:12345/?token=example")
            fallback.assert_called_once()

    def test_font_asset_is_same_origin_and_fixed_path(self):
        with TemporaryDirectory() as directory:
            font = Path(directory) / "forge.ttf"
            font.write_bytes(b"fake-font-fixture")
            with patch.object(forge_gui, "FONT", font):
                status, body, headers = self.request("GET", "/forge-font.ttf", token=False)
                self.assertEqual(status, 200)
                self.assertEqual(body, b"fake-font-fixture")
                self.assertEqual(headers["Content-Type"], "font/ttf")
                self.assertEqual(self.request("GET", "/forge-font.ttf?path=/etc/passwd", token=False)[1], body)
                self.assertEqual(self.request("GET", "/../forge-font.ttf", token=True)[0], 404)
            self.assertEqual(self.request("GET", "/forge-font.ttf", token=False)[0], 404)

    def test_approved_artwork_is_fixed_read_only_png_route(self):
        with TemporaryDirectory() as directory:
            image = Path(directory) / "approved.png"
            image.write_bytes(b"\\x89PNG\\r\\n\\x1a\\nimage-fixture")
            with patch.object(forge_gui, "ARTWORK", image):
                status, body, headers = self.request("GET", "/artwork.png", token=False)
                self.assertEqual(status, 200)
                self.assertEqual(body, b"\\x89PNG\\r\\n\\x1a\\nimage-fixture")
                self.assertEqual(headers["Content-Type"], "image/png")
                self.assertEqual(self.request(
                    "GET", "/artwork.png?file=/etc/passwd", token=False
                )[1], body)
                self.assertEqual(self.request(
                    "GET", "/../artwork.png", token=True
                )[0], 404)
            self.assertEqual(self.request("GET", "/artwork.png", token=False)[0], 404)

    def test_rejects_host_rebinding(self):
        self.assertEqual(self.request("GET", f"/?token={self.token}", host=False)[0], 403)

    def test_api_requires_token(self):
        self.assertEqual(self.request("GET", "/api/inventory", token=False)[0], 403)
        self.assertEqual(self.request("GET", "/api/preview?id=whatever", token=False)[0], 403)

    def test_discovery_and_plan_share_preflight(self):
        with patch.object(core, "system_preflight", return_value=SYSTEM), \
             patch.object(core, "run_lsblk", return_value=SOURCE), \
             patch.object(core, "stable_ids", return_value={"/dev/vda": ID}):
            status, body, _ = self.request("GET", "/api/inventory")
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertFalse(data["write_operations_enabled"])
            self.assertEqual(data["disks"][0]["by_id"], ID)
            status, body, _ = self.request("GET", "/api/preview?id=" + ID.replace("/", "%2F"))
            self.assertEqual(status, 200)
            plan = json.loads(body)
            self.assertEqual(plan["status"], "ready-for-review")
            self.assertFalse(plan["would_write_to_disk"])
            status, body, _ = self.request("GET", "/api/preview?id=%2Fdev%2Fsda")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["status"], "blocked")

    def test_no_write_verbs(self):
        for method in ("POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                self.assertEqual(self.request(method, "/api/preview")[0], 405)

    def test_missing_ids_and_bad_disks(self):
        self.assertEqual(self.request("GET", "/api/preview")[0], 400)
        with patch.object(core, "system_preflight", return_value=SYSTEM), \
             patch.object(core, "run_lsblk", return_value=SOURCE), \
             patch.object(core, "stable_ids", return_value={}):
            plan = forge_gui.plan_for_identifier(ID)
            self.assertEqual(plan["status"], "blocked")
            self.assertFalse(plan["would_write_to_disk"])


if __name__ == "__main__":
    unittest.main()
