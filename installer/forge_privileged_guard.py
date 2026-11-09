#!/usr/bin/env python3
"""Root-only, READ-ONLY pre-execution guard for the Forge Installer.

Not a disk writer, not an erasure authorization and not connected to GUI or
QEMU's lab executor. Unknown mount topology fails closed on purpose.

A future destructive helper must hold an independently verified device
handle and repeat all protections immediately before writing.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping

import forge_live_media as live_media
import forge_disk_identity as identity
import forge_installer as inventory

MAX_REVIEW_SIZE = 128 * 1024
CRITICAL_MOUNTS = frozenset(("/", "/boot", "/nix", "/home", "/persist"))


class Refused(ValueError):
    pass


def block_graph(data: dict) -> tuple[dict[str, dict], dict[str, set[str]]]:
    """Index lsblk identities and all their parents, including md multi-parent."""
    nodes: dict[str, dict] = {}
    parents: dict[str, set[str]] = {}

    def visit(node: dict, parent: str | None, ancestry: frozenset[str]) -> None:
        key = node.get("maj:min")
        if not isinstance(key, str) or not re.fullmatch(r"\d+:\d+", key):
            raise Refused("Block device without a valid major:minor identity")
        if key in ancestry:
            raise Refused("Block-device topology contains a cycle")
        previous = nodes.get(key)
        if previous is not None and previous.get("path") != node.get("path"):
            raise Refused("Conflicting paths for the same block device")
        nodes[key] = node
        parents.setdefault(key, set())
        if parent is not None:
            parents[key].add(parent)
        for child in node.get("children") or []:
            visit(child, key, ancestry | {key})

    roots = data.get("blockdevices")
    if not isinstance(roots, list) or not roots:
        raise Refused("Cannot inspect block-device topology")
    for root in roots:
        visit(root, None, frozenset())
    return nodes, parents


def ancestor_devices(key: str, parents: dict[str, set[str]]) -> set[str]:
    """All devices supporting key, not just its immediate partition."""
    visited: set[str] = set()
    pending = [key]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        if current not in parents:
            raise Refused("Incomplete block-device parent graph")
        visited.add(current)
        pending.extend(parents[current])
    return visited


def parse_mountinfo(text: str) -> list[tuple[str, str]]:
    """(mountpoint, dev major:minor) from Linux /proc/self/mountinfo."""
    output = []
    for line in text.splitlines():
        bits = line.split(" ")
        if len(bits) < 10 or "-" not in bits:
            raise Refused("Incomplete kernel mount information")
        dev, path = bits[2], bits[4]
        if not re.fullmatch(r"\d+:\d+", dev):
            raise Refused("Invalid mounted device identifier")
        output.append((path, dev))
    if not any(point == "/" for point, _ in output):
        raise Refused("Root filesystem is absent from mount table")
    return output


def parse_swap_devices(text: str) -> list[str]:
    rows = text.splitlines()
    if not rows:
        raise Refused("Cannot inspect swap state")
    if not rows[0].startswith("Filename"):
        raise Refused("Invalid swap table")
    output = []
    for row in rows[1:]:
        parts = row.split()
        if len(parts) < 5:
            raise Refused("Cannot inspect active swap entry")
        output.append(parts[0])
    return output


def guard_topology(selected_path: str, data: dict, mountinfo: str,
                   swaps: str, *, loop_backings: Mapping[str, str] | None = None) -> dict:
    """Fail closed if target can back any active mounted or swap device.

    Overlay root is allowed only when every lowerdir can be traced through
    squashfs loop devices into physical ISO9660 media; ambiguous sources
    fail closed. This is evidence, not erasure authorization.
    """
    nodes, parents = block_graph(data)
    selected = [name for name, node in nodes.items()
                if node.get("path") == selected_path and node.get("type") == "disk"]
    if len(selected) != 1:
        raise Refused("Selected path no longer points at one whole block disk")
    target = selected[0]
    protected: set[str] = set()
    kernel_mounts = parse_mountinfo(mountinfo)
    live_provenance = None
    for path, dev in kernel_mounts:
        if dev not in nodes:
            if path == "/" and loop_backings is not None:
                try:
                    proof = live_media.verify_live_overlay(
                        live_media.mounts_from_mountinfo(mountinfo),
                        loop_backings, set(nodes),
                    )
                except live_media.Refused as exc:
                    raise Refused(f"Live root provenance is unverified: {exc}") from exc
                if proof.root_devno != dev:
                    raise Refused("Overlay root identity changed during inspection")
                for source in proof.iso_devnos:
                    ancestors = ancestor_devices(source, parents)
                    if not any(nodes[key].get("type") in {"disk", "rom"}
                               for key in ancestors):
                        raise Refused("Live ISO source has no traceable physical or optical media")
                    protected.update(ancestors)
                live_provenance = proof.report()
                continue
            if path in CRITICAL_MOUNTS:
                raise Refused(f"Cannot trace critical mount {path} to physical media")
            continue
        protected.update(ancestor_devices(dev, parents))

    # Mounts reported by lsblk may not appear in the current mount namespace.
    for name, node in nodes.items():
        if any(bool(mp) for mp in node.get("mountpoints") or []):
            protected.update(ancestor_devices(name, parents))

    # All active swap block devices, even if not mounted, are protected.
    device_by_path = {node.get("path"): key for key, node in nodes.items()}
    for source in parse_swap_devices(swaps):
        resolved = os.path.realpath(source) if source.startswith("/dev/") else source
        swap_key = device_by_path.get(resolved) or device_by_path.get(source)
        if swap_key is None:
            # Files backed by a filesystem or unknown mappings need extra
            # filesystem/loop resolution; block rather than guess.
            raise Refused("Active swap source cannot be traced to a block device")
        protected.update(ancestor_devices(swap_key, parents))
    if target in protected:
        raise Refused("Selected disk is backing a mounted filesystem or active swap")

    return {"target_path": selected_path, "target_devno": target,
            "protected_devices": sorted(protected),
            "live_media": live_provenance,
            "write_operations_enabled": False}


def load_review(path: str) -> dict[str, Any]:
    # Root helper must not follow a user-controlled symlink; cap payload.
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REVIEW_SIZE:
            raise Refused("Review must be a small regular file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            content = stream.read(MAX_REVIEW_SIZE + 1)
        if len(content) > MAX_REVIEW_SIZE:
            raise Refused("Disk review exceeds safe size limit")
    finally:
        os.close(fd)
    review = json.loads(content)
    if not isinstance(review, dict):
        raise Refused("Disk review must be an object")
    return review


def privileged_preflight(review: dict, *, euid: int | None = None,
                         lsblk_data: dict | None = None,
                         mountinfo: str | None = None,
                         swaps: str | None = None) -> dict:
    """Fresh identity+mount checks, no writable handle and no execution."""
    if (os.geteuid() if euid is None else euid) != 0:
        raise Refused("Root privileges are required to run installer preflight")
    # Independently verify user-originated review. A hash isn't a signature.
    identity.verify(review)
    selected_path = review["snapshot"]["device"]["path"]
    # Re-evaluate hardware identity against the same freshly captured lsblk
    # state that will be used for the mount ancestry check.
    block = identity.probe() if lsblk_data is None else lsblk_data
    identity.verify(review, data=block)
    mounts = (Path("/proc/self/mountinfo").read_text()
              if mountinfo is None else mountinfo)
    swapinfo = Path("/proc/swaps").read_text() if swaps is None else swaps
    verdict = guard_topology(
        selected_path, block, mounts, swapinfo,
        loop_backings=live_media.sysfs_loop_backings(),
    )
    return {
        "status": "preflight-passed",
        "disk_id": review["snapshot"]["stable_id"],
        "disk_review_sha256": review["sha256"],
        "target_devno": verdict["target_devno"],
        "protected_device_count": len(verdict["protected_devices"]),
        "live_media": verdict["live_media"],
        "write_operations_enabled": False,
        "note": "No disk write was authorized or performed.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eduardOS root-only, read-only disk safety gate")
    parser.add_argument("--review", required=True, help="Read-only disk review JSON")
    args = parser.parse_args(argv)
    try:
        verdict = privileged_preflight(load_review(args.review))
        print(json.dumps(verdict, indent=2))
        return 0
    except (Refused, identity.Refused, OSError, ValueError, TypeError,
            KeyError, json.JSONDecodeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
