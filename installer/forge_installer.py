#!/usr/bin/env python3
"""eduardOS Forge Installer: read-only discovery and installation preview.

PR #20 intentionally has NO execution path that writes to a block device.
All probe commands are read-only. The install executor belongs to a later PR.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

MIN_DISK_BYTES = 32 * 1024**3
MIN_MEMORY_BYTES = 4 * 1024**3
LAYOUT = ("1 GiB EFI System Partition (FAT32)", "Remaining space: LUKS2 encrypted Btrfs",
          "Btrfs subvolumes: @root, @home, @nix, @persist, @snapshots")
BY_ID = Path("/dev/disk/by-id")


@dataclass(frozen=True)
class Disk:
    path: str
    model: str
    size: int
    transport: str
    by_id: str | None
    eligible: bool
    reasons: tuple[str, ...]


def run_lsblk() -> dict:
    result = subprocess.run(
        ["lsblk", "--json", "--bytes", "--output",
         "NAME,PATH,TYPE,SIZE,MODEL,TRAN,RO,RM,MOUNTPOINTS,FSTYPE,PKNAME"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return json.loads(result.stdout)


def stable_ids() -> dict[str, str]:
    """Discover stable symlinks without following symlinks outside /dev."""
    mapping: dict[str, str] = {}
    if not BY_ID.is_dir():
        return mapping
    try:
        entries = sorted(BY_ID.iterdir())
    except OSError:
        return mapping
    for entry in entries:
        if "-part" in entry.name or entry.name.startswith(("dm-", "lvm-", "md-")):
            continue
        try:
            if not entry.is_symlink():
                continue
            target = entry.resolve(strict=True)
            if target.parent != Path("/dev"):
                continue
            mapping.setdefault(str(target), str(entry))
        except (OSError, RuntimeError):
            continue
    return mapping


def descendants(node: dict) -> list[dict]:
    children = []
    for child in node.get("children") or []:
        children.append(child)
        children.extend(descendants(child))
    return children


def all_nodes(nodes: list[dict]) -> list[dict]:
    output: list[dict] = []
    for node in nodes:
        output.append(node)
        output.extend(descendants(node))
    return output


def disk_inventory(data: dict, ids: dict[str, str]) -> list[Disk]:
    disks = []
    for node in all_nodes(data.get("blockdevices") or []):
        if node.get("type") != "disk":
            continue
        path = str(node.get("path") or "")
        size = int(node.get("size") or 0)
        related = [node, *descendants(node)]
        reasons = []
        if not re.fullmatch(r"/dev/[a-zA-Z0-9._/-]+", path):
            reasons.append("Missing or invalid disk device path")
        if bool(node.get("ro")):
            reasons.append("Read-only device")
        if bool(node.get("rm")):
            reasons.append("Removable device; excluded by default")
        if size < MIN_DISK_BYTES:
            reasons.append("Smaller than the 32 GiB minimum")
        if any(n.get("mountpoints") and any(m for m in n["mountpoints"]) for n in related):
            reasons.append("Disk or a descendant has a mounted filesystem")
        if any(n.get("type") in {"crypt", "lvm", "raid0", "raid1", "raid5", "raid6", "raid10", "md"} for n in related[1:]):
            reasons.append("Disk contains active encrypted, LVM or RAID mappings")
        if any(n.get("fstype") == "swap" for n in related):
            reasons.append("Disk or a descendant contains swap; excluded")
        stable = ids.get(path)
        if stable is None:
            reasons.append("No stable /dev/disk/by-id identifier")
        disks.append(Disk(path, str(node.get("model") or "Unknown model").strip(),
                          size, str(node.get("tran") or "unknown"),
                          stable, not reasons, tuple(reasons)))
    return sorted(disks, key=lambda d: d.path)


def system_preflight() -> dict:
    uefi = Path("/sys/firmware/efi").is_dir()
    mem = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError, IndexError):
        pass
    return {
        "architecture": os.uname().machine,
        "uefi": uefi,
        "memory_bytes": mem,
        "sufficient_memory": mem >= MIN_MEMORY_BYTES,
        "architecture_supported": os.uname().machine == "x86_64",
    }


def preview(disk: Disk | None, system: dict) -> dict:
    blockers = []
    if not system["architecture_supported"]:
        blockers.append("Installer target must be x86_64 Linux")
    if not system["uefi"]:
        blockers.append("UEFI boot is required")
    if not system["sufficient_memory"]:
        blockers.append("At least 4 GiB RAM required")
    if disk is None:
        blockers.append("No target disk selected")
    elif not disk.eligible:
        blockers.extend(disk.reasons)
    return {
        "mode": "dry-run-only",
        "would_write_to_disk": False,
        "status": "ready-for-review" if not blockers else "blocked",
        "selected_disk": asdict(disk) if disk else None,
        "planned_layout": list(LAYOUT),
        "blockers": blockers,
        "note": "No partitioning, formatting, mounting or installation is implemented.",
    }


def format_bytes(n: int) -> str:
    return f"{n / 1024**3:.1f} GiB"


def interactive(disks: list[Disk], system: dict) -> int:
    print("\n\033[1;36m╔══════════════════════════════════════╗")
    print("║  eduardOS · FORGE INSTALLER · ALPHA  ║")
    print("╚══════════════════════════════════════╝\033[0m")
    print("PREVIEW ONLY — NO DISK WRITES\n")
    print(f"Architecture: {system['architecture']} | UEFI: {'yes' if system['uefi'] else 'no'}"
          f" | RAM: {format_bytes(system['memory_bytes'])}\n")
    if not disks:
        print("No block disks detected. Nothing to preview.")
        return 2
    for index, disk in enumerate(disks, 1):
        state = "candidate" if disk.eligible else "BLOCKED"
        print(f" {index}. {disk.path}  {disk.model}  {format_bytes(disk.size)}  [{state}]")
        print(f"    {disk.by_id or '(no stable ID)'}")
        for reason in disk.reasons:
            print(f"    ! {reason}")
    try:
        selected = input("\nDisk number to preview (Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 0
    if not selected:
        print("Cancelled.")
        return 0
    if not selected.isascii() or not selected.isdecimal():
        print("Invalid selection.", file=sys.stderr)
        return 2
    number = int(selected)
    if number < 1 or number > len(disks):
        print("Invalid selection.", file=sys.stderr)
        return 2
    plan = preview(disks[number - 1], system)
    print("\n╔══ INSTALLATION PLAN (READ-ONLY) ══╗")
    print(f"Target: {plan['selected_disk']['by_id'] or plan['selected_disk']['path']}")
    for item in plan["planned_layout"]:
        print(f" • {item}")
    print(f"Status: {plan['status']}")
    for reason in plan["blockers"]:
        print(f" BLOCKED: {reason}")
    print("NO CHANGES WERE MADE. Future installer PR will require explicit confirmation.")
    return 0 if not plan["blockers"] else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eduardOS installer hardware preflight (read only)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="Output inventory and preflight JSON")
    group.add_argument("--disk", metavar="/dev/disk/by-id/...", help="Preview a specific stable disk identifier")
    args = parser.parse_args(argv)
    try:
        system = system_preflight()
        disks = disk_inventory(run_lsblk(), stable_ids())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Hardware discovery failed: {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps({"system": system, "disks": [asdict(d) for d in disks],
                          "write_operations_enabled": False}, indent=2))
        return 0
    if args.disk:
        # Only stable, discovered identifiers can be selected. Do not trust
        # arbitrary paths, including a manually supplied /dev/sda.
        disk = next((d for d in disks if d.by_id == args.disk), None)
        if disk is None:
            print("Disk not found by stable identifier in discovery results.", file=sys.stderr)
            return 2
        plan = preview(disk, system)
        print(json.dumps(plan, indent=2))
        return 0 if not plan["blockers"] else 2
    return interactive(disks, system)


if __name__ == "__main__":
    sys.exit(main())
