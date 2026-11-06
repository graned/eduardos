#!/usr/bin/env python3
"""VM-LAB-ONLY destructive installation runner.

This is NOT a physical-hardware installer. Target is hard-locked to
/dev/vda in a disposable QEMU test guest, with multiple independent gates.
The browser UI is deliberately not connected to this executable.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

import forge_installer as preflight

MARKER = Path("/run/eduardos-disposable-install-lab")
KEYFILE = Path("/run/edos-test-passphrase")
TARGET = "/dev/vda"
CONFIRM = "ERASE DISPOSABLE /dev/vda"


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


def install(disko_script: str, system_closure: str) -> None:
    # The paths are passed by the Nix test harness from its evaluated
    # store outputs. Never parse strings as shell commands.
    if not disko_script.startswith("/nix/store/") or not Path(disko_script).is_file():
        raise Refused("Invalid immutable Disko script")
    if not system_closure.startswith("/nix/store/") or not Path(system_closure).is_dir():
        raise Refused("Invalid immutable NixOS system closure")
    subprocess.run([disko_script, "--yes-wipe-all-disks"], check=True)
    subprocess.run(["nixos-install", "--root", "/mnt", "--system", system_closure,
                    "--no-root-passwd"], check=True, stdin=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eduardOS destructive disposable-VM installation test ONLY")
    parser.add_argument("--execute", action="store_true", help="Enable test VM disk write path")
    parser.add_argument("--confirm", default="", help="Exact disposable disk confirmation phrase")
    parser.add_argument("--disko-script", required=True)
    parser.add_argument("--system-closure", required=True)
    args = parser.parse_args(argv)
    if not args.execute:
        print("DRY RUN: no disk modifications. This runner is restricted to disposable QEMU guests.")
        return 0
    if args.confirm != CONFIRM:
        print("REFUSED: explicit disposable disk confirmation required.", file=sys.stderr)
        return 2
    failures = check_lab_guard()
    if failures:
        for failure in failures:
            print(f"REFUSED: {failure}", file=sys.stderr)
        return 2
    try:
        install(args.disko_script, args.system_closure)
    except (subprocess.CalledProcessError, Refused) as exc:
        print(f"Installation aborted: {exc}", file=sys.stderr)
        return 3
    print("Disposable VM installation complete; no physical device was supported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
