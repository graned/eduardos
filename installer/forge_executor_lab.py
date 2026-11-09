#!/usr/bin/env python3
"""VM-LAB-ONLY destructive installation runner.

This is NOT a physical-hardware installer. Target is hard-locked to
/dev/vda in a disposable QEMU test guest, with multiple independent gates.
The browser UI is deliberately not connected to this executable.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import subprocess
import sys

import forge_authorization as authorization
import forge_credentials as credentials
import forge_disk_identity as identity
import forge_installer as preflight
import forge_live_media as live_media
import forge_mount_audit as mount_audit
import forge_privileged_guard as topology_guard

MARKER = Path("/run/eduardos-disposable-install-lab")
KEYFILE = Path("/run/edos-test-passphrase")
TARGET = "/dev/vda"
CONFIRM = "ERASE DISPOSABLE /dev/vda"
# QEMU-only fixture login; must match installedUserLabSystem in flake.nix.
LAB_USERNAME = "testpilot"


class Refused(RuntimeError):
    pass


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=30).stdout.strip()


def check_lab_guard() -> list[str]:
    errors = []
    if os.geteuid() != 0:
        errors.append("Must run as root inside a disposable VM")
    if not MARKER.is_file() or MARKER.read_text().strip() != "EDOS-LAB-ONLY":
        errors.append("Missing disposable-VM-only marker")
    try:
        dmi = " ".join(
            Path(f"/sys/class/dmi/id/{name}").read_text().strip()
            for name in ("sys_vendor", "product_name")
        ).lower()
    except OSError:
        dmi = ""
    if not any(value in dmi for value in ("qemu", "kvm", "bochs")):
        errors.append("Hardware does not identify as QEMU/KVM")
    if not Path(TARGET).exists():
        errors.append("Disposable /dev/vda target missing")
        return errors
    try:
        if run("lsblk", "-dnro", "TYPE", TARGET) != "disk":
            errors.append("Target is not a whole block disk")
        data = preflight.run_lsblk()
        node = next((n for n in preflight.all_nodes(data.get("blockdevices") or [])
                     if n.get("path") == TARGET), None)
        if node is None or node.get("type") != "disk":
            errors.append("Target missing from disk inventory")
        else:
            related = [node, *preflight.descendants(node)]
            if node.get("ro") or node.get("rm"):
                errors.append("Target is read-only or removable")
            if any(any(m for m in (n.get("mountpoints") or [])) for n in related):
                errors.append("Target or a descendant is mounted")
            if any(n.get("type") in ("crypt", "lvm", "raid0", "raid1", "raid5",
                                      "raid6", "raid10", "md") for n in related[1:]):
                errors.append("Target has active mapped storage")
            if any(n.get("fstype") == "swap" for n in related):
                errors.append("Target has swap")
            if int(node.get("size") or 0) < 8 * 1024**3:
                errors.append("Test disk is smaller than 8 GiB")
        # Fail closed if the currently booted root belongs to the target disk.
        root_source = run("findmnt", "-n", "-o", "SOURCE", "/")
        if root_source.startswith(TARGET):
            errors.append("Target appears to contain the running root filesystem")
    except (OSError, ValueError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        errors.append(f"Disk guard could not complete: {type(exc).__name__}")
    if not KEYFILE.is_file() or KEYFILE.is_symlink():
        errors.append("Missing regular test-only LUKS key file")
    else:
        stat = KEYFILE.stat()
        if stat.st_size < 16 or stat.st_mode & 0o077:
            errors.append("Disposable LUKS key must be nonempty and mode 0600")
    return errors


# The block device is held open for the entire formatter/installer sequence
# so kernel major:minor and path alias can be independently rechecked.
_BLOCK_READ_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


def _assert_held_target(fd: int, expected_devno: str) -> None:
    metadata = os.fstat(fd)
    if not stat.S_ISBLK(metadata.st_mode):
        raise Refused("The held disposable target is not a block device")
    actual = f"{os.major(metadata.st_rdev)}:{os.minor(metadata.st_rdev)}"
    if actual != expected_devno:
        raise Refused("Disposable target block identity changed")
    path_meta = os.stat(TARGET)
    if not stat.S_ISBLK(path_meta.st_mode) or path_meta.st_rdev != metadata.st_rdev:
        raise Refused("Disposable target path was replaced")


@contextmanager
def hold_lab_disk():
    """Independent pre-Disko root/boot/swap ancestry protection.

    No /dev/disk/by-id support is added: this remains permanently tied to
    QEMU /dev/vda and is *not* a physical-disk installer.
    """
    data = identity.probe()
    verdict = topology_guard.guard_topology(
        TARGET, data,
        Path("/proc/self/mountinfo").read_text(),
        Path("/proc/swaps").read_text(),
        loop_backings=live_media.sysfs_loop_backings(),
    )
    if verdict.get("write_operations_enabled") is not False:
        raise Refused("Kernel disk ancestry validation did not remain read-only")
    expected = verdict["target_devno"]
    fd = os.open(TARGET, _BLOCK_READ_FLAGS)
    try:
        _assert_held_target(fd, expected)
        yield fd, expected
    finally:
        os.close(fd)


_EXPECTED_MOUNTS = sorted([
    "/mnt", "/mnt/boot", "/mnt/home", "/mnt/nix",
    "/mnt/persist", "/mnt/.snapshots",
])


def verify_post_format(fd: int, expected_devno: str) -> None:
    """Refuse to invoke nixos-install if Disko mounted the wrong destination."""
    _assert_held_target(fd, expected_devno)
    report = mount_audit.audit(TARGET)
    if (report.get("status") != "verified-already-mounted-encrypted-target"
            or report.get("target_devno") != expected_devno
            or report.get("mountpoints") != _EXPECTED_MOUNTS
            or report.get("destructive_disk_operations_enabled") is not False
            or report.get("credential_writes_enabled") is not False):
        raise Refused("Disposable target mounted-fileystem audit failed")
    _assert_held_target(fd, expected_devno)


def read_fixture_password(stream) -> str:
    """Read one test-only account secret from stdin, not argv/env/store.

    The caller supplies a public QEMU fixture through a private /run file.
    A normal login password must never be embedded in any Nix evaluation.
    """
    if stream is None or not hasattr(stream, "read"):
        raise Refused("Disposable test-user password must be supplied on stdin")
    data = stream.read(credentials.MAX_SECRET_BYTES + 1)
    if not isinstance(data, bytes) or not data or len(data) > credentials.MAX_SECRET_BYTES:
        raise Refused("Missing or oversized disposable account password")
    try:
        password = data.decode("utf-8")
    except UnicodeError:
        raise Refused("Disposable account password has invalid encoding") from None
    try:
        authorization.validate_secret_pair(
            password, password, kind="Disposable account password",
        )
    except authorization.Refused:
        raise Refused("Disposable account password validation refused") from None
    return password


def stage_lab_account(fd: int, expected_devno: str, password: str) -> None:
    """Write one account HASH only into the already-attested QEMU target."""
    verify_post_format(fd, expected_devno)
    info = Path("/proc/self/mountinfo").read_text()
    mounted = {m.point: m for m in live_media.mounts_from_mountinfo(info)}
    root = mounted.get("/mnt")
    persist = mounted.get("/mnt/persist")
    if root is None or persist is None:
        raise Refused("Installed root or encrypted persist mount disappeared")

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open("/mnt", flags)
    try:
        root_meta = os.fstat(root_fd)
        persist_meta = os.stat("persist", dir_fd=root_fd, follow_symlinks=False)
        if (not stat.S_ISDIR(root_meta.st_mode) or root_meta.st_uid != 0
                or f"{os.major(root_meta.st_dev)}:{os.minor(root_meta.st_dev)}" != root.devno):
            raise Refused("Installed root filesystem changed before credential staging")
        if (not stat.S_ISDIR(persist_meta.st_mode) or persist_meta.st_uid != 0
                or f"{os.major(persist_meta.st_dev)}:{os.minor(persist_meta.st_dev)}" != persist.devno):
            raise Refused("Encrypted persist filesystem changed before credential staging")
        digest = credentials.hash_user_password(password)
        # Revalidate after hashing and immediately before the only
        # account write. The same held /dev/vda descriptor remains open.
        verify_post_format(fd, expected_devno)
        credentials.write_user_hash(root_fd, LAB_USERNAME, digest, expected_uid=0)
    finally:
        os.close(root_fd)


def install(disko_script: str, system_closure: str, *, password_stream) -> None:
    # The paths are passed by the Nix test harness from its evaluated
    # store outputs. Never parse strings as shell commands.
    if not disko_script.startswith("/nix/store/") or not Path(disko_script).is_file():
        raise Refused("Invalid immutable Disko script")
    if not system_closure.startswith("/nix/store/") or not Path(system_closure).is_dir():
        raise Refused("Invalid immutable NixOS system closure")
    # Never allow direct callers to bypass the QEMU/marker/root guard:
    # main() checks too, but this is the actual destructive trust boundary.
    failures = check_lab_guard()
    if failures:
        raise Refused("Disposable VM safety checks refused the installation")
    # Reject missing/invalid user credentials BEFORE Disko can erase the
    # disposable disk. No password or hash appears in argv, env or logs.
    account_password = read_fixture_password(password_stream)

    with hold_lab_disk() as (fd, devno):
        # The only destructive operation remains the existing, VM-only
        # Disko script. We do NOT add an installer for physical disks.
        subprocess.run([disko_script, "--yes-wipe-all-disks"], check=True)
        # PR #30: prove all six real mounted filesystem sources before
        # proceeding to copy/activate the system closure.
        verify_post_format(fd, devno)
        stage_lab_account(fd, devno, account_password)
        subprocess.run(["nixos-install", "--root", "/mnt", "--system", system_closure,
                        "--no-root-passwd"], check=True, stdin=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eduardOS destructive disposable-VM installation test ONLY")
    parser.add_argument("--execute", action="store_true", help="Enable test VM disk write path")
    parser.add_argument("--confirm", default="", help="Exact disposable disk confirmation phrase")
    parser.add_argument(
        "--user-password-stdin", action="store_true",
        help="Required in QEMU execute mode; public test fixture is read on stdin",
    )
    parser.add_argument("--disko-script", required=True)
    parser.add_argument("--system-closure", required=True)
    args = parser.parse_args(argv)
    if not args.execute:
        print("DRY RUN: no disk modifications. This runner is restricted to disposable QEMU guests.")
        return 0
    if args.confirm != CONFIRM:
        print("REFUSED: explicit disposable disk confirmation required.", file=sys.stderr)
        return 2
    if not args.user_password_stdin:
        print("REFUSED: QEMU fixture account password must be supplied on stdin.", file=sys.stderr)
        return 2
    failures = check_lab_guard()
    if failures:
        for failure in failures:
            print(f"REFUSED: {failure}", file=sys.stderr)
        return 2
    try:
        install(args.disko_script, args.system_closure,
                password_stream=sys.stdin.buffer)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            Refused, mount_audit.Refused, topology_guard.Refused,
            OSError, ValueError, TypeError, KeyError,
            credentials.Refused, authorization.Refused) as exc:
        print(f"Installation aborted: {exc}", file=sys.stderr)
        return 3
    print("Disposable VM installation complete; no physical device was supported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
