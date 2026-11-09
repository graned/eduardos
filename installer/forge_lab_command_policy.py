#!/usr/bin/env python3
"""Audited fixed-command boundary for the disposable QEMU installer ONLY.

Never import this into production hardware installers, the browser GUI,
the root read-only protocol or any physical-disk service. The sole
destructive caller is forge_executor_lab.py, whose independently enforced
root/QEMU/marker/held-/dev/vda guards MUST run for every attempt.

This class does NOT confer authorization. It prevents accidental command
substitution, dynamic argv expansion, automatic retry or phase reversal
inside the *already guarded disposable VM* path.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from collections.abc import Callable


STORE_PATH = re.compile(r"/nix/store/[a-zA-Z0-9+._-]+(?:/[a-zA-Z0-9+._/-]+)*\Z")
INSTALL_BIN = "/run/current-system/sw/bin/nixos-install"


class Refused(RuntimeError):
    pass


def _store_path(value: str, *, expect_file: bool) -> str:
    """Reject shell-like, parent traversal, and non-store user paths."""
    if (not isinstance(value, str) or not STORE_PATH.fullmatch(value)
            or value.endswith("/") or "//" in value
            or any(component in {".", ".."}
                   for component in value.split("/"))):
        raise Refused("Only an exact immutable Nix store path is accepted")
    resolved = os.path.realpath(value)
    if not resolved.startswith("/nix/store/"):
        raise Refused("Nix store symlink escaped the trusted store")
    item = Path(value)
    if expect_file and not item.is_file():
        raise Refused("Selected Nix store formatter is not a regular file")
    if not expect_file and not item.is_dir():
        raise Refused("Selected installed system is not a directory")
    return value


class AuditedLabCommands:
    """Exactly one Disko format, then exactly one NixOS install.

    The caller supplies independently enforced security gates. No generic
    run(command), shell injection, arbitrary disk path or callback that
    grants permissions is exposed. No formatter can run outside the
    existing QEMU-only forge_executor_lab.py guards.
    """

    def __init__(
        self,
        disko_script: str,
        system_closure: str,
        *,
        before_format: Callable[[], None],
        before_install: Callable[[], None],
    ) -> None:
        if not callable(before_format) or not callable(before_install):
            raise Refused("Mandatory independent pre-execution guards missing")
        self._disko = _store_path(disko_script, expect_file=True)
        self._system = _store_path(system_closure, expect_file=False)
        self._before_format = before_format
        self._before_install = before_install
        self._format_attempted = False
        self._formatted = False
        self._install_attempted = False

    @property
    def format_attempted(self) -> bool:
        """The disposable disk MAY be partially formatted."""
        return self._format_attempted

    def format(self) -> None:
        if self._format_attempted:
            raise Refused("Disposable format is already attempted; no retry")
        # Set before the guard AND subprocess: failure has no retry path.
        self._format_attempted = True
        self._before_format()
        # Must never use shell=True or accept a disk path from the caller.
        subprocess.run(
            [self._disko, "--yes-wipe-all-disks"],
            check=True, stdin=subprocess.DEVNULL, close_fds=True,
        )
        self._formatted = True

    def install(self) -> None:
        if not self._formatted or self._install_attempted:
            raise Refused("Install is out of order or has already been attempted")
        self._install_attempted = True
        # Recheck the exact mounted encrypted disk and held FD immediately
        # before the second external process is invoked.
        self._before_install()
        # Absolute binary path excludes PATH-based executable injection;
        # only one fixed, reviewed set of parameters is allowed.
        subprocess.run(
            [INSTALL_BIN, "--root", "/mnt", "--system", self._system,
             "--no-root-passwd"],
            check=True, stdin=subprocess.DEVNULL, close_fds=True,
        )
