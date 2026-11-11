"""Root-only, NON-EXECUTABLE final physical target review gate.

Composes independently implemented read-only checks. This is intentionally
not used by a formatter or GUI and returns no reusable capability. The
future trusted executor must repeat checks at the actual irreversible
operation, enforce a durable lock and independently obtain local consent.
"""
from __future__ import annotations

import os
from pathlib import Path

import forge_backend as backend
import forge_physical_command_policy as policy


class Refused(ValueError):
    pass


def review_before_execution(held: backend.HeldTarget, *,
                            disko_script: str, system_closure: str) -> dict:
    """Produce a closed, non-executable assessment from a held root disk.

    The immutable store object identities must be independently verified
    by the eventual executor; syntax-only store review is NOT provenance.
    """
    if os.geteuid() != 0:
        raise Refused("Final physical target review requires trusted root")
    if not isinstance(held, backend.HeldTarget) or held.used:
        raise Refused("A live unused held target is required")

    # Re-probe boot, stable alias, held device, mount/swap and topology.
    outcome = held.reattest_preformat()
    if (not isinstance(outcome, dict)
            or outcome.get("status") != "preformat-attested-read-only"
            or outcome.get("target_devno") != held.devno
            or outcome.get("write_operations_enabled") is not False
            or outcome.get("authorization_to_write") is not False
            or outcome.get("destructive_disk_operations_enabled") is not False):
        raise Refused("Fresh read-only preformat attestation refused")

    snapshot = held.review["snapshot"]
    plan = policy.review_fixed_plan(
        target_id=snapshot["stable_id"],
        target_devno=held.devno,
        disko_script=disko_script,
        system_closure=system_closure,
    )
    policy.verify_no_write_authority(plan)
    if plan.target_id != snapshot["stable_id"] or plan.target_devno != held.devno:
        raise Refused("Command plan disk differs from held target")

    # Another fresh disk FD / boot identity check after plan construction.
    # No disk writes, secrets, commands, or privileged service connections.
    held._fresh_device(backend.identity.probe())
    return {
        "status": "final-review-only",
        "target_devno": held.devno,
        "policy_version": plan.version,
        "phases": [step.phase for step in plan.phases],
        "write_operations_enabled": False,
        "authorization_to_write": False,
        "destructive_disk_operations_enabled": False,
        "credentials_accepted": False,
        "executable": False,
        "note": "Evidence only. No physical execution authority granted.",
    }
