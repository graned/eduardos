#!/usr/bin/env python3
"""Forge Neon browser-based installer preview, served only on loopback.

No disk writes or installation APIs exist here. Uses the PR #20 hardware
preflight module as the source of truth rather than duplicating its rules.
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import forge_installer as core

ASSETS = Path(__file__).with_name("web")
MAX_PATH_LENGTH = 2048


def inventory() -> dict:
    system = core.system_preflight()
    disks = core.disk_inventory(core.run_lsblk(), core.stable_ids())
    return {"system": system, "disks": [asdict(d) for d in disks],
            "write_operations_enabled": False, "mode": "dry-run-only"}


def plan_for_identifier(identifier: str) -> dict:
    """Re-read the hardware, fail closed when selected ID disappears or changes."""
    system = core.system_preflight()
    disks = core.disk_inventory(core.run_lsblk(), core.stable_ids())
    disk = next((d for d in disks if d.by_id == identifier), None)
    if disk is None or not identifier.startswith("/dev/disk/by-id/"):
        return {"status": "blocked", "mode": "dry-run-only",
                "would_write_to_disk": False, "selected_disk": None,
                "planned_layout": list(core.LAYOUT),
                "blockers": ["Selected stable device identifier is no longer available"],
                "note": "No changes were made."}
    return core.preview(disk, system)


def make_handler(token: str):
    class ForgeHandler(BaseHTTPRequestHandler):
        server_version = "ForgePreview/0.2"

        def log_message(self, fmt, *args):
            # Avoid logging the token included in the browser's initial URL.
            sys.stderr.write("forge-installer: request handled\n")

        def send_body(self, code: int, body: bytes, mime: str):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; img-src 'self' data:; "
                             "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def reject(self, status: int = 403):
            self.send_body(status, b'{"error":"request rejected"}', "application/json; charset=utf-8")

        def do_GET(self):
            # Bind loopback AND reject unexpected Host headers (DNS rebinding).
            if len(self.path) > MAX_PATH_LENGTH:
                return self.reject(414)
            host = self.headers.get("Host", "")
            port = self.server.server_address[1]
            if host != f"127.0.0.1:{port}":
                return self.reject()
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            if path == "/":
                query = urllib.parse.parse_qs(parsed.query)
                if query.get("token") != [token]:
                    return self.reject()
                return self.serve_asset("index.html", "text/html; charset=utf-8")
            if self.headers.get("X-Forge-Token") != token:
                return self.reject()
            if path == "/style.css":
                return self.serve_asset("style.css", "text/css; charset=utf-8")
            if path == "/app.js":
                return self.serve_asset("app.js", "text/javascript; charset=utf-8")
            if path == "/api/inventory":
                try:
                    result = inventory()
                except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    return self.send_json(503, {"error": f"Hardware discovery failed: {type(exc).__name__}"})
                return self.send_json(200, result)
            if path == "/api/preview":
                query = urllib.parse.parse_qs(parsed.query)
                identifiers = query.get("id", [])
                if len(identifiers) != 1 or len(identifiers[0]) > 256:
                    return self.send_json(400, {"error": "Expected one stable disk identifier"})
                try:
                    result = plan_for_identifier(identifiers[0])
                except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    return self.send_json(503, {"error": f"Hardware discovery failed: {type(exc).__name__}"})
                return self.send_json(200, result)
            return self.reject(404)

        def do_POST(self):
            self.reject(405)

        def do_PUT(self):
            self.reject(405)

        def do_DELETE(self):
            self.reject(405)

        def send_json(self, status: int, value: dict):
            return self.send_body(status, json.dumps(value).encode(), "application/json; charset=utf-8")

        def serve_asset(self, filename: str, mime: str):
            # Fixed whitelist: requests never choose arbitrary filesystem paths.
            try:
                data = (ASSETS / filename).read_bytes()
            except OSError:
                return self.reject(500)
            return self.send_body(200, data, mime)

    return ForgeHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eduardOS graphical installer preview (read-only)")
    parser.add_argument("--no-browser", action="store_true", help="Print URL without opening browser")
    args = parser.parse_args(argv)
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(token))
    # The server never accepts any writes and is available only to local clients.
    url = f"http://127.0.0.1:{server.server_port}/?token={token}"
    print("eduardOS FORGE INSTALLER · graphical preview · NO DISK WRITES", flush=True)
    print(f"Open locally: {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nPreview stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
