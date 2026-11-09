#!/usr/bin/env python3
"""QEMU-only same-boot format-attempt marker; NEVER a physical writer.

A failure after Disko starts may leave /dev/vda partially formatted.
Do not silently retry in another process in the same installer boot.
This is a best-effort *lab safety interlock*, not a durable journal:
the marker is in /run and disappears on reboot. It never grants writes.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat

MARKER = Path("/run/eduardos-qemu-format-attempted")
MARKER_CONTENT = b"EDOS-QEMU-FORMAT-STARTED-V1\n"
FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class Refused(RuntimeError):
    pass


def require_new_attempt() -> None:
    """Refuse a prior/ambiguous marker; do not trust marker contents."""
    if os.geteuid() != 0:
        raise Refused("QEMU attempt marker requires root")
    try:
        os.lstat(MARKER)
    except FileNotFoundError:
        return
    raise Refused("Disposable disk attempt already started; manual review required")


def mark_format_started() -> None:
    """Record first irreversible attempt BEFORE calling Disko.

    O_EXCL rejects a second process and symlink/path substitution.
    The root-controlled /run directory is part of the trusted QEMU VM.
    On error do not remove the marker: the target state is uncertain.
    """
    require_new_attempt()
    try:
        fd = os.open(MARKER, FLAGS, 0o600)
    except FileExistsError as exc:
        raise Refused("Disposable format already attempted") from exc
    try:
        os.fchmod(fd, 0o600)
        actual = os.fstat(fd)
        if (not stat.S_ISREG(actual.st_mode)
                or actual.st_uid != 0
                or stat.S_IMODE(actual.st_mode) != 0o600):
            raise Refused("QEMU format marker ownership or mode is unsafe")
        if os.write(fd, MARKER_CONTENT) != len(MARKER_CONTENT):
            raise Refused("Unable to record QEMU format attempt")
        os.fsync(fd)
    finally:
        os.close(fd)


def recovery_report() -> dict:
    """Read-only classification. Never claim an unmarked disk is safe."""
    try:
        marker = os.lstat(MARKER)
    except FileNotFoundError:
        status = "no-attempt-recorded"
        advice = "Disk condition unknown; obtain a fresh independent review."
    else:
        # A symlink/directory or altered marker is just as unsafe as a
        # legitimate attempt; refuse to infer any clean state.
        if not stat.S_ISREG(marker.st_mode) or marker.st_uid != 0:
            status = "untrusted-attempt-marker"
        else:
            status = "manual-recovery-required"
        advice = (
            "Disk may be partially formatted. Do not retry or erase "
            "automatically. Inspect the disposable target from a fresh boot."
        )
    return {
        "version": "eduardos.forge.qemu-recovery.v1",
        "status": status,
        "advice": advice,
        "target": "/dev/vda",
        "physical_hardware_supported": False,
        "write_operations_enabled": False,
        "destructive_disk_operations_enabled": False,
        "authorization_to_write": False,
        "auto_retry_enabled": False,
        "automatic_rollback_enabled": False,
    }
