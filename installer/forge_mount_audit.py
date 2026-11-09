#!/usr/bin/env python3
"""Read-only verification of an already-mounted eduardOS target.

Used by QEMU storage integration tests. This command NEVER partitions,
formats, mounts, provisions credentials, or installs an OS. Passing this
audit is not an authorization to write to a physical device.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import forge_backend as backend
import forge_disk_identity as identity
import forge_privileged_guard as guard


class Refused(ValueError):
    pass


def audit(disk_path: str, *, lsblk_data: dict | None = None,
          mountinfo: str | None = None) -> dict:
    if not isinstance(disk_path, str) or not re.fullmatch(r"/dev/[A-Za-z0-9_./-]+", disk_path):
        raise Refused("Explicit whole block disk path is required")
    if ".." in disk_path.split("/"):
        raise Refused("Parent-directory traversal is forbidden")
    block = identity.probe() if lsblk_data is None else lsblk_data
    nodes, _ = guard.block_graph(block)
    matches = [(k, n) for k, n in nodes.items()
               if n.get("path") == disk_path and n.get("type") == "disk"]
    if len(matches) != 1:
        raise Refused("Target path must resolve to exactly one whole disk")
    target_devno, _ = matches[0]

    # Validate actual block inode rather than trusting lsblk's textual path.
    metadata = os.stat(disk_path)
    if not stat.S_ISBLK(metadata.st_mode):
        raise Refused("Target path is not a block device")
    actual_devno = f"{os.major(metadata.st_rdev)}:{os.minor(metadata.st_rdev)}"
    if actual_devno != target_devno:
        raise Refused("Kernel block device differs from lsblk target")

    mounts = (Path("/proc/self/mountinfo").read_text()
              if mountinfo is None else mountinfo)
    evidence = backend.attest_target_mounts(target_devno, block, mounts)
    return {
        "status": "verified-already-mounted-encrypted-target",
        "target_path": disk_path,
        "target_devno": target_devno,
        "luks_mapper_devno": evidence["encrypted_mapper_devno"],
        "mountpoints": evidence["verified_mountpoints"],
        "destructive_disk_operations_enabled": False,
        "credential_writes_enabled": False,
        "note": "Read-only evidence only; not installation or erasure authorization.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="eduardOS read-only audit of six mounted EFI/LUKS2/Btrfs filesystems"
    )
    parser.add_argument("--disk", required=True, help="Existing whole-disk path, e.g. /dev/vdb in QEMU")
    args = parser.parse_args(argv)
    try:
        result = audit(args.disk)
        print(json.dumps(result, indent=2))
        return 0
    except (Refused, backend.Refused, guard.Refused, OSError, ValueError,
            KeyError, TypeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
