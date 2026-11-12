#!/usr/bin/env python3
"""Explicit local-console entry point for the Alpha 0.2 VM-only ISO installer.

No untrusted browser request can invoke this entry point. It may create the
fixed disposable-QEMU authorization marker ONLY after confirming that this
is a root-operated virtual machine with the exact /dev/vda/virtio-root
target. It then launches the already-tested local Forge lab GUI, prompting
for two distinct secrets on the operator's terminal.

This is NOT a general physical installer. Refuse on all non-QEMU machines.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import forge_executor_lab as executor
import forge_lab_gui as gui
import forge_lab_gui_session as lab_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="eduardOS explicit disposable-QEMU-only ISO installation"
    )
    parser.add_argument("--executor", required=True)
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0 or not sys.stdin.isatty():
            raise ValueError("Root and an interactive local console are required")
        dmi = " ".join(
            Path(f"/sys/class/dmi/id/{name}").read_text().strip()
            for name in ("sys_vendor", "product_name")
        ).lower()
        if not any(word in dmi for word in ("qemu", "kvm", "bochs")):
            raise ValueError("This installer supports disposable QEMU only")
        alias = Path(lab_session.ALIAS)
        if not alias.is_symlink() or alias.resolve(strict=True) != Path(executor.TARGET):
            raise ValueError("Expected disposable virtio-root at /dev/vda is absent")
        if executor.MARKER.exists() or executor.MARKER.is_symlink():
            raise ValueError("Disposable VM authorization marker already exists")
        # Marker creation grants no write permission by itself: the executor
        # independently checks the VM, target, mounts, one-shot attempt,
        # passphrase, and exact immutable Disko command at execution time.
        marker_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(executor.MARKER, marker_flags, 0o600)
        try:
            os.write(fd, b"EDOS-LAB-ONLY\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        if executor.check_lab_guard(require_luks=False):
            raise ValueError("VM disk preflight failed")
        print("WARNING: this will ERASE disposable QEMU /dev/vda.", flush=True)
        print("No physical disk or arbitrary target is supported.", flush=True)
        answer = input("Type ERASE DISPOSABLE /dev/vda to continue: ")
        if answer != executor.CONFIRM:
            raise ValueError("Operator confirmation was refused")
        # A local root-operated Forge service is intentionally separate
        # from the unprivileged live desktop's read-only preview.
        return gui.main([
            "--executor", args.executor,
            "--operator-confirm", answer,
            "--trusted-console-credentials",
        ])
    except (OSError, ValueError, EOFError):
        print("REFUSED: no installation was authorized by the QEMU-only launcher",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
