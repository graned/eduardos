#!/usr/bin/env python3
"""One-shot Forge installation-service *rehearsal*: NO DISK WRITES.

PR #41 combines the independently root-selected local preflight
(PR #37), read-only physical manifest (PR #40), and kernel-authenticated
sealed LUKS/account FD transport (PRs #35-36). It never runs a formatter,
mounts anything, hashes a password or installs NixOS.

This module does not bind a socket, start a daemon, implement a CLI,
install a polkit rule, or grant an execution token. A future physical
writer must NOT use success here as authorization.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os

import forge_authorization as auth
import forge_disk_identity as identity
import forge_local_ipc as ipc
import forge_local_service as local
import forge_physical_preview as preview
import forge_privileged_protocol as protocol

SCHEMA = "eduardos.forge.execution-rehearsal.v1"
_NO_WRITE_FLAGS = (
    "write_operations_enabled",
    "destructive_disk_operations_enabled",
    "credential_writes_enabled",
    "authorization_to_write",
)
_EXPECTED_PHASE_IDS = tuple(name for name, _ in preview._INTENDED_PHASES)


class Refused(ValueError):
    pass


def _report(status: str, *, digest: str | None = None) -> dict:
    result = {"version": SCHEMA, "status": status}
    result.update({field: False for field in _NO_WRITE_FLAGS})
    if digest is not None:
        result["manifest_sha256"] = digest
        result["credential_transport_verified"] = True
        result["note"] = "Dry-run only. No password used and no disk write authorized."
    return result


class OneShotExecutionRehearsal:
    """Trusted root policy -> local consent -> preview -> sealed FD -> recheck.

    All bindings are selected independently by the root-side caller via
    TrustedIntent. Both sockets are supplied by the caller and must have
    the same exact SO_PEERCRED identity. The peer cannot supply a new
    review, hostname, operation or manifest on the credential channel.

    Python cannot guarantee total erasure of immutable strings; the
    existing sealed-FD reader clears mutable buffers upon context exit.
    """

    def __init__(self, trusted: local.TrustedIntent) -> None:
        if not isinstance(trusted, local.TrustedIntent):
            raise Refused("Independent root-selected intent is required")
        if trusted.used:
            raise Refused("Trusted disk consent was already consumed")
        self._trusted = trusted
        self._review = copy.deepcopy(trusted.review)
        self._username = trusted.username
        self._hostname = trusted.hostname
        self._peer = trusted.peer
        self._deadline = trusted.deadline
        self._consumed = False

    def _assert_binding(self) -> None:
        intent = self._trusted
        if (intent.review != self._review
                or intent.username != self._username
                or intent.hostname != self._hostname
                or intent.peer != self._peer
                or intent.deadline != self._deadline):
            raise Refused("Root-selected disk, account or peer policy changed")
        if intent.clock() >= self._deadline:
            raise Refused("Installation rehearsal consent expired")
        if identity.boot_id() != self._review["snapshot"]["boot_id"]:
            raise Refused("Boot changed after root-side disk review")

    def _root_request(self) -> io.BytesIO:
        """Create a read-only request from root policy, never peer bytes."""
        request = {
            "version": protocol.SCHEMA,
            "operation": protocol.OPERATION,
            "review": copy.deepcopy(self._review),
            "confirmation": auth.confirm_text(
                self._review["snapshot"]["stable_id"]
            ),
            "username": self._username,
            "hostname": self._hostname,
        }
        return io.BytesIO(identity.canonical(request))

    def _verified_preview(self) -> dict:
        report = preview.preview_request(self._root_request())
        if (not isinstance(report, dict)
                or report.get("version") != preview.SCHEMA
                or report.get("status") != "preview-read-only"
                or any(report.get(flag) is not False
                       for flag in _NO_WRITE_FLAGS)):
            raise Refused("Read-only physical manifest was not approved")
        manifest = report.get("manifest")
        required_manifest = {
            "version", "kind", "disk_id", "target_devno", "boot_id",
            "disk_review_sha256", "account", "hostname",
            "storage_intent", "intended_phases", *_NO_WRITE_FLAGS,
        }
        if (not isinstance(manifest, dict)
                or set(manifest) != required_manifest
                or manifest.get("version") != preview.SCHEMA
                or manifest.get("kind") != "non-executable-installation-preview"
                or any(manifest.get(flag) is not False
                       for flag in _NO_WRITE_FLAGS)):
            raise Refused("Physical manifest has unexpected permissions")
        snap = self._review["snapshot"]
        if (manifest.get("disk_id") != snap["stable_id"]
                or manifest.get("target_devno") != snap["device"]["maj:min"]
                or manifest.get("boot_id") != snap["boot_id"]
                or manifest.get("disk_review_sha256") != self._review["sha256"]
                or manifest.get("account") != self._username
                or manifest.get("hostname") != self._hostname):
            raise Refused("Physical manifest differs from trusted root selection")
        phases = manifest.get("intended_phases")
        expected_storage = {
            "partition_table": "gpt",
            "esp_size_mib": 1024,
            "esp_filesystem": "vfat",
            "encryption": "luks2",
            "encrypted_filesystem": "btrfs",
            "subvolumes": list(preview._SUBVOLUMES),
            "mountpoints": list(preview._MOUNTPOINTS),
        }
        if manifest.get("storage_intent") != expected_storage:
            raise Refused("Physical storage layout differs from audited intent")
        if (not isinstance(phases, list)
                or len(phases) != len(_EXPECTED_PHASE_IDS)
                or any(
                    not isinstance(item, dict)
                    or set(item) != {"id", "description", "executable"}
                    or item.get("executable") is not False
                    or (item.get("id"), item.get("description")) != expected
                    for item, expected in zip(phases, preview._INTENDED_PHASES)
                )):
            raise Refused("Physical installation phases are not read-only")
        digest = report.get("manifest_sha256")
        if (not isinstance(digest, str)
                or digest != hashlib.sha256(
                    identity.canonical(manifest)
                ).hexdigest()):
            raise Refused("Physical manifest checksum changed")
        return report

    def run(self, preflight_conn, credentials_conn) -> dict:
        """Attempt exactly once; never return a token, FD, or plaintext."""
        if self._consumed:
            return _report("refused")
        self._consumed = True
        try:
            # Non-root callers do not even inspect incoming socket data.
            if os.geteuid() != 0:
                raise Refused("Execution rehearsal must run as root")
            if preflight_conn is credentials_conn:
                raise Refused("Separate preflight and credential sockets required")
            if (preflight_conn.fileno() < 0
                    or preflight_conn.fileno() == credentials_conn.fileno()):
                raise Refused("Invalid or duplicate Unix connections")
            self._assert_binding()
            # Verify both peers BEFORE local consent, a review or receiving
            # any credentials. Neither socket can select its own identity.
            ipc._verify_peer(preflight_conn, self._peer)
            ipc._verify_peer(credentials_conn, self._peer)

            # One-shot root local consent & real read-only target review.
            if local.serve_one_connected(preflight_conn, self._trusted) is not True:
                raise Refused("Local root-side preflight was refused")
            if self._trusted.used is not True:
                raise Refused("Local root-side preflight was not consumed")
            self._assert_binding()

            # The manifest comes from a second root-side physical audit,
            # NEVER from the peer. It cannot authorize any write.
            first = self._verified_preview()
            ipc._verify_peer(credentials_conn, self._peer)
            self._assert_binding()

            # Receive TWO separate sealed memfds. There is intentionally
            # no storage, password hashing, logging or secret serialization.
            with ipc.OneShotLocalReceiver(
                credentials_conn, self._peer
            ).consume() as material:
                if not material.luks or not material.account:
                    raise Refused("Both sealed credential roles required")
                self._assert_binding()
                # Recheck hardware/boot/active mounts AFTER credential
                # reception, while mutable buffers are still owned by
                # the context manager. They are wiped on ANY exit path.
                second = self._verified_preview()
                if (first["manifest_sha256"] != second["manifest_sha256"]
                        or first["manifest"] != second["manifest"]):
                    raise Refused("Disk plan changed after receiving credentials")
                self._assert_binding()
            return _report(
                "rehearsal-complete-read-only",
                digest=first["manifest_sha256"],
            )
        except Exception:
            # Never echo raw exceptions, disk ID, peer details or secrets.
            # NOTE: a refusal MUST NOT trigger an automatic retry.
            return _report("refused")
