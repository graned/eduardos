#!/usr/bin/env python3
"""Manual, root-only Forge read-only preflight on a physical Linux VT.

One invocation, one root-owned Unix listener, one pinned root client,
one interactive foreground /dev/ttyN operator challenge, then exit.

NO daemon, browser endpoint, sudo/polkit bridge, credential receiving,
formatting, mounting, QEMU lab invocation or installation. This command
is an OPTIONAL package and is not enabled at boot or in the live ISO.
"""
from __future__ import annotations

import argparse
import os
import select
import socket
import sys

import forge_console_consent as console
import forge_disk_identity as identity
import forge_local_ipc as ipc
import forge_local_service as local
import forge_socket_lifecycle as lifecycle


class Refused(ValueError):
    pass


def _pidfd_alive(pid_fd: int) -> bool:
    """Pinned pidfd must remain live: refuse PID exit/reuse before service."""
    poller = select.poll()
    poller.register(pid_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    return not bool(poller.poll(0))


def run_once(disk_id: str, username: str, hostname: str,
             client_pid: int, console_tty: str, *,
             capture=identity.capture,
             listener=lifecycle.root_listener,
             prompt=console.request_local_consent,
             serve=local.serve_one_connected) -> bool:
    """Root-selected request policy. No client data can pick an action."""
    if os.geteuid() != 0:
        raise Refused("Forge local preflight requires root")
    if (type(client_pid) is not int or client_pid <= 1
            or client_pid == os.getpid()):
        raise Refused("A separate trusted local client PID is mandatory")
    if (not isinstance(disk_id, str)
            or not identity.re.fullmatch(
                r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+", disk_id)):
        raise Refused("Explicit stable disk identity required")
    if not console._CONSOLE_RE.fullmatch(console_tty):
        raise Refused("Only an explicit physical virtual console is accepted")

    # Require a live pidfd, rather than merely trusting a textual PID that
    # could exit and be recycled before accepting a socket connection.
    try:
        pid_fd = os.pidfd_open(client_pid, 0)
    except (OSError, AttributeError):
        raise Refused("Trusted client process cannot be pinned by pidfd") from None
    try:
        if not _pidfd_alive(pid_fd):
            raise Refused("Selected local client is no longer running")
        # The root process independently probes current disk topology.
        # Snapshot and boot ID are never selected by socket JSON.
        review = capture(disk_id)
        expected = ipc.PeerIdentity(client_pid, 0, 0)
        trusted = local.TrustedIntent(
            peer=expected, review=review,
            username=username, hostname=hostname,
            local_consent=lambda challenge: prompt(challenge, console_tty),
        )
        # Only the root process may use the existing fixed /run socket.
        # No listener or directory is installed by this package.
        with listener() as server:
            connection, _ = server.accept()
            with connection:
                if not _pidfd_alive(pid_fd):
                    raise Refused("Pinned local client exited before connect")
                outcome = serve(connection, trusted)
                if not _pidfd_alive(pid_fd):
                    raise Refused("Pinned local client exited during preflight")
                return outcome
    finally:
        os.close(pid_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="eduardOS root/VT-only one-shot READ-ONLY disk preflight"
    )
    parser.add_argument("--disk-id", required=True,
                        help="Exact stable /dev/disk/by-id disk identity")
    parser.add_argument("--username", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--client-pid", required=True, type=int,
                        help="PID of a separately trusted ROOT client")
    parser.add_argument("--console", required=True,
                        help="Active foreground virtual console, e.g. /dev/tty2")
    args = parser.parse_args(argv)
    try:
        ok = run_once(
            args.disk_id, args.username, args.hostname,
            args.client_pid, args.console,
        )
    except (Refused, console.Refused, local.Refused, lifecycle.Refused,
            ipc.Refused, identity.Refused, OSError, socket.timeout,
            ValueError, TypeError):
        print("REFUSED: root-only read-only Forge preflight was not approved",
              file=sys.stderr)
        return 2
    print("READ-ONLY PREFLIGHT PASSED" if ok
          else "REFUSED: read-only preflight did not pass")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
