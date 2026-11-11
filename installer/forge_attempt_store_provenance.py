"""Read-only provenance checks for a proposed durable Forge attempt store.

This module checks that the selected path appears as an explicit local
filesystem mount in kernel mountinfo. It is NOT a durability guarantee:
the future privileged installer must independently verify filesystem,
physical provenance, root ownership and persistence across actual reboots
before using the attempt-marker primitive to guard destructive writes.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

ALLOWED_FILESYSTEMS = frozenset(("ext4", "xfs", "btrfs"))
BLOCK_SOURCE = re.compile(r"/dev/(?:[a-zA-Z0-9_.+-]+|mapper/[a-zA-Z0-9_.+-]+)\Z")
DEVNO = re.compile(r"[0-9]+:[0-9]+\Z")


class Refused(ValueError):
    pass


def mount_evidence(mountpoint: str, mountinfo: str) -> dict:
    """Extract a unique local mountpoint record without executing anything."""
    if (not isinstance(mountpoint, str) or not mountpoint.startswith("/")
            or mountpoint == "/" or ".." in mountpoint.split("/")
            or not isinstance(mountinfo, str)):
        raise Refused("Invalid persistent mountpoint or kernel evidence")
    matches = []
    for line in mountinfo.splitlines():
        fields = line.split(" ")
        if len(fields) < 10 or fields.count("-") != 1:
            raise Refused("Malformed kernel mount table")
        sep = fields.index("-")
        if sep + 3 >= len(fields) or not DEVNO.fullmatch(fields[2]):
            raise Refused("Malformed kernel mount identity")
        if fields[4] == mountpoint:
            matches.append(fields)
    if len(matches) != 1:
        raise Refused("Persistent store must be an explicit, unique filesystem mountpoint")
    fields = matches[0]
    sep = fields.index("-")
    fstype, source = fields[sep + 1], fields[sep + 2]
    mount_options = set(fields[5].split(","))
    if fstype not in ALLOWED_FILESYSTEMS or not BLOCK_SOURCE.fullmatch(source):
        raise Refused("Attempt store is not backed by an allowed local block filesystem")
    if "ro" in mount_options or "rw" not in mount_options:
        raise Refused("Attempt store is not mounted read-write")
    if fields[3] != "/":
        raise Refused("Attempt store must use the filesystem root, not a bind subdirectory")
    return {
        "status": "candidate-local-mount",
        "mountpoint": mountpoint,
        "devno": fields[2],
        "source": source,
        "fstype": fstype,
        "write_operations_enabled": False,
        "authorization_to_write": False,
        "durability_proven": False,
    }


def check_candidate_directory(directory: Path, mountinfo: str) -> dict:
    """Check metadata + explicit mount evidence, never create a directory.

    This checks an existing directory and is deliberately not integrated
    with the current QEMU lab formatter or physical-device execution path.
    """
    path = Path(directory)
    if not path.is_absolute() or str(path) == "/" or not path.parts:
        raise Refused("Attempt directory must be an absolute dedicated mountpoint")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise Refused("Attempt store directory is missing") from exc
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700):
        raise Refused("Attempt store must be owned by caller with mode 0700")
    return mount_evidence(str(path), mountinfo)
