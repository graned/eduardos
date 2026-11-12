#!/usr/bin/env python3
"""Disposable-QEMU root-operated Forge GUI integration.

This launch mode is NOT part of the eduardOS ISO or packages. It exists
only as a pinned Nix QEMU test tool. Operator consent is independent of
the browser: the CLI must be deliberately invoked by the trusted local
root test/operator with the exact disposable target confirmation.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from http.server import ThreadingHTTPServer

import forge_gui
from forge_lab_gui_session import LabInstallSession, Refused


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Forge disposable-QEMU-only lab GUI")
    parser.add_argument("--executor", required=True, help="Fixed immutable Nix lab executable")
    parser.add_argument("--operator-confirm", required=True,
                        help="Explicit root-side disposable QEMU consent phrase")
    args = parser.parse_args(argv)
    try:
        session = LabInstallSession(args.executor, args.operator_confirm)
    except (Refused, OSError, ValueError):
        print("REFUSED: independent QEMU-only root operator authorization failed",
              file=sys.stderr)
        return 2
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), forge_gui.make_handler(token, lab_session=session)
    )
    print("eduardOS Forge QEMU LAB · fixture credentials · NO PHYSICAL INSTALL", flush=True)
    print(f"Open locally: http://127.0.0.1:{server.server_port}/?token={token}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
