#!/usr/bin/env python3
"""Read-only, fail-closed installation disk identity contract.

This module cannot execute Disko, format a filesystem or mount a device.
The signed-off plan is deliberately NOT an authorization to write: the future
privileged installer must perform its own verification immediately before use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import forge_installer as preflight

SCHEMA = "eduardos.disk-review.v1"
MIN_BYTES = preflight.MIN_DISK_BYTES
ID_PREFIX = "/dev/disk/by-id/"
FIELDS = ("path", "size", "model", "serial", "wwn", "tran", "maj:min", "ro", "rm", "pttype")


class Refused(ValueError):
    pass


def probe() -> dict[str, Any]:
    result = subprocess.run(
        ["lsblk", "--json", "--bytes", "--output",
         "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,WWN,TRAN,MAJ:MIN,RO,RM,"
         "MOUNTPOINTS,FSTYPE,PTTYPE,PKNAME"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return json.loads(result.stdout)


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(canonical(snapshot)).hexdigest()


def flat_disks(data: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for node in preflight.all_nodes(data.get("blockdevices") or []):
        if node.get("type") == "disk":
            path = node.get("path")
            if not isinstance(path, str) or path in result:
                raise Refused("Disk inventory contains missing/duplicate disk paths")
            result[path] = node
    return result


def validated_ids(mapping: dict[str, str]) -> dict[str, str]:
    """Require unambiguous /dev/disk/by-id identities for individual disks."""
    seen: set[str] = set()
    output = {}
    for device, stable in mapping.items():
        if not (isinstance(device, str) and isinstance(stable, str)
                and stable.startswith(ID_PREFIX)
                and re.fullmatch(r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+", stable)):
            raise Refused("Malformed stable disk identity")
        if stable in seen:
            raise Refused("Stable disk identifier resolves to multiple devices")
        seen.add(stable)
        output[device] = stable
    return output


def mountpoints(node: dict) -> bool:
    return any(bool(mp) for mp in node.get("mountpoints") or [])


def capture(identifier: str, *, data: dict | None = None,
            ids: dict[str, str] | None = None, current_boot_id: str | None = None) -> dict:
    if not isinstance(identifier, str) or not re.fullmatch(
            r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+", identifier):
        raise Refused("Select one exact stable /dev/disk/by-id identifier")
    block = probe() if data is None else data
    aliases = validated_ids(preflight.stable_ids() if ids is None else ids)
    matches = [device for device, stable in aliases.items() if stable == identifier]
    if len(matches) != 1:
        raise Refused("Selected device identifier disappeared or is ambiguous")
    path = matches[0]
    disks = flat_disks(block)
    if path not in disks:
        raise Refused("Selected identifier no longer points at a whole disk")
    disk = disks[path]
    descendants = preflight.descendants(disk)
    blockers: list[str] = []
    for name, value in (("serial", disk.get("serial")), ("wwn", disk.get("wwn"))):
        if value is not None and not isinstance(value, str):
            blockers.append(f"Malformed {name} identity")
    if not (str(disk.get("serial") or "").strip() or str(disk.get("wwn") or "").strip()):
        blockers.append("No hardware serial or WWN: physical installer cannot prove disk identity")
    size = disk.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < MIN_BYTES:
        blockers.append("Disk must be at least 32 GiB")
    if disk.get("ro") or disk.get("rm"):
        blockers.append("Read-only or removable disk")
    if mountpoints(disk) or any(mountpoints(child) for child in descendants):
        blockers.append("Disk or a descendant has mounted filesystems")
    if descendants or disk.get("pttype") or disk.get("fstype"):
        blockers.append("Disk is not blank: existing partitions or signatures require separate erasure review")
    if any(child.get("type") in {"crypt", "lvm", "raid0", "raid1", "raid5",
                                  "raid6", "raid10", "md"} for child in descendants):
        blockers.append("Active encrypted, RAID or LVM mapping")
    if any(child.get("fstype") == "swap" for child in [disk, *descendants]):
        blockers.append("Swap is present")
    system = preflight.system_preflight()
    if not system["architecture_supported"] or not system["uefi"] or not system["sufficient_memory"]:
        blockers.append("System does not meet x86_64, UEFI and 4 GiB memory requirements")
    boot = boot_id() if current_boot_id is None else current_boot_id
    if not isinstance(boot, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", boot):
        raise Refused("Cannot identify this boot session")
    values = {name: disk.get(name) for name in FIELDS}
    values["size"] = size
    values["path"] = path
    snapshot = {
        "schema": SCHEMA,
        "boot_id": boot,
        "stable_id": identifier,
        "device": values,
        "layout": list(preflight.LAYOUT),
        "eligible": not blockers,
        "blockers": blockers,
    }
    return {"snapshot": snapshot, "sha256": fingerprint(snapshot),
            "write_operations_enabled": False}


def verify(review: dict, *, data: dict | None = None,
           ids: dict[str, str] | None = None,
           current_boot_id: str | None = None) -> dict:
    if not isinstance(review, dict) or set(review) != {
            "snapshot", "sha256", "write_operations_enabled"}:
        raise Refused("Invalid disk-review envelope")
    snap = review["snapshot"]
    if not isinstance(snap, dict) or snap.get("schema") != SCHEMA:
        raise Refused("Unsupported disk-review schema")
    if review["write_operations_enabled"] is not False:
        raise Refused("Review must remain read-only")
    if not isinstance(review["sha256"], str) or review["sha256"] != fingerprint(snap):
        raise Refused("Review fingerprint differs from its snapshot")
    if not snap.get("eligible") or snap.get("blockers"):
        raise Refused("Selected disk was blocked when the review was created")
    current = capture(snap.get("stable_id"), data=data, ids=ids,
                      current_boot_id=current_boot_id)
    if current["snapshot"] != snap:
        raise Refused("Hardware, boot session, or disk state changed; start a new review")
    if not current["snapshot"]["eligible"]:
        raise Refused("Disk no longer passes safety review")
    return {"verified": True, "write_operations_enabled": False,
            "sha256": current["sha256"], "stable_id": current["snapshot"]["stable_id"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eduardOS read-only disk identity review")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture", metavar="/dev/disk/by-id/...", help="Print a new disk review JSON")
    group.add_argument("--verify", metavar="FILE", help="Re-probe against a previous JSON review")
    args = parser.parse_args(argv)
    try:
        if args.capture:
            result = capture(args.capture)
        else:
            # Only reads the review file; never executes anything in it.
            with open(args.verify, encoding="utf-8") as handle:
                review = json.load(handle)
            result = verify(review)
        print(json.dumps(result, indent=2))
        return 0 if result.get("verified", result.get("snapshot", {}).get("eligible", False)) else 2
    except (Refused, OSError, ValueError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, json.JSONDecodeError, TypeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
