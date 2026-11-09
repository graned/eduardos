#!/usr/bin/env python3
"""Bounded subprocess cancellation for the disposable QEMU installer only.

Does not authorize disk writes. The caller must pass all existing QEMU,
target-disk, irreversible-boundary and attempt-marker checks first.
"""
from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Sequence


class Cancelled(RuntimeError):
    pass


def run_child(argv: Sequence[str]) -> None:
    """Wait for one fixed-argv child; terminate its process group on interrupt.

    Children start in a fresh process group so cancellation cannot propagate
    to the VM test harness. SIGTERM/SIGINT are intercepted only during this
    blocking step. SIGKILL/power loss are not catchable; the separate
    same-boot marker and manual recovery policy still apply.
    """
    if not argv or not all(isinstance(part, str) and part for part in argv):
        raise ValueError("Invalid lab child argv")
    child = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL,
                             start_new_session=True, close_fds=True)
    previous = {}

    def cancelled(_signum, _frame):
        raise Cancelled("Disposable QEMU installer interrupted; manual recovery required")

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, cancelled)
        returncode = child.wait()
        if returncode:
            raise subprocess.CalledProcessError(returncode, list(argv))
    finally:
        # This includes cancellation and Python exceptions. Do not leave a
        # formatter/install process running after its supervisor has stopped.
        # Even an exited leader may have children in the same group.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
