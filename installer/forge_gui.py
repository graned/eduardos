#!/usr/bin/env python3
"""Forge Eclipse browser-based installer preview, served only on loopback.

No disk writes or installation APIs exist here. Uses the PR #20 hardware
preflight module as the source of truth rather than duplicating its rules.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import tempfile
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import forge_installer as core
from forge_install_config import validate_draft

ASSETS = Path(__file__).with_name("web")
# Nix supplies dedicated immutable installer artwork, distinct from both
# the desktop wallpaper and the EFI/BIOS boot menu background.
# Local development can provide installer/web/artwork.png instead.
ARTWORK = Path(os.environ.get("EDOS_FORGE_ARTWORK_PNG", str(ASSETS / "artwork.png")))
# Serve a known system font as a same-origin asset: Chromium in some live VMs
# draws backgrounds but fails to paint text when font fallback is unavailable.
FONT = Path(os.environ.get("EDOS_FORGE_FONT_PATH", "/nonexistent/forge-font.ttf"))
MAX_PATH_LENGTH = 2048
MAX_DRAFT_BYTES = 2048

def install_capabilities() -> dict:
    """Safe public contract: preview-only, no local privileged executor.

    This is intentionally fixed server-side. A browser, preview hash or
    validated draft can never promote these flags into an install action.
    """
    return {
        "version": "eduardos.forge.capabilities.v1",
        "mode": "dry-run-only",
        "installation_available": False,
        "physical_disk_writes_enabled": False,
        "credential_collection_enabled": False,
        "privileged_executor_connected": False,
        "automatic_retry_enabled": False,
        "required_gates": [
            "independent-root-authorization",
            "durable-attempt-recovery",
            "sealed-credential-integration",
            "gui-executor-qemu-acceptance",
        ],
    }



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


def make_handler(token: str, *, lab_session=None):
    # Only a separate disposable-VM root launcher may supply lab_session.
    # The normal live ISO and packaged GUI always use the default None.
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
                             "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
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
            # Browsers do not attach custom request headers when loading
            # stylesheet and script tags; these fixed assets are public,
            # but the HTML entrypoint and read-only API remain token-guarded.
            if path == "/favicon.ico":
                # Browsers request this automatically. No icon is shipped;
                # respond with an explicit empty asset rather than a 403.
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if path == "/style.css":
                return self.serve_asset("style.css", "text/css; charset=utf-8")
            if path == "/app.js":
                return self.serve_asset("app.js", "text/javascript; charset=utf-8")
            if path == "/forge-font.ttf":
                try:
                    font_data = FONT.read_bytes()
                except OSError:
                    return self.reject(404)
                return self.send_body(200, font_data, "font/ttf")
            # Fixed artwork route: no user-controlled asset paths, and the
            # installer remains a strictly read-only preview.
            if path == "/artwork.png":
                # A fixed, read-only file selected by the trusted Nix launcher.
                # Never accept request-supplied filesystem paths.
                try:
                    data = ARTWORK.read_bytes()
                except OSError:
                    return self.reject(404)
                return self.send_body(200, data, "image/png")
            if self.headers.get("X-Forge-Token") != token:
                return self.reject()
            if path == "/api/lab/status" and lab_session is not None:
                return self.send_json(200, lab_session.report())
            if path == "/api/capabilities":
                return self.send_json(200, install_capabilities())
            if path == "/api/inventory":
                try:
                    result = lab_session.inventory() if lab_session is not None else inventory()
                except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    return self.send_json(503, {"error": f"Hardware discovery failed: {type(exc).__name__}"})
                return self.send_json(200, result)
            if path == "/api/preview":
                query = urllib.parse.parse_qs(parsed.query)
                identifiers = query.get("id", [])
                if len(identifiers) != 1 or len(identifiers[0]) > 256:
                    return self.send_json(400, {"error": "Expected one stable disk identifier"})
                try:
                    result = (lab_session.preview(identifiers[0]) if lab_session is not None
                              else plan_for_identifier(identifiers[0]))
                except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    return self.send_json(503, {"error": f"Hardware discovery failed: {type(exc).__name__}"})
                return self.send_json(200, result)
            return self.reject(404)

        def do_POST(self):
            # This single, bounded JSON endpoint validates a NON-SECRET draft.
            # It cannot access an executor, store data or authorize installation.
            if len(self.path) > MAX_PATH_LENGTH:
                return self.reject(414)
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_address[1]}":
                return self.reject()
            route = urllib.parse.urlsplit(self.path).path
            if route not in ("/api/config/validate", "/api/lab/start", "/api/lab/cancel"):
                return self.reject(405)
            if route != "/api/config/validate" and lab_session is None:
                return self.reject(405)
            if self.headers.get("X-Forge-Token") != token:
                return self.reject()
            if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_address[1]}":
                return self.reject()
            if self.headers.get("Content-Type") != "application/json":
                return self.reject(415)
            length_str = self.headers.get("Content-Length", "")
            if not length_str.isascii() or not length_str.isdecimal():
                return self.reject(411)
            length = int(length_str)
            if length == 0 or length > MAX_DRAFT_BYTES:
                return self.reject(413)
            try:
                value = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                return self.send_json(400, {"error": "Invalid JSON draft"})
            if route == "/api/lab/start":
                try:
                    return self.send_json(202, lab_session.start(value))
                except ValueError:
                    return self.reject(409)
            if route == "/api/lab/cancel":
                if value != {"operation": "cancel-disposable-qemu-install"}:
                    return self.reject(400)
                try:
                    return self.send_json(200, lab_session.cancel())
                except ValueError:
                    return self.reject(409)
            return self.send_json(200, validate_draft(value))

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



def open_preview_browser(url: str) -> None:
    """Start an isolated XWayland browser for Forge's live-ISO preview.

    Chromium forwards launches to an already running instance with the SAME
    profile. That silently discards subsequent GPU/ozone switches, which
    explains why toggling flags did not fix the text-less VM screenshot.
    Use a fresh PRIVATE profile and X11/XWayland in this non-accelerated VM
    instead of relying on the broken native Wayland glyph rasterizer.
    Normal hosts keep their configured default browser.
    """
    if os.environ.get("EDOS_FORGE_SOFTWARE_BROWSER") == "1":
        browser = shutil.which("brave") or shutil.which("brave-browser")
        if browser:
            # Runtime dir disappears at logout; no persistent credentials,
            # browsing history or browser-profile contention. mkdtemp=0700.
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            if not runtime or not os.path.isdir(runtime):
                runtime = None
            profile = tempfile.mkdtemp(prefix="edos-forge-", dir=runtime)
            try:
                subprocess.Popen(
                    [browser,
                     f"--user-data-dir={profile}",
                     "--ozone-platform=x11",
                     "--disable-gpu",
                     "--disable-gpu-rasterization",
                     "--disable-gpu-compositing",
                     "--disable-zero-copy",
                     "--disable-features=Vulkan",
                     "--no-first-run",
                     "--no-default-browser-check",
                     "--new-window", url],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True,
                    start_new_session=True,
                    env={**os.environ, "LIBGL_ALWAYS_SOFTWARE": "1",
                         "GDK_BACKEND": "x11"},
                )
                return
            except OSError:
                # The browser never started; remove the unused profile and
                # fall back to the host's browser for an actionable display.
                shutil.rmtree(profile, ignore_errors=True)
    webbrowser.open(url)


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
        opener = threading.Timer(0.6, lambda: open_preview_browser(url))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nPreview stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
