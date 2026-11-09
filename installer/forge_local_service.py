#!/usr/bin/env python3
"""Non-destructive, one-shot root-side local preflight session library.

NOT installed as a service, NOT connected to the browser or a disk writer.
The future root controller must separately select a trusted user/process,
capture a fresh disk review, and obtain LOCAL interactive consent.
A socket packet, peer PID, or a valid review alone is never consent.

This module accepts only a single read-only attestation request over an
already connected AF_UNIX SOCK_SEQPACKET socket. No LUKS or account
credentials are accepted on this channel; those remain separate.
"""
from __future__ import annotations

from array import array
import copy
from dataclasses import dataclass, field
import io
import json
import os
import secrets
import socket
import subprocess
import time
from collections.abc import Callable

import forge_authorization as auth
import forge_backend as backend
import forge_disk_identity as identity
import forge_local_ipc as ipc
import forge_privileged_protocol as protocol
import forge_privileged_guard as guard

MAX_PACKET = protocol.MAX_REQUEST_BYTES
CONSENT_TTL_SECONDS = 120
_ANCILLARY_SPACE = socket.CMSG_SPACE(3 * array("i").itemsize)


class Refused(ValueError):
    pass


@dataclass
class TrustedIntent:
    """Created by a trusted root-side controller, NEVER from socket JSON.

    The local_consent callback MUST be implemented by a trusted UI/TTY
    outside this library. A callback which returns the phrase automatically
    is NOT evidence of a human presence and is forbidden in production.
    """

    peer: ipc.PeerIdentity
    review: dict
    username: str
    hostname: str
    local_consent: Callable[[str], str]
    clock: Callable[[], float] = time.monotonic
    deadline: float = field(init=False)
    used: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.peer, ipc.PeerIdentity):
            raise Refused("Expected peer must be supplied by trusted policy")
        if not callable(self.local_consent) or not callable(self.clock):
            raise Refused("Root-side local consent and clock are required")
        if (not isinstance(self.review, dict)
                or set(self.review) != {
                    "snapshot", "sha256", "write_operations_enabled",
                } or self.review["write_operations_enabled"] is not False):
            raise Refused("Trusted review envelope is invalid")
        # Copy caller-owned dictionaries so later mutation cannot silently
        # redirect an already-confirmed local session to another disk.
        self.review = copy.deepcopy(self.review)
        snapshot = self.review["snapshot"]
        if (not isinstance(snapshot, dict)
                or set(snapshot) != protocol._SNAPSHOT_FIELDS
                or snapshot.get("schema") != identity.SCHEMA
                or snapshot.get("eligible") is not True
                or snapshot.get("blockers") != []
                or not isinstance(snapshot.get("stable_id"), str)
                or not protocol._STABLE_ID.fullmatch(snapshot["stable_id"])
                or not isinstance(snapshot.get("device"), dict)
                or set(snapshot["device"]) != set(identity.FIELDS)
                or not isinstance(snapshot.get("boot_id"), str)
                or self.review["sha256"] != identity.fingerprint(snapshot)):
            raise Refused("Trusted disk review is invalid")
        try:
            auth.validate_user_settings(self.username, self.hostname)
        except (auth.Refused, TypeError) as exc:
            raise Refused("Trusted installed-user settings are invalid") from exc
        self.deadline = self.clock() + CONSENT_TTL_SECONDS

    def consume(self, conn: socket.socket) -> None:
        if self.used:
            raise Refused("Trusted local session is already consumed")
        self.used = True
        if os.geteuid() != 0:
            raise Refused("Local preflight service requires root")
        if self.clock() >= self.deadline:
            raise Refused("Trusted local session expired")
        # This check is kernel-authenticated, not a remote-provided UID.
        try:
            ipc._verify_peer(conn, self.peer)
        except (ipc.Refused, OSError) as exc:
            raise Refused("Kernel peer identity does not match policy") from exc
        snap = self.review["snapshot"]
        if identity.boot_id() != snap["boot_id"]:
            raise Refused("Boot changed since trusted review")
        # Consent MUST come from a trusted *local* prompt, not socket data.
        phrase = auth.confirm_text(snap["stable_id"])
        try:
            spoken = self.local_consent(phrase)
        except BaseException:
            raise Refused("Trusted local consent was interrupted") from None
        if (not isinstance(spoken, str)
                or not secrets.compare_digest(spoken, phrase)):
            raise Refused("Trusted local disk confirmation refused")
        if self.clock() >= self.deadline or identity.boot_id() != snap["boot_id"]:
            raise Refused("Local consent expired or boot changed")


def _receive_request(conn: socket.socket) -> bytes:
    """Read one bounded packet. Close EVERY passed FD before refusal."""
    if not hasattr(socket, "MSG_CMSG_CLOEXEC"):
        raise Refused("Linux close-on-exec ancillary receive is required")
    received: list[int] = []
    previous = conn.gettimeout()
    try:
        try:
            conn.settimeout(ipc.IO_TIMEOUT_SECONDS)
            payload, ancillary, flags, _ = conn.recvmsg(
                MAX_PACKET + 1, _ANCILLARY_SPACE, socket.MSG_CMSG_CLOEXEC,
            )
        except (OSError, TimeoutError) as exc:
            raise Refused("Local preflight request could not be read") from exc
        finally:
            conn.settimeout(previous)

        bad = False
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                size = array("i").itemsize
                if len(data) % size:
                    bad = True
                numbers = array("i")
                numbers.frombytes(data[:len(data) - len(data) % size])
                received.extend(numbers)
            else:
                bad = True
        if (bad or ancillary or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
                or not payload or len(payload) > MAX_PACKET):
            raise Refused("Unexpected request packet or credential descriptors")
        return payload
    finally:
        for fd in received:
            try:
                os.close(fd)
            except OSError:
                pass


def _redacted_refusal() -> dict:
    return {
        "version": protocol.SCHEMA,
        "status": "refused",
        "write_operations_enabled": False,
        "destructive_disk_operations_enabled": False,
        "credential_writes_enabled": False,
        "authorization_to_write": False,
    }


def serve_one_connected(conn: socket.socket, trusted: TrustedIntent) -> bool:
    """Process exactly one read-only operation; no reusable login session.

    This function does not bind a socket, start a daemon, invoke Disko or
    expose a physical write capability. The caller owns the connection.
    """
    try:
        if not isinstance(trusted, TrustedIntent):
            raise Refused("Trusted root-side session is required")
        # Root, kernel peer identity, current boot and local TTY consent
        # MUST succeed before reading any request bytes.
        trusted.consume(conn)
        raw = _receive_request(conn)
        request = protocol.parse_request(io.BytesIO(raw))
        snap = trusted.review["snapshot"]
        # Review must match the independently root-side selected disk,
        # boot ID and account settings, not merely the network payload.
        if (request.review != trusted.review
                or request.review["sha256"] != trusted.review["sha256"]
                or request.username != trusted.username
                or request.hostname != trusted.hostname
                or request.confirmation != auth.confirm_text(snap["stable_id"])):
            raise Refused("Request differs from trusted local selection")
        # PR #33 repeats the physical disk identity/ancestry and by-id
        # checks while holding a READ-ONLY disk descriptor. Never write.
        result = protocol.handle_request(io.BytesIO(raw))
        status = result.get("status") == "attested-read-only"
    except (Refused, ipc.Refused, protocol.Refused, auth.Refused,
            identity.Refused, backend.Refused, guard.Refused,
            OSError, ValueError, TypeError, KeyError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # No attacker payload, device path, confirmation, secret, or raw
        # error message is returned when any authorization gate fails.
        result = _redacted_refusal()
        status = False
    response = json.dumps(result, separators=(",", ":"), sort_keys=True).encode()
    if len(response) > MAX_PACKET:
        raise Refused("Preflight response was unexpectedly oversized")
    previous = conn.gettimeout()
    try:
        conn.settimeout(ipc.IO_TIMEOUT_SECONDS)
        count = conn.send(response)
        if count != len(response):
            raise Refused("Incomplete local preflight response")
    except (OSError, TimeoutError) as exc:
        raise Refused("Local preflight response could not be sent") from exc
    finally:
        conn.settimeout(previous)
    return status
