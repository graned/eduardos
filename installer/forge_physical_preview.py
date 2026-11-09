#!/usr/bin/env python3
"""Forge physical installation *execution preview*, with NO write API.

This is a deterministic, non-executable account of the intended storage
layout and installation phases. It is NOT an installer, a Disko runner,
an execution authorization, a command template, or a reusable capability.

The root-only caller must supply one PR #33 "attest-target" request.
The existing Forge root backend independently rechecks current boot,
disk identity, live-media ancestry, mounts and swap, and holds the selected
block device OPEN READ-ONLY while this preview is computed. We recheck
topology before returning, then close the held descriptor.

No operation here formats, mounts, writes credentials or installs NixOS.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import subprocess
import sys

import forge_backend as backend
import forge_disk_identity as identity
import forge_privileged_guard as guard
import forge_privileged_protocol as protocol

SCHEMA = "eduardos.forge.physical-preview.v1"

# An immutable *description*, not executable steps or a runbook for a
# privileged process. Actual writes require a separately reviewed writer
# with an entirely separate authorization/credential interface.
_INTENDED_PHASES = (
    ("partition-gpt", "Create a GPT partition table"),
    ("esp-vfat", "Create a 1 GiB EFI system partition (FAT)"),
    ("encrypt-luks2", "Encrypt the remainder with LUKS2"),
    ("btrfs-subvolumes", "Create five Btrfs subvolumes"),
    ("attest-mounts", "Verify six kernel mounted filesystem sources"),
    ("stage-account", "Provision an encrypted persisted user hash"),
    ("install-nixos", "Install the eduardOS system closure"),
    ("verify-boot", "Verify encrypted UEFI boot and user login"),
)
_SUBVOLUMES = ("@root", "@home", "@nix", "@persist", "@snapshots")
_MOUNTPOINTS = ("/", "/boot", "/home", "/nix", "/persist", "/.snapshots")


class Refused(ValueError):
    pass


class OneShotPhysicalPreview:
    """Root-side single-use preview bound to an already-held disk handle.

    This is NOT an authorization object; its only public action, build(),
    returns JSON-serializable READ-ONLY descriptive data.
    """

    def __init__(self, held: backend.HeldTarget) -> None:
        if not isinstance(held, backend.HeldTarget):
            raise Refused("Expected an independently prepared root-held disk")
        self._held = held
        # Freeze the *value*, not the mutable dictionary provided by caller.
        self._initial_review = copy.deepcopy(held.review)
        self._initial_devno = held.devno
        self._initial_username = held.username
        self._initial_hostname = held.hostname
        self._consumed = False

    def build(self) -> dict:
        if self._consumed:
            raise Refused("Physical installation preview already consumed")
        self._consumed = True  # even failed first attempts cannot retry
        if os.geteuid() != 0:
            raise Refused("Only root may review a held physical disk")
        held = self._held
        if (held.review != self._initial_review
                or held.devno != self._initial_devno
                or held.username != self._initial_username
                or held.hostname != self._initial_hostname):
            raise Refused("Held target changed since initial preparation")
        review = self._initial_review
        snapshot = review["snapshot"]
        if (review.get("write_operations_enabled") is not False
                or snapshot.get("eligible") is not True
                or snapshot.get("blockers") != []):
            raise Refused("Physical disk was not eligible for a review")

        # Do not assume a prior read-only proof is still fresh. Identity
        # verification includes current boot, by-id mapping and full
        # partition/mount metadata. The backend holds the FD O_RDONLY.
        first = identity.probe()
        identity.verify(review, data=first)
        held._fresh_device(first)
        proof = guard.privileged_preflight(review, lsblk_data=first)
        if (proof.get("status") != "preflight-passed"
                or proof.get("write_operations_enabled") is not False
                or proof.get("target_devno") != held.devno
                or proof.get("disk_id") != snapshot["stable_id"]
                or proof.get("disk_review_sha256") != review["sha256"]):
            raise Refused("Independent active-system disk audit refused")

        # Audit again after the slower ancestry/mount checks; a
        # replacement or hotplug after this check still cannot yield an
        # authorized writer because NO WRITER EXISTS in this module.
        second = identity.probe()
        identity.verify(review, data=second)
        held._fresh_device(second)

        # Keep this manifest free of shell commands, derived target paths,
        # cryptsetup arguments, plaintext credentials and executable FDs.
        manifest = {
            "version": SCHEMA,
            "kind": "non-executable-installation-preview",
            "disk_id": snapshot["stable_id"],
            "target_devno": held.devno,
            "boot_id": snapshot["boot_id"],
            "disk_review_sha256": review["sha256"],
            "account": held.username,
            "hostname": held.hostname,
            "storage_intent": {
                "partition_table": "gpt",
                "esp_size_mib": 1024,
                "esp_filesystem": "vfat",
                "encryption": "luks2",
                "encrypted_filesystem": "btrfs",
                "subvolumes": list(_SUBVOLUMES),
                "mountpoints": list(_MOUNTPOINTS),
            },
            "intended_phases": [
                {"id": name, "description": description,
                 "executable": False}
                for name, description in _INTENDED_PHASES
            ],
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "credential_writes_enabled": False,
            "authorization_to_write": False,
        }
        # SHA-256 detects accidental preview drift. It does NOT sign the
        # manifest, authenticate its origin or grant execution authority.
        digest = hashlib.sha256(identity.canonical(manifest)).hexdigest()
        return {
            "version": SCHEMA,
            "status": "preview-read-only",
            "manifest": manifest,
            "manifest_sha256": digest,
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "credential_writes_enabled": False,
            "authorization_to_write": False,
            "note": "Review only. No disk write, credential or install is authorized.",
        }


def preview_request(stream) -> dict:
    """One bounded PR #33 request; no new execute/format operation accepted."""
    if os.geteuid() != 0:
        raise Refused("Root-only physical installation preview")
    request = protocol.parse_request(stream)
    with backend.prepare_target(
        request.review, request.confirmation,
        username=request.username, hostname=request.hostname,
    ) as held:
        return OneShotPhysicalPreview(held).build()


def main(argv: list[str] | None = None, *, input_stream=None,
         output_stream=None) -> int:
    parser = argparse.ArgumentParser(
        description="Forge root-only physical installer intent preview: NO DISK WRITES"
    )
    parser.parse_args(argv)
    stream = sys.stdin.buffer if input_stream is None else input_stream
    output = sys.stdout if output_stream is None else output_stream
    try:
        result = preview_request(stream)
        status = 0
    except (Refused, protocol.Refused, backend.Refused, identity.Refused,
            guard.Refused, OSError, TypeError, ValueError, KeyError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Never echo a device ID, account, request body or exception.
        result = {
            "version": SCHEMA,
            "status": "refused",
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "credential_writes_enabled": False,
            "authorization_to_write": False,
        }
        status = 2
    output.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
