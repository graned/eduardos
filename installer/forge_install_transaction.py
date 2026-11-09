#!/usr/bin/env python3
"""One-shot, fail-closed orchestration of the *disposable QEMU* installation.

This module has NO subprocess, disk, mount or credential operations. The
only caller is forge_executor_lab.py, which is permanently locked to a
disposable QEMU /dev/vda. Do not expose this as a physical-disk writer,
privileged protocol operation, browser endpoint, or authorization token.

The irreversible boundary is marked BEFORE invoking the formatter:
formatting can partially modify a disk even when the command fails.
There is deliberately no rollback, restart, resume or retry API.
"""
from __future__ import annotations

from collections.abc import Callable


class Refused(RuntimeError):
    pass


# Stable names, suitable for progress messages without credentials, device
# identifiers, command arguments, paths, or raw exception messages.
PHASES = frozenset({
    "guarded", "format-started", "formatted", "mounted-attested",
    "credential-staged", "re-attested", "install-started", "installed",
    "halted-before-format", "halted-after-format-started",
})


class InstallationTransaction:
    """Run an exact, closed sequence of operations once.

    The QEMU-only caller must supply trusted callables after proving its
    VM marker, target device ancestry and read-only held block descriptor.
    The state machine cannot invoke commands or grant disk permissions.
    """

    def __init__(
        self,
        *,
        preflight: Callable[[], None],
        format_disk: Callable[[], None],
        audit_mounted_target: Callable[[], None],
        stage_credential_hash: Callable[[], None],
        install_system: Callable[[], None],
        emit: Callable[[str], None] | None = None,
    ) -> None:
        operations = (preflight, format_disk, audit_mounted_target,
                      stage_credential_hash, install_system)
        if not all(callable(op) for op in operations):
            raise Refused("An installation step is not callable")
        if emit is not None and not callable(emit):
            raise Refused("Progress reporter must be callable")
        self._preflight = preflight
        self._format_disk = format_disk
        self._audit = audit_mounted_target
        self._credential = stage_credential_hash
        self._install = install_system
        self._emit = emit
        self._consumed = False
        self._format_started = False
        self.phase = "new"

    @property
    def format_started(self) -> bool:
        """The disk MAY be partially modified, even if formatting failed."""
        return self._format_started

    def _advance(self, phase: str) -> None:
        if phase not in PHASES:
            raise Refused("Unexpected installation phase")
        self.phase = phase
        if self._emit is not None:
            self._emit(phase)

    def run(self) -> None:
        """Execute exactly once; recheck mount topology before install."""
        if self._consumed:
            raise Refused("Installation transaction is already consumed")
        # Consume before any external callback, including a failed preflight.
        self._consumed = True
        try:
            self._preflight()
            self._advance("guarded")
            # Must be set BEFORE formatting; an interrupted formatter can
            # leave a partially erased or formatted target.
            self._format_started = True
            self._advance("format-started")
            self._format_disk()
            self._advance("formatted")

            self._audit()
            self._advance("mounted-attested")
            self._credential()
            self._advance("credential-staged")
            # Credential hashing and staging can take time. Attest mounts
            # again, while the held disk FD remains open, before install.
            self._audit()
            self._advance("re-attested")
            self._advance("install-started")
            self._install()
            self._advance("installed")
        except BaseException:
            # Do not auto retry, unmount or roll back after a destructive
            # boundary: that could damage a partially installed system.
            self._advance(
                "halted-after-format-started"
                if self._format_started else "halted-before-format"
            )
            raise
