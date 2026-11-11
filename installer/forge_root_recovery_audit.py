"""Root-only read-only recovery audit combining real kernel evidence.

The future installer must separately prove cross-reboot persistence and
protect this store from removal. No marker creation, deletion, retry,
device write or permission to execute an installer is exposed.
"""
from __future__ import annotations

import os
from pathlib import Path

import forge_attempt_store_ancestry as ancestry
import forge_disk_identity as identity
import forge_persistent_recovery as recovery
import forge_attempt_store_provenance as provenance


class Refused(ValueError):
    pass


def audit(*, store: Path, stable_id: str, target_devno: str) -> dict:
    """Classify an existing attempt marker only after a fresh topology audit.

    Uses independently sampled lsblk and mountinfo from this caller's mount
    namespace. Rechecks mountinfo + ancestry after marker inspection so
    changed mount sources fail closed.
    """
    if os.geteuid() != 0:
        raise Refused("Trusted root is required for recovery evidence")
    if not isinstance(store, Path) or not store.is_absolute():
        raise Refused("Expected absolute persistent store path")
    try:
        initial_mounts = Path("/proc/self/mountinfo").read_text()
        initial_inventory = identity.probe()
        first = ancestry.attest_separate_backing(
            mountpoint=str(store), mountinfo=initial_mounts,
            block_inventory=initial_inventory, target_devno=target_devno,
        )
        if first.get("status") != "separate-physical-backing-candidate" or \
                first.get("durability_proven") is not False or \
                first.get("authorization_to_write") is not False:
            raise Refused("Unsafe attempt-store ancestry evidence")
        # This additionally validates the store directory owner/mode and
        # rejects partial, symlinked or changed attempt record contents.
        state = recovery.report(store, stable_id, mountinfo=initial_mounts)
        if (state.get("write_operations_enabled") is not False or
                state.get("authorization_to_write") is not False or
                state.get("automatic_retry_enabled") is not False or
                state.get("durability_proven") is not False):
            raise Refused("Recovery state unexpectedly grants authority")

        last_mounts = Path("/proc/self/mountinfo").read_text()
        last_inventory = identity.probe()
        second = ancestry.attest_separate_backing(
            mountpoint=str(store), mountinfo=last_mounts,
            block_inventory=last_inventory, target_devno=target_devno,
        )
        # Never accept a reattached storage device or changed mount context.
        if first != second or initial_mounts != last_mounts:
            raise Refused("Attempt store topology changed during recovery audit")
    except (ancestry.Refused, recovery.Refused, provenance.Refused,
            OSError, TypeError, ValueError, KeyError) as exc:
        raise Refused("Cannot prove safe read-only recovery evidence") from exc
    return {
        "version": "eduardos.forge.root-recovery-audit.v1",
        "status": state["status"],
        "store_evidence": first["status"],
        "durability_proven": False,
        "write_operations_enabled": False,
        "authorization_to_write": False,
        "destructive_disk_operations_enabled": False,
        "automatic_retry_enabled": False,
        "automatic_rollback_enabled": False,
        "note": "Recovery evidence only. Existing markers require manual recovery.",
    }
