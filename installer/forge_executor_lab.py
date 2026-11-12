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
import io
import re
from pathlib import Path
import stat
import subprocess
import sys

import forge_authorization as authorization
import forge_credentials as credentials
import forge_secret_handoff as sealed_handoff
import forge_disk_identity as identity
import forge_installer as preflight
import forge_install_transaction as transaction
import forge_lab_command_policy as command_policy
import forge_lab_attempt as lab_attempt
import forge_lab_child as lab_child
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


def check_lab_guard(*, require_luks: bool = True) -> list[str]:
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
    # The legacy CI fixture is a root-owned 0600 tmpfs file. The trusted
    # operator path instead supplies a role-labelled sealed memfd; Disko's
    # immutable formatter expects this exact /run pathname, so it is a
    # root-owned symlink to the executor's own live /proc/self/fd/N.
    # Never follow an arbitrary symlink or accept a caller-provided key path.
    if not require_luks:
        return errors
    if KEYFILE.is_symlink():
        try:
            link = os.readlink(KEYFILE)
            if not re.fullmatch(r"/proc/[1-9][0-9]*/fd/[0-9]+", link):
                raise Refused("Invalid sealed LUKS link")
            pid, descriptor = (int(part) for part in (link.split("/")[2], link.split("/")[4]))
            if pid != os.getpid() or KEYFILE.lstat().st_uid != 0:
                raise Refused("Sealed LUKS link belongs to another process")
            sealed_handoff._assert_fd(descriptor, credentials.LUKS_MEMFD_LABEL)
        except (OSError, ValueError, Refused, sealed_handoff.Refused):
            errors.append("Sealed LUKS credential provenance failed")
    elif not KEYFILE.is_file():
        errors.append("Missing guarded QEMU LUKS input")
    else:
        metadata = KEYFILE.stat()
        if (metadata.st_uid != 0 or metadata.st_size < 16
                or metadata.st_mode & 0o077):
            errors.append("Disposable LUKS fixture must be root-owned mode 0600")
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


def audit_irreversible_boundary(fd: int, expected_devno: str) -> None:
    """Recheck live kernel mount/swap ancestry immediately before QEMU Disko.

    No report can authorize writing. The independent disposable QEMU,
    root, marker and exact-confirmation gates still apply.
    """
    _assert_held_target(fd, expected_devno)
    report = command_policy.review_kernel_boundary(
        expected_devno,
        data=identity.probe(),
        mountinfo=Path("/proc/self/mountinfo").read_text(),
        swaps=Path("/proc/swaps").read_text(),
        loop_backings=live_media.sysfs_loop_backings(),
    )
    if (report.get("status") != "lab-boundary-reviewed-read-only"
            or report.get("target_devno") != expected_devno
            or report.get("write_operations_enabled") is not False
            or report.get("authorization_to_write") is not False):
        raise Refused("Disposable disk irreversible-boundary audit refused")
    _assert_held_target(fd, expected_devno)


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


def _fd_mount_id(fd: int) -> str:
    """Kernel mount identity from fdinfo, independent of Btrfs st_dev."""
    info = Path(f"/proc/self/fdinfo/{fd}").read_text()
    values = [line.split(":", 1)[1].strip()
              for line in info.splitlines() if line.startswith("mnt_id:")]
    if len(values) != 1 or not values[0].isdecimal():
        raise Refused("Could not prove kernel mount ID of held directory")
    return values[0]


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
        persist_fd = os.open("persist", flags, dir_fd=root_fd)
        try:
            root_meta = os.fstat(root_fd)
            persist_meta = os.fstat(persist_fd)
            # Btrfs subvolumes can report a distinct anonymous st_dev for
            # each subvolume; it is not guaranteed to equal the underlying
            # mapper major:minor from mountinfo. Instead prove each opened
            # directory belongs to the exact kernel mount ID just audited.
            if (not root.mount_id or not persist.mount_id
                    or root.mount_id == persist.mount_id
                    or not stat.S_ISDIR(root_meta.st_mode)
                    or root_meta.st_uid != 0
                    or _fd_mount_id(root_fd) != root.mount_id):
                raise Refused("Installed root filesystem changed before credential staging")
            if (not stat.S_ISDIR(persist_meta.st_mode)
                    or persist_meta.st_uid != 0
                    or _fd_mount_id(persist_fd) != persist.mount_id):
                raise Refused("Encrypted persist filesystem changed before credential staging")
            digest = credentials.hash_user_password(password)
            # Revalidate after hashing and immediately before the only
            # account write. The same held /dev/vda descriptor remains open.
            verify_post_format(fd, expected_devno)
            # Reject changed mounts in the live mount namespace as well as
            # stale directory handles before allowing the hash file write.
            current = {m.point: m for m in live_media.mounts_from_mountinfo(
                Path("/proc/self/mountinfo").read_text())}
            if (current.get("/mnt") is None
                    or current.get("/mnt/persist") is None
                    or current["/mnt"].mount_id != root.mount_id
                    or current["/mnt/persist"].mount_id != persist.mount_id
                    or _fd_mount_id(root_fd) != root.mount_id
                    or _fd_mount_id(persist_fd) != persist.mount_id):
                raise Refused("Installed target mounts changed while staging credential")
            credentials.write_user_hash(root_fd, LAB_USERNAME, digest, expected_uid=0)
        finally:
            os.close(persist_fd)
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
    # A previous invocation may already have partially formatted /dev/vda.
    # Block same-boot reruns even with a fresh consent string and PID.
    lab_attempt.require_new_attempt()
    # Independently verify the two fixed existing commands. This review
    # is non-executable and grants no disk-write authority.
    reviewed = command_policy.review_commands(disko_script, system_closure)
    if (reviewed.disk != TARGET
            or reviewed.write_operations_enabled is not False
            or reviewed.authorization_to_write is not False
            or reviewed.format_step.executable is not False
            or reviewed.install_step.executable is not False
            or reviewed.format_step.arguments !=
            (disko_script, "--yes-wipe-all-disks")
            or reviewed.install_step.arguments !=
            ("nixos-install", "--root", "/mnt", "--system",
             system_closure, "--no-root-passwd")):
        raise Refused("Disposable command allowlist contract refused")

    with hold_lab_disk() as (fd, devno):
        def preformat_gate() -> None:
            # This is a SECOND safety check inside the held descriptor's
            # lifetime, immediately before the irreversible formatter call.
            if check_lab_guard():
                raise Refused("Disposable VM safety changed before formatting")
            _assert_held_target(fd, devno)

        def format_disposable() -> None:
            # This runs AFTER the transaction has entered format-started.
            # Re-probe mounts, swaps, boot ancestry and held devno
            # immediately before the irreversible Disko command.
            audit_irreversible_boundary(fd, devno)
            # Record terminal attempt state before irreversible disk writes.
            # The root-owned /run marker survives subprocess failure and
            # refuses a second invocation during this QEMU installer boot.
            lab_attempt.mark_format_started()
            lab_child.run_child([disko_script, "--yes-wipe-all-disks"])

        def install_disposable() -> None:
            lab_child.run_child([
                "nixos-install", "--root", "/mnt", "--system",
                system_closure, "--no-root-passwd",
            ])

        # Fail closed and never retry/rollback a partially formatted disk.
        # Progress events carry fixed phase names, no secrets or paths.
        tx = transaction.InstallationTransaction(
            preflight=preformat_gate,
            format_disk=format_disposable,
            audit_mounted_target=lambda: verify_post_format(fd, devno),
            stage_credential_hash=lambda: stage_lab_account(
                fd, devno, account_password,
            ),
            install_system=install_disposable,
            emit=lambda phase: print(f"FORGE_QEMU_PHASE={phase}", flush=True),
        )
        tx.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eduardOS destructive disposable-VM installation test ONLY")
    parser.add_argument("--execute", action="store_true", help="Enable test VM disk write path")
    parser.add_argument("--confirm", default="", help="Exact disposable disk confirmation phrase")
    parser.add_argument(
        "--user-password-stdin", action="store_true",
        help="Required in QEMU execute mode; public test fixture is read on stdin",
    )
    parser.add_argument("--sealed-luks-fd", type=int, default=None,
                        help="Trusted QEMU operator: inherited sealed LUKS memfd")
    parser.add_argument("--sealed-account-fd", type=int, default=None,
                        help="Trusted QEMU operator: inherited sealed account memfd")
    parser.add_argument("--disko-script", required=True)
    parser.add_argument("--system-closure", required=True)
    args = parser.parse_args(argv)
    if not args.execute:
        print("DRY RUN: no disk modifications. This runner is restricted to disposable QEMU guests.")
        return 0
    if args.confirm != CONFIRM:
        print("REFUSED: explicit disposable disk confirmation required.", file=sys.stderr)
        return 2
    sealed_mode = args.sealed_luks_fd is not None or args.sealed_account_fd is not None
    if sealed_mode:
        if (args.user_password_stdin or args.sealed_luks_fd is None
                or args.sealed_account_fd is None):
            print("REFUSED: expected exactly two sealed credential descriptors.", file=sys.stderr)
            return 2
    elif not args.user_password_stdin:
        print("REFUSED: QEMU fixture password input required.", file=sys.stderr)
        return 2
    failures = check_lab_guard(require_luks=not sealed_mode)
    if failures:
        for failure in failures:
            print(f"REFUSED: {failure}", file=sys.stderr)
        return 2
    try:
        if sealed_mode:
            # Descriptor numbers are NOT authorization. QEMU, target identity,
            # independent root consent and format-attempt gates still apply.
            if os.geteuid() != 0 or not MARKER.is_file():
                raise Refused("Sealed credentials require root disposable QEMU")
            handles = sealed_handoff.CredentialFDs(
                args.sealed_luks_fd, args.sealed_account_fd)
            with sealed_handoff.OneShotCredentialReader(handles).consume() as material:
                # The immutable Disko script reads the fixed /run path.
                # Point it only to this live process's sealed memfd, never a
                # plaintext secret file. Refuse to overwrite a fixture/link.
                if KEYFILE.exists() or KEYFILE.is_symlink():
                    raise Refused("Sealed LUKS path is already occupied")
                os.symlink(f"/proc/{os.getpid()}/fd/{args.sealed_luks_fd}", KEYFILE)
                try:
                    install(args.disko_script, args.system_closure,
                            password_stream=io.BytesIO(material.account))
                finally:
                    KEYFILE.unlink(missing_ok=True)
        else:
            install(args.disko_script, args.system_closure,
                    password_stream=sys.stdin.buffer)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            Refused, mount_audit.Refused, topology_guard.Refused,
            OSError, ValueError, TypeError, KeyError,
            credentials.Refused, authorization.Refused,
            command_policy.Refused, lab_attempt.Refused,
            lab_child.Cancelled, sealed_handoff.Refused) as exc:
        print(f"Installation aborted: {exc}", file=sys.stderr)
        return 3
    print("Disposable VM installation complete; no physical device was supported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
