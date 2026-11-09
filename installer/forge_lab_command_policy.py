#!/usr/bin/env python3
"""Non-executable command allowlist contract for QEMU installation review.

No subprocess, shell, disk operation, authorizer or execution method.
This is a *static contract* for comparing the existing guarded QEMU
installation against intended fixed commands. It cannot grant permission
to run Disko or any command on real hardware.

The executable integration requires a separately reviewed change and
destructive disposable-QEMU install test before it is enabled.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

import forge_privileged_guard as topology_guard

SCHEMA = "eduardos.forge.command-review.v1"
TARGET = "/dev/vda"  # disposable QEMU only
STORE_PATH = re.compile(r"/nix/store/[a-zA-Z0-9+._-]+(?:/[a-zA-Z0-9+._-]+)*\Z")
FORMAT_PHASE = "format-disposable-vda"
INSTALL_PHASE = "install-disposable-vda"


class Refused(ValueError):
    pass


def _store_path(value: str, *, expect_file: bool) -> str:
    """Reject path traversal, injection, and non-Nix-store targets."""
    if (not isinstance(value, str) or not STORE_PATH.fullmatch(value)
            or value.endswith("/") or "//" in value
            or any(part in {".", ".."} for part in value.split("/"))):
        raise Refused("Only exact immutable Nix store paths are accepted")
    resolved = os.path.realpath(value)
    if not resolved.startswith("/nix/store/"):
        raise Refused("Nix store path resolved outside the store")
    item = Path(value)
    if expect_file and not item.is_file():
        raise Refused("Format script must be a Nix store regular file")
    if not expect_file and not item.is_dir():
        raise Refused("Installed system must be a Nix store directory")
    return value


@dataclass(frozen=True)
class ReviewedCommand:
    phase: str
    description: str
    arguments: tuple[str, ...]
    executable: bool = False


@dataclass(frozen=True)
class LabCommandReview:
    """Immutable *descriptions*, not executable commands or capabilities."""

    disk: str
    format_step: ReviewedCommand
    install_step: ReviewedCommand
    write_operations_enabled: bool = False
    authorization_to_write: bool = False


def review_commands(disko_script: str, system_closure: str) -> LabCommandReview:
    """Validate static store inputs and return a NON-EXECUTABLE review.

    The chosen disk can never be supplied by the caller. No environment,
    shell, output redirection, secret, disk FD or extra argv is accepted.
    """
    disko = _store_path(disko_script, expect_file=True)
    system = _store_path(system_closure, expect_file=False)
    return LabCommandReview(
        disk=TARGET,
        format_step=ReviewedCommand(
            phase=FORMAT_PHASE,
            description="Guarded disposable VM Disko layout",
            arguments=(disko, "--yes-wipe-all-disks"),
        ),
        install_step=ReviewedCommand(
            phase=INSTALL_PHASE,
            description="Guarded disposable VM installed NixOS closure",
            arguments=("nixos-install", "--root", "/mnt", "--system",
                       system, "--no-root-passwd"),
        ),
    )


def review_kernel_boundary(expected_devno: str, *, data: dict,
                           mountinfo: str, swaps: str,
                           loop_backings: dict[str, str]) -> dict:
    """Read-only, fixed /dev/vda ancestry check for the irreversible gate.

    The caller MUST also hold and recheck its O_RDONLY block descriptor,
    prove the disposable QEMU environment, and repeat all kernel probes
    immediately before ANY future write. This returns NO authority.
    """
    if (not isinstance(expected_devno, str)
            or not re.fullmatch(r"[0-9]+:[0-9]+", expected_devno)
            or not isinstance(data, dict)
            or not isinstance(mountinfo, str)
            or not isinstance(swaps, str)
            or not isinstance(loop_backings, dict)):
        raise Refused("Missing trusted kernel block or mount evidence")
    try:
        report = topology_guard.guard_topology(
            TARGET, data, mountinfo, swaps, loop_backings=loop_backings,
        )
    except topology_guard.Refused as exc:
        raise Refused("Kernel mount/swap/boot ancestry audit refused") from exc
    if (not isinstance(report, dict)
            or report.get("target_devno") != expected_devno
            or report.get("target_path") != TARGET
            or report.get("write_operations_enabled") is not False):
        raise Refused("Fixed QEMU disk identity or write prohibition changed")
    return {
        "version": SCHEMA,
        "status": "lab-boundary-reviewed-read-only",
        "target_devno": expected_devno,
        "write_operations_enabled": False,
        "authorization_to_write": False,
    }
