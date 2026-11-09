#!/usr/bin/env python3
"""One-shot, root-only Forge preflight protocol. READ-ONLY, NO INSTALLATION.

The caller provides a previously reviewed disk snapshot and an exact local
confirmation. The root-side helper independently verifies the snapshot,
current boot, active mounts/swap and the by-id alias before holding the
selected *block device* open read-only for the duration of the request.

The response is evidence only: it grants NO capability to format, mount,
install, write credentials, invoke the QEMU lab installer or touch a disk.
No socket, daemon, privilege escalation, browser bridge or token exists.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
import subprocess
import sys

import forge_authorization as auth
import forge_backend as backend
import forge_disk_identity as identity
import forge_privileged_guard as guard

SCHEMA = "eduardos.forge.privileged.v1"
OPERATION = "attest-target"
MAX_REQUEST_BYTES = 64 * 1024
_REQUEST_FIELDS = frozenset({
    "version", "operation", "review", "confirmation", "username", "hostname"
})
_REVIEW_FIELDS = frozenset({"snapshot", "sha256", "write_operations_enabled"})
_STABLE_ID = re.compile(r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+\\Z")


class Refused(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    review: dict
    confirmation: str
    username: str
    hostname: str


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused("Duplicate request field")
        result[key] = value
    return result


def _invalid_constant(_: str):
    raise Refused("Non-finite numbers are not valid JSON")


def parse_request(stream) -> Request:
    """Consume exactly one bounded UTF-8 JSON request; reject extra fields."""
    if stream is None or not callable(getattr(stream, "read", None)):
        raise Refused("Expected a readable binary input stream")
    raw = stream.read(MAX_REQUEST_BYTES + 1)
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_REQUEST_BYTES:
        raise Refused("Missing, oversized, or non-binary request")
    try:
        message = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_invalid_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Refused("Malformed UTF-8 JSON request") from exc
    if not isinstance(message, dict) or set(message) != _REQUEST_FIELDS:
        # Unknown fields include 'execute', 'password', 'target', 'shell',
        # 'format' and any future flags: no implicit privilege expansion.
        raise Refused("Request does not match the read-only protocol schema")
    if message["version"] != SCHEMA or message["operation"] != OPERATION:
        raise Refused("Unsupported privileged protocol operation or version")

    review = message["review"]
    if not isinstance(review, dict) or set(review) != _REVIEW_FIELDS:
        raise Refused("Invalid disk review envelope")
    if review["write_operations_enabled"] is not False:
        raise Refused("A disk review must explicitly prohibit writes")
    snap = review["snapshot"]
    if not isinstance(snap, dict):
        raise Refused("Disk review snapshot is malformed")
    disk_id = snap.get("stable_id")
    if not isinstance(disk_id, str) or not _STABLE_ID.fullmatch(disk_id):
        raise Refused("Only exact by-id disk identities are accepted")

    confirmation = message["confirmation"]
    if not isinstance(confirmation, str) or len(confirmation) > 512:
        raise Refused("Invalid local disk confirmation")
    # The independent root backend checks again against the snapshot.
    if confirmation != auth.confirm_text(disk_id):
        raise Refused("Exact disk confirmation required")
    username, hostname = message["username"], message["hostname"]
    if not isinstance(username, str) or not isinstance(hostname, str):
        raise Refused("Explicit username and hostname are required")
    try:
        auth.validate_user_settings(username, hostname)
    except auth.Refused as exc:
        raise Refused("Invalid installed account or host identity") from exc
    return Request(review, confirmation, username, hostname)


def handle_request(stream) -> dict:
    """Independently perform the existing root-only held-disk preflight.

    This is *not* a root writer, a reusable authorization handle or a disk
    erasure request. The block descriptor is closed before returning.
    """
    if os.geteuid() != 0:
        raise Refused("Root-only preflight boundary")
    request = parse_request(stream)
    with backend.prepare_target(
        request.review, request.confirmation,
        username=request.username, hostname=request.hostname,
    ) as held:
        # The existing prepare_target rechecks review freshness, topology,
        # live media and kernel block-device identity before opening O_RDONLY.
        # Return no handle, secret, nonce, token or executable operation.
        return {
            "version": SCHEMA,
            "status": "attested-read-only",
            "disk_id": held.review["snapshot"]["stable_id"],
            "disk_review_sha256": held.review["sha256"],
            "target_devno": held.devno,
            "username": held.username,
            "hostname": held.hostname,
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "credential_writes_enabled": False,
            "authorization_to_write": False,
            "note": "Attestation completed; descriptor closed. No write permitted.",
        }


def main(argv: list[str] | None = None, *, input_stream=None, output_stream=None) -> int:
    parser = argparse.ArgumentParser(
        description="One-shot ROOT-ONLY eduardOS physical target attestation; NO WRITES"
    )
    parser.parse_args(argv)  # no write flags, no disk path arguments
    stream = sys.stdin.buffer if input_stream is None else input_stream
    output = sys.stdout if output_stream is None else output_stream
    try:
        result = handle_request(stream)
        status = 0
    except (Refused, auth.Refused, backend.Refused, identity.Refused,
            guard.Refused, OSError, TypeError, ValueError, KeyError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Do not echo user-controlled payload, review data or input secrets.
        result = {
            "version": SCHEMA,
            "status": "refused",
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "credential_writes_enabled": False,
            "authorization_to_write": False,
        }
        status = 2
    output.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
