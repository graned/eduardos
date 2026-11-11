"""Strict observer for the disposable-QEMU installation phase event stream.

Parses existing lab executor output only; never executes anything, invents
progress, provides disk-write authorization, or consumes credentials.
An installed phase can be reported only if EVERY prior phase was observed
exactly once and in order, without any halted state.
"""
from __future__ import annotations

PREFIX = "FORGE_QEMU_PHASE="
ORDER = (
    "guarded", "format-started", "formatted", "mounted-attested",
    "credential-staged", "re-attested", "install-started", "installed",
)
HALTED = frozenset(("halted-before-format", "halted-after-format-started"))


class Refused(ValueError):
    pass


def assess(output: str, *, process_returncode: int) -> dict:
    if not isinstance(output, str) or not isinstance(process_returncode, int) or isinstance(process_returncode, bool):
        raise Refused("Invalid lab progress evidence")
    if len(output) > 2 * 1024 * 1024:
        raise Refused("Lab progress evidence exceeds bounded size")
    events = []
    for line in output.splitlines():
        if not line.startswith(PREFIX):
            continue
        phase = line.removeprefix(PREFIX)
        if phase not in ORDER and phase not in HALTED:
            raise Refused("Unexpected lab phase")
        events.append(phase)
        if len(events) > len(ORDER) + 1:
            raise Refused("Duplicate or excessive lab phase events")

    normal = [phase for phase in events if phase in ORDER]
    if normal != list(ORDER[:len(normal)]):
        raise Refused("Missing, duplicate, or out-of-order lab phase")
    halted = [phase for phase in events if phase in HALTED]
    if len(halted) > 1 or (halted and events[-1] != halted[0]):
        raise Refused("Ambiguous terminal lab state")

    if halted:
        expected_halt = (
            "halted-after-format-started"
            if "format-started" in normal
            else "halted-before-format"
        )
        if halted[0] != expected_halt or process_returncode == 0:
            raise Refused("Inconsistent interrupted installer evidence")
        status = "manual-recovery-required" if "format-started" in normal else "aborted-before-format"
    elif normal == list(ORDER) and process_returncode == 0:
        status = "installed-lab-only"
    elif process_returncode == 0:
        raise Refused("Process exited successfully without complete phase evidence")
    else:
        # A SIGKILL or power outage can skip the final halt event: never
        # infer whether the disk is safe based solely on missing output.
        status = "incomplete-unknown-disk-state"

    return {
        "version": "eduardos.forge.qemu-phases.v1",
        "status": status,
        "observed_phases": tuple(events),
        "complete": status == "installed-lab-only",
        "physical_hardware_supported": False,
        "write_operations_enabled": False,
        "authorization_to_write": False,
        "automatic_retry_enabled": False,
    }
