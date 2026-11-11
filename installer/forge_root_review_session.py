"""One-shot root-side FINAL REVIEW of physical install policy (NO WRITES).

Builds on the existing trusted kernel-peer / local-consent session. The
fixed immutable inputs must originate from a trusted root-side controller,
NOT the browser or socket request. Never runs Disko, consumes secrets,
creates a writer or exposes an authorization capability.

This library does not bind a listening socket or install a daemon.
"""
from __future__ import annotations

import io
import os
import socket
import subprocess
import json

import forge_authorization as auth
import forge_backend as backend
import forge_disk_identity as identity
import forge_execution_gate as gate
import forge_local_service as local
import forge_privileged_protocol as protocol


class Refused(ValueError):
    pass


def assess_connected(conn: socket.socket, trusted: local.TrustedIntent, *,
                     disko_script: str, system_closure: str) -> bool:
    """Consume a peer-pinned local session and return only review evidence.

    No caller, socket frame or disk-review hash can authorize execution.
    The root controller is responsible for independently choosing immutable
    closure inputs; this interface exposes no CLI or browser entrypoint.
    """
    result = local._redacted_refusal()
    accepted = False
    try:
        if not isinstance(trusted, local.TrustedIntent) or os.geteuid() != 0:
            raise Refused("Trusted root-side review session required")
        trusted.consume(conn)  # one shot, kernel peer identity + local consent
        raw = local._receive_request(conn)  # refuses and closes unexpected FDs
        if (trusted.clock() >= trusted.deadline
                or identity.boot_id() != trusted.review["snapshot"]["boot_id"]):
            raise Refused("Consent or boot session no longer valid")
        request = protocol.parse_request(io.BytesIO(raw))
        snapshot = trusted.review["snapshot"]
        if (request.review != trusted.review
                or request.username != trusted.username
                or request.hostname != trusted.hostname
                or request.confirmation != auth.confirm_text(snapshot["stable_id"])):
            raise Refused("Review differs from independently selected root intent")
        # This opens an O_RDONLY held block-device descriptor, then closes it
        # before returning. No writable device descriptor can leave the scope.
        with backend.prepare_target(
            trusted.review, request.confirmation,
            username=trusted.username, hostname=trusted.hostname
        ) as held:
            assessment = gate.review_before_execution(
                held, disko_script=disko_script, system_closure=system_closure
            )
        if (assessment.get("status") != "final-review-only"
                or assessment.get("executable") is not False
                or assessment.get("write_operations_enabled") is not False
                or assessment.get("destructive_disk_operations_enabled") is not False
                or assessment.get("authorization_to_write") is not False):
            raise Refused("Execution review unexpectedly supplied authority")
        result = {
            "version": "eduardos.forge.final-review.v1",
            "status": "reviewed-read-only",
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "authorization_to_write": False,
            "executable": False,
        }
        accepted = True
    except (Refused, local.Refused, auth.Refused, identity.Refused,
            backend.Refused, gate.Refused, protocol.Refused,
            OSError, TypeError, ValueError, KeyError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        result = {
            "version": "eduardos.forge.final-review.v1",
            "status": "refused",
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "authorization_to_write": False,
            "executable": False,
        }
    response = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    if len(response) > local.MAX_PACKET:
        raise Refused("Unexpected final-review response length")
    old_timeout = conn.gettimeout()
    try:
        conn.settimeout(local.ipc.IO_TIMEOUT_SECONDS)
        count = conn.send(response)
        if count != len(response):
            raise Refused("Incomplete final-review response")
    except (OSError, TimeoutError) as exc:
        raise Refused("Unable to deliver final-review response") from exc
    finally:
        conn.settimeout(old_timeout)
    return accepted
