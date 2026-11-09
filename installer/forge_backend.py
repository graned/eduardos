#!/usr/bin/env python3
"""Forge backend trust boundary. NO formatting, mounting or installation.

This library coordinates independent pre-format disk checks and post-format
target mount attestation. It can stage an account HASH only on a previously
verified mounted encrypted target. It never provides a destructive disk API.

Until integration tests run on a disposable VM, this is NOT a production
installer or an authorization to erase any physical drive.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Iterator

import forge_authorization as auth
import forge_credentials as credentials
import forge_disk_identity as identity
import forge_live_media as live
import forge_privileged_guard as guard

TARGET_ROOT = "/mnt"  # Fixed, never chosen by the browser/CLI.
TARGET_MOUNTS = {
    "": ("btrfs", "/@root"),
    "/home": ("btrfs", "/@home"),
    "/nix": ("btrfs", "/@nix"),
    "/persist": ("btrfs", "/@persist"),
    "/.snapshots": ("btrfs", "/@snapshots"),
    "/boot": ("vfat", "/"),
}
MAX_SESSION_SECONDS = 120
BLOCK_OPEN_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW
DIR_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class Refused(ValueError):
    pass


def _devno(device: int) -> str:
    return f"{os.major(device)}:{os.minor(device)}"


def _root_required() -> None:
    if os.geteuid() != 0:
        raise Refused("Only the trusted root-side backend may validate a target")


def _assert_disk_handle(fd: int, expected_devno: str) -> None:
    meta = os.fstat(fd)
    if not stat.S_ISBLK(meta.st_mode) or _devno(meta.st_rdev) != expected_devno:
        raise Refused("Held file descriptor is not the selected block disk")


def _same_stable_disk(stable_id: str, fd: int) -> None:
    # The symlink itself must still point to the held block-device identity.
    # This catches path replacement but is NOT a lock against hotplug.
    meta = os.stat(stable_id)
    held = os.fstat(fd)
    if not stat.S_ISBLK(meta.st_mode) or meta.st_rdev != held.st_rdev:
        raise Refused("Stable device path no longer identifies the held disk")


def _mount_records(mountinfo: str, prefix: str) -> dict[str, live.Mount]:
    mounts = live.mounts_from_mountinfo(mountinfo)
    result: dict[str, live.Mount] = {}
    for row in mounts:
        if row.point == prefix or row.point.startswith(prefix + "/"):
            if row.point in result:
                raise Refused("Multiple mounts share an installation mountpoint")
            result[row.point] = row
    wanted = {prefix + suffix for suffix in TARGET_MOUNTS}
    if set(result) != wanted:
        raise Refused("Installed target mountpoints are missing or contain unexpected mounts")
    return result


def _parents_include_only_target(
    key: str, selected_devno: str, nodes: dict, parents: dict,
) -> bool:
    ancestry = guard.ancestor_devices(key, parents)
    disks = {item for item in ancestry if nodes[item].get("type") in ("disk", "rom")}
    return disks == {selected_devno}


def attest_target_mounts(
    selected_devno: str, data: dict, mountinfo: str, *,
    prefix: str = TARGET_ROOT,
) -> dict:
    """Pure check of Disko's exact installed layout and physical ancestry.

    No paths in the target are opened and no device is modified. The
    filesystem's kernel mountinfo root field is used to verify subvolumes.
    """
    if not re.fullmatch(r"[0-9]+:[0-9]+", selected_devno):
        raise Refused("Invalid selected disk device number")
    if not prefix.startswith("/") or prefix == "/" or ".." in prefix.split("/"):
        raise Refused("Invalid installation target mount root")

    nodes, parents = guard.block_graph(data)
    selected = nodes.get(selected_devno)
    if not selected or selected.get("type") != "disk":
        raise Refused("Selected device number is no longer a whole disk")

    crypt = [
        key for key, node in nodes.items()
        if node.get("type") == "crypt"
        and (node.get("name") == "edos-crypt" or
             node.get("path") == "/dev/mapper/edos-crypt")
    ]
    if len(crypt) != 1 or not _parents_include_only_target(
        crypt[0], selected_devno, nodes, parents,
    ):
        raise Refused("Expected edos-crypt is missing or not exclusively on target disk")

    by_mount = _mount_records(mountinfo, prefix)
    source_aliases = {"/dev/mapper/edos-crypt", nodes[crypt[0]].get("path")}
    for suffix, (fstype, subvolume) in TARGET_MOUNTS.items():
        row = by_mount[prefix + suffix]
        if row.fstype != fstype:
            raise Refused(f"Unexpected filesystem at {suffix or '/'}")
        # mountinfo's mount root (field 4, 0-based index 3) carries
        # the Btrfs subvolume identity even when its st_dev is virtual.
        if row.root != subvolume:
            raise Refused(f"Incorrect mounted subvolume at {suffix or '/'}")
        if fstype == "btrfs":
            if row.source not in source_aliases:
                raise Refused("Encrypted Btrfs mount source is not edos-crypt")
        else:
            boot = nodes.get(row.devno)
            if (boot is None or boot.get("type") != "part"
                    or not _parents_include_only_target(
                        row.devno, selected_devno, nodes, parents
                    )):
                raise Refused("EFI mount is not a partition on selected disk")
            if row.source not in {boot.get("path"), boot.get("name"),
                                  "/dev/" + str(boot.get("name"))}:
                raise Refused("EFI mount source does not match the selected partition")

    return {
        "status": "encrypted-target-attested",
        "target_devno": selected_devno,
        "encrypted_mapper_devno": crypt[0],
        "verified_mountpoints": sorted(by_mount),
        "write_operations_enabled": False,
    }


@dataclass
class HeldTarget:
    """Short-lived prepared disk identity, not a destructive capability."""

    fd: int
    review: dict
    username: str
    hostname: str
    devno: str
    deadline: float
    used: bool = False

    def _fresh_device(self, data: dict) -> None:
        _root_required()
        if time.monotonic() >= self.deadline:
            raise Refused("Prepared installation target expired")
        _assert_disk_handle(self.fd, self.devno)
        snap = self.review["snapshot"]
        if identity.boot_id() != snap["boot_id"]:
            raise Refused("Boot session changed after target preparation")
        _same_stable_disk(snap["stable_id"], self.fd)
        disks = identity.flat_disks(data)
        current = disks.get(snap["device"]["path"])
        if current is None:
            raise Refused("Selected whole disk disappeared")
        for field in ("size", "model", "serial", "wwn", "tran", "maj:min", "ro", "rm"):
            if current.get(field) != snap["device"].get(field):
                raise Refused("Disk hardware identity changed during installation")

    def stage_account_hash(self, password: str, *, data: dict | None = None,
                           mountinfo: str | None = None) -> dict:
        """Write only one account HASH, after proving mounted target ancestry.

        Assumes an external *separately reviewed* VM-only formatter has
        already created and mounted the encrypted target. No formatter here.
        """
        if self.used:
            raise Refused("This installation session has already been consumed")
        # Consume on first attempt, including failed validation or password.
        self.used = True
        _root_required()
        if time.monotonic() >= self.deadline:
            raise Refused("Installation session expired")
        block = identity.probe() if data is None else data
        self._fresh_device(block)

        info = (Path("/proc/self/mountinfo").read_text()
                if mountinfo is None else mountinfo)
        verdict = attest_target_mounts(self.devno, block, info)
        root_fd = os.open(TARGET_ROOT, DIR_OPEN_FLAGS)
        try:
            info_root = os.fstat(root_fd)
            if not stat.S_ISDIR(info_root.st_mode) or info_root.st_uid != 0:
                raise Refused("Installed root directory ownership is unsafe")
            mounts = {m.point: m for m in live.mounts_from_mountinfo(info)}
            if _devno(info_root.st_dev) != mounts[TARGET_ROOT].devno:
                raise Refused("Target root mount changed after attestation")
            persist_meta = os.stat("persist", dir_fd=root_fd, follow_symlinks=False)
            if (not stat.S_ISDIR(persist_meta.st_mode)
                    or _devno(persist_meta.st_dev) != mounts[TARGET_ROOT + "/persist"].devno):
                raise Refused("Encrypted persist mount changed after attestation")

            digest = credentials.hash_user_password(password)
            # The device path can be reattached while hashing takes place.
            _assert_disk_handle(self.fd, self.devno)
            _same_stable_disk(self.review["snapshot"]["stable_id"], self.fd)
            name = credentials.write_user_hash(
                root_fd, self.username, digest, expected_uid=0,
            )
        finally:
            os.close(root_fd)
        return {
            "status": "credential-staged",
            "account_hash_path": name,
            "attestation": verdict["status"],
            "destructive_disk_operations_enabled": False,
            "filesystem_write_scope": "new-account-hash-only",
            "note": "One account hash was written; no partitioning or OS installation.",
        }


@contextmanager
def prepare_target(review: dict, confirmation: str, *,
                   username: str, hostname: str) -> Iterator[HeldTarget]:
    """Trusted root-only preparation; holds a READ-ONLY block device FD.

    Requires a fresh disk review and independent current-system ancestry
    validation. No physical drive writes or authorization token output.
    """
    _root_required()
    auth.validate_user_settings(username, hostname)
    if not isinstance(review, dict) or not isinstance(review.get("snapshot"), dict):
        raise Refused("Invalid untrusted disk review")
    stable_id = review["snapshot"].get("stable_id")
    if (not isinstance(stable_id, str)
            or not isinstance(confirmation, str)
            or not secrets.compare_digest(
                confirmation, auth.confirm_text(stable_id),
            )):
        raise Refused("Exact stable-disk confirmation required")
    proof = guard.privileged_preflight(review)
    if proof.get("status") != "preflight-passed" or proof.get(
        "write_operations_enabled"
    ) is not False:
        raise Refused("Privileged disk preflight was not approved")
    if proof.get("disk_id") != stable_id:
        raise Refused("Preflight disk identity differs from the reviewed disk")

    # The by-id entry is a symlink: resolve it, open the actual device with
    # O_NOFOLLOW, then prove fstat and the alias still identify the same disk.
    realpath = os.path.realpath(stable_id)
    if not realpath.startswith("/dev/") or realpath == "/dev/":
        raise Refused("Invalid resolved block device path")
    fd = os.open(realpath, BLOCK_OPEN_FLAGS)
    try:
        _assert_disk_handle(fd, proof["target_devno"])
        _same_stable_disk(stable_id, fd)
        session = HeldTarget(
            fd, review, username, hostname, proof["target_devno"],
            time.monotonic() + MAX_SESSION_SECONDS,
        )
        yield session
    finally:
        os.close(fd)
