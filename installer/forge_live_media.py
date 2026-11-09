#!/usr/bin/env python3
"""Conservative, read-only NixOS live-media provenance for overlay roots.

An overlay root is only considered traceable when *every* lower layer is a
mounted squashfs loop backed by a file on a mounted ISO9660 block device,
and upper/work layers live on tmpfs. Any other layout fails closed.

This is a safety evidence reader, not an ISO authenticity check, permission
to erase media, or support for arbitrary live-boot arrangements.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Mapping

DEVNO = re.compile(r"[0-9]+:[0-9]+\Z")
LOOPNAME = re.compile(r"loop[0-9]+\Z")
OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


class Refused(ValueError):
    pass


@dataclass(frozen=True)
class Mount:
    point: str
    devno: str
    fstype: str
    source: str
    superopts: str
    # Kernel mount root: Btrfs subvolume path; "/" for ordinary mounts.
    root: str = "/"


@dataclass(frozen=True)
class LiveProvenance:
    root_devno: str
    iso_devnos: frozenset[str]
    squashfs_devnos: frozenset[str]

    def report(self) -> dict:
        return {
            "source": "overlay-squashfs-loop-iso9660",
            "iso_device_numbers": sorted(self.iso_devnos),
            "squashfs_loop_numbers": sorted(self.squashfs_devnos),
            "write_operations_enabled": False,
        }


def _unescape(text: str) -> str:
    return OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), text)


def mounts_from_mountinfo(text: str) -> list[Mount]:
    mounts = []
    for line in text.splitlines():
        left, separator, right = line.partition(" - ")
        if not separator:
            raise Refused("Mount table contains an incomplete record")
        fields, after = left.split(), right.split()
        if len(fields) < 6 or len(after) < 3 or not DEVNO.fullmatch(fields[2]):
            raise Refused("Mount table contains an invalid record")
        mounts.append(Mount(
            _unescape(fields[4]), fields[2], after[0],
            _unescape(after[1]), _unescape(after[2]),
            _unescape(fields[3]),
        ))
    if not mounts:
        raise Refused("Mount table is empty")
    return mounts


def sysfs_loop_backings(root: Path = Path("/sys/block")) -> dict[str, str]:
    """Read kernel-reported loop major:minor -> backing filename."""
    result: dict[str, str] = {}
    for device in root.glob("loop*"):
        if not LOOPNAME.fullmatch(device.name):
            continue
        try:
            devno = (device / "dev").read_text().strip()
            backing = (device / "loop/backing_file").read_text().strip()
        except OSError:
            continue
        if not DEVNO.fullmatch(devno) or not backing.startswith("/"):
            continue
        if devno in result:
            raise Refused("Loop device identity is ambiguous")
        result[devno] = backing
    return result


def _one_mount(mounts: list[Mount], point: str) -> Mount:
    matches = [m for m in mounts if m.point == point]
    if len(matches) != 1:
        raise Refused(f"Ambiguous or missing mountpoint: {point}")
    return matches[0]


def _under(path: str, parent: str) -> bool:
    return (parent == "/" and path.startswith("/")) or (
        path == parent or path.startswith(parent.rstrip("/") + "/")
    )


def _backing_mount(mounts: list[Mount], path: str) -> Mount:
    if not path.startswith("/") or ".." in path.split("/"):
        raise Refused("Backing path is not an absolute safe path")
    candidates = [m for m in mounts if _under(path, m.point)]
    if not candidates:
        raise Refused("Unable to resolve backing file's filesystem")
    depth = max(len(m.point) for m in candidates)
    matches = [m for m in candidates if len(m.point) == depth]
    if len(matches) != 1:
        raise Refused("Ambiguous mount for a backing file")
    return matches[0]


def _option(options: str, key: str) -> str:
    values = [x[len(key) + 1:] for x in options.split(",")
              if x.startswith(key + "=")]
    if len(values) != 1 or not values[0]:
        raise Refused(f"Overlay root missing or ambiguous {key}")
    return _unescape(values[0])


def verify_live_overlay(
    mounts: list[Mount],
    loop_backings: Mapping[str, str],
    known_device_numbers: set[str],
) -> LiveProvenance:
    """Inspect mount provenance with no device or filesystem writes.

    The probe does not trust labels or a mere ISO9660 mount. It verifies
    the overlay -> squashfs loop -> backing file -> ISO9660 block chain.
    """
    root = _one_mount(mounts, "/")
    if root.fstype != "overlay":
        raise Refused("Live-media provenance requires an overlay root")
    lowers = _option(root.superopts, "lowerdir").split(":")
    if not lowers or any(not item.startswith("/") for item in lowers):
        raise Refused("Unsupported overlay lowerdir configuration")
    upper = _option(root.superopts, "upperdir")
    work = _option(root.superopts, "workdir")
    if upper == work:
        raise Refused("Overlay upper and work directories must differ")
    upper_mount = _backing_mount(mounts, upper)
    work_mount = _backing_mount(mounts, work)
    if (upper_mount.fstype != "tmpfs" or work_mount.fstype != "tmpfs"
            or upper_mount.devno != work_mount.devno):
        raise Refused("Overlay writable layer is not entirely on the same tmpfs")

    iso_devnos: set[str] = set()
    squashfs_devnos: set[str] = set()
    for lower in lowers:
        squash = _backing_mount(mounts, lower)
        if squash.fstype != "squashfs" or squash.point != lower:
            raise Refused("Overlay lower layer is not an exact squashfs mount")
        if squash.devno not in loop_backings:
            raise Refused("Squashfs loop backing cannot be verified")
        backing_file = loop_backings[squash.devno]
        iso_mount = _backing_mount(mounts, backing_file)
        if iso_mount.fstype != "iso9660":
            raise Refused("Squashfs image is not backed by ISO9660 media")
        if iso_mount.devno not in known_device_numbers:
            raise Refused("ISO9660 source is not a known block device")
        if not _under(backing_file, iso_mount.point) or backing_file == iso_mount.point:
            raise Refused("Missing squashfs image path inside ISO mount")
        iso_devnos.add(iso_mount.devno)
        squashfs_devnos.add(squash.devno)

    if not iso_devnos:
        raise Refused("No traceable live ISO media found")
    return LiveProvenance(root.devno, frozenset(iso_devnos),
                          frozenset(squashfs_devnos))
