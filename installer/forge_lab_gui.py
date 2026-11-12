#!/usr/bin/env python3
"""Disposable-QEMU root-operated Forge GUI integration.

This launch mode is NOT part of the eduardOS ISO or packages. It exists
only as a pinned Nix QEMU test tool. Operator consent is independent of
the browser: the CLI must be deliberately invoked by the trusted local
root test/operator with the exact disposable target confirmation.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import getpass
import fcntl
import secrets
import sys
from http.server import ThreadingHTTPServer

import forge_gui
import forge_authorization as authorization
import forge_secret_handoff as handoff
from forge_lab_gui_session import LabInstallSession, Refused


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Forge disposable-QEMU-only lab GUI")
    parser.add_argument("--executor", required=True, help="Fixed immutable Nix lab executable")
    parser.add_argument("--operator-confirm", required=True,
                        help="Explicit root-side disposable QEMU consent phrase")
    parser.add_argument("--trusted-console-credentials", action="store_true",
                        help="Collect both secrets at the local root TTY into sealed memfds")
    parser.add_argument("--trusted-sealed-luks-fd", type=int, default=None,
                        help="QEMU harness: inherited independently created sealed LUKS fd")
    parser.add_argument("--trusted-sealed-account-fd", type=int, default=None,
                        help="QEMU harness: inherited independently created sealed account fd")
    args = parser.parse_args(argv)
    try:
        with ExitStack() as stack:
            handles = None
            inherited = (args.trusted_sealed_luks_fd, args.trusted_sealed_account_fd)
            if any(fd is not None for fd in inherited):
                if (args.trusted_console_credentials or any(fd is None for fd in inherited)
                        or any(fd < 0 for fd in inherited)):
                    raise Refused("Sealed QEMU descriptor pair is incomplete")
                # subprocess pass_fds clears FD_CLOEXEC during exec; restore it
                # before verifying both immutable descriptor roles and seals.
                for fd in inherited:
                    fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
                handles = handoff.CredentialFDs(*inherited)
            elif args.trusted_console_credentials:
                # Explicit root/operator mode, NOT the HTTP/browser UI.
                if not sys.stdin.isatty():
                    raise Refused("Trusted credential entry requires an actual local TTY")
                first = getpass.getpass("Disposable VM LUKS passphrase: ")
                again = getpass.getpass("Repeat VM LUKS passphrase: ")
                authorization.validate_secret_pair(first, again, kind="LUKS")
                second = getpass.getpass("Disposable VM account password: ")
                repeated = getpass.getpass("Repeat VM account password: ")
                authorization.validate_secret_pair(second, repeated, kind="Account")
                handles = stack.enter_context(handoff.sealed_credential_pair(first, second))
                # CPython cannot guarantee zeroization of immutable strings.
                del first, again, second, repeated
            session = LabInstallSession(
                args.executor, args.operator_confirm, sealed_credentials=handles,
            )
            token = secrets.token_urlsafe(32)
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0), forge_gui.make_handler(token, lab_session=session)
            )
            print("eduardOS Forge disposable QEMU LAB · NO PHYSICAL INSTALL", flush=True)
            print(f"Open locally: http://127.0.0.1:{server.server_port}/?token={token}", flush=True)
            try:
                server.serve_forever(poll_interval=0.25)
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except (Refused, OSError, ValueError, handoff.Refused, authorization.Refused):
        print("REFUSED: independent QEMU-only root operator/credentials rejected",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
