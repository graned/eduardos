#!/usr/bin/env python3
"""Peer-verified, one-shot AF_UNIX credential FD transport rehearsal.

NOT a privileged service, daemon, GUI endpoint or physical installer.
A separately trusted process must provide connected local sockets and
pin the expected peer identity from its own authorization policy.

Messages carry only a fixed protocol marker. Actual LUKS and account
secrets travel via SCM_RIGHTS as separate sealed Linux memfds. Neither
possession of a socket nor SO_PEERCRED establishes disk-write consent.
"""
from __future__ import annotations

from array import array
from contextlib import contextmanager
from dataclasses import dataclass
import os
import socket
import struct
from collections.abc import Iterator

import forge_credentials as credentials
import forge_secret_handoff as handoff


PROTOCOL_MARKER = b"EDOS-CREDENTIAL-FDS-V1"
IO_TIMEOUT_SECONDS = 3.0
_PEERCRED_FORMAT = "3i"
_PEERCRED_SIZE = struct.calcsize(_PEERCRED_FORMAT)
_FD_SIZE = array("i").itemsize
# Allow one extra FD to be received so it can be rejected and closed;
# still fail on MSG_CTRUNC if a sender sends even more.
_ANCILLARY_SPACE = socket.CMSG_SPACE(3 * _FD_SIZE)


class Refused(ValueError):
    pass


@dataclass(frozen=True)
class PeerIdentity:
    pid: int
    uid: int
    gid: int

    def __post_init__(self):
        if (not all(type(n) is int for n in (self.pid, self.uid, self.gid))
                or self.pid <= 0 or self.uid < 0 or self.gid < 0):
            raise Refused("Invalid trusted peer identity")


def _verify_peer(conn: socket.socket, expected: PeerIdentity) -> None:
    """Verify the OS kernel peer identity for one connected socket.

    Never derive 'expected' from a message on that socket, browser input
    or a caller-provided JSON request. A real root service must derive it
    independently from an authenticated local login/authorization policy.
    """
    if not isinstance(expected, PeerIdentity):
        raise Refused("Expected trusted peer identity is mandatory")
    if (conn.family != socket.AF_UNIX
            or conn.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            != socket.SOCK_SEQPACKET):
        raise Refused("Only connected Unix seqpacket sockets are supported")
    try:
        raw = conn.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED_SIZE,
        )
        if len(raw) != _PEERCRED_SIZE:
            raise Refused("Kernel peer credentials were incomplete")
        found = PeerIdentity(*struct.unpack(_PEERCRED_FORMAT, raw))
    except (OSError, ValueError, struct.error) as exc:
        raise Refused("Could not prove connected kernel peer identity") from exc
    if found != expected:
        raise Refused("Connected peer does not match the trusted allowlist")


def _distinct_fds(handles: handoff.CredentialFDs) -> None:
    if not isinstance(handles, handoff.CredentialFDs):
        raise Refused("Expected separate LUKS and account descriptors")
    try:
        first = handoff._assert_fd(handles.luks, credentials.LUKS_MEMFD_LABEL)
        second = handoff._assert_fd(handles.account, credentials.ACCOUNT_MEMFD_LABEL)
    except handoff.Refused as exc:
        raise Refused("Credential descriptors failed role or seal checks") from exc
    if (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino):
        raise Refused("Credential roles cannot share a memfd")


class OneShotLocalSender:
    """Transfer exactly two descriptors once, never plaintext or JSON."""

    def __init__(self, conn: socket.socket, expected_server: PeerIdentity):
        self._conn = conn
        self._expected = expected_server
        self._used = False

    def send(self, handles: handoff.CredentialFDs) -> None:
        if self._used:
            raise Refused("Local credential send already consumed")
        self._used = True  # Failed peer verification also consumes this sender.
        _verify_peer(self._conn, self._expected)
        _distinct_fds(handles)
        payload = array("i", [handles.luks, handles.account]).tobytes()
        previous = self._conn.gettimeout()
        try:
            self._conn.settimeout(IO_TIMEOUT_SECONDS)
            count = self._conn.sendmsg(
                [PROTOCOL_MARKER],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, payload)],
            )
        except (OSError, TimeoutError) as exc:
            raise Refused("Local credential descriptor send failed") from exc
        finally:
            self._conn.settimeout(previous)
        if count != len(PROTOCOL_MARKER):
            raise Refused("Local credential protocol packet was incomplete")


class OneShotLocalReceiver:
    """Validate kernel sender identity, then consume two sealed FDs once.

    Returned buffers are zeroed and all RECEIVED descriptors are closed on
    context exit, including on malformed messages or validation failures.
    The sender continues to own and close its original memfds.
    """

    def __init__(self, conn: socket.socket, expected_client: PeerIdentity):
        self._conn = conn
        self._expected = expected_client
        self._used = False

    @contextmanager
    def consume(self) -> Iterator[handoff.CredentialBuffers]:
        if self._used:
            raise Refused("Local credential receive already consumed")
        self._used = True
        received: list[int] = []
        try:
            # Reject before even reading or accepting ancillary descriptors.
            _verify_peer(self._conn, self._expected)
            if not hasattr(socket, "MSG_CMSG_CLOEXEC"):
                raise Refused("Kernel lacks close-on-exec ancillary receive")
            previous = self._conn.gettimeout()
            try:
                self._conn.settimeout(IO_TIMEOUT_SECONDS)
                packet, ancillary, flags, _ = self._conn.recvmsg(
                    len(PROTOCOL_MARKER) + 1,
                    _ANCILLARY_SPACE,
                    socket.MSG_CMSG_CLOEXEC,
                )
            except (OSError, TimeoutError) as exc:
                raise Refused("Local credential descriptor receive failed") from exc
            finally:
                self._conn.settimeout(previous)

            # Always collect the returned FDs before validating message
            # shape, so malformed frames cannot leak descriptors.
            bad_ancillary = False
            for level, kind, payload in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    if len(payload) % _FD_SIZE != 0:
                        bad_ancillary = True
                        continue
                    integers = array("i")
                    integers.frombytes(payload)
                    received.extend(integers)
                else:
                    bad_ancillary = True
            if (bad_ancillary
                    or flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC)
                    or packet != PROTOCOL_MARKER
                    or len(ancillary) != 1
                    or len(received) != 2):
                raise Refused("Unexpected local credential frame or FD count")
            handles = handoff.CredentialFDs(*received)
            with handoff.OneShotCredentialReader(handles).consume() as material:
                yield material
        finally:
            for fd in received:
                try:
                    os.close(fd)
                except OSError:
                    pass
