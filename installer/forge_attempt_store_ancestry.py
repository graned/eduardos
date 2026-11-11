"""Read-only physical ancestry of a proposed persistent attempt-store mount.

The store must not be hosted by the disk that would be erased. A distinct
block ancestry is necessary, but NOT sufficient to prove cross-boot
persistence, root control, write ordering or authorization for an install.
"""
from __future__ import annotations

import re

import forge_attempt_store_provenance as store
import forge_privileged_guard as guard

DEVNO = re.compile(r"[0-9]+:[0-9]+\Z")


class Refused(ValueError):
    pass


def attest_separate_backing(*, mountpoint: str, mountinfo: str,
                            block_inventory: dict, target_devno: str) -> dict:
    """Prove a candidate store is rooted in physical media *other* than target.

    Pure inspection of caller-supplied evidence. A trusted privileged caller
    MUST collect mountinfo and lsblk independently in one mount namespace,
    pin the device handles, and repeat checks before durable reservation.
    """
    if not isinstance(target_devno, str) or not DEVNO.fullmatch(target_devno):
        raise Refused("Invalid proposed installation target identity")
    try:
        candidate = store.mount_evidence(mountpoint, mountinfo)
        nodes, parents = guard.block_graph(block_inventory)
        root_devno = candidate["devno"]
        if root_devno not in nodes or target_devno not in nodes:
            raise Refused("Unknown or incomplete mount/store target block identity")
        if nodes[target_devno].get("type") != "disk":
            raise Refused("Installation target must be a physical whole disk")
        ancestry = guard.ancestor_devices(root_devno, parents)
        if target_devno in ancestry:
            raise Refused("Attempt store would be erased with selected disk")
        disks = [key for key in ancestry if nodes[key].get("type") == "disk"]
        if len(disks) != 1:
            raise Refused("Ambiguous or missing physical backing disk for attempt store")
        for key in ancestry:
            node = nodes[key]
            if node.get("ro") or node.get("rm") or node.get("type") in ("loop", "rom"):
                raise Refused("Store has removable, read-only or loop/optical ancestry")
        if candidate.get("durability_proven") is not False:
            raise Refused("Mount inspection must never claim verified durability")
    except (guard.Refused, store.Refused, KeyError, TypeError, ValueError) as exc:
        raise Refused("Attempt store ancestry could not be safely attested") from exc
    return {
        "status": "separate-physical-backing-candidate",
        "store_mount_devno": root_devno,
        "store_disk_devno": disks[0],
        "install_target_devno": target_devno,
        "durability_proven": False,
        "write_operations_enabled": False,
        "authorization_to_write": False,
        "note": "Cross-reboot persistence and trusted storage lifecycle unverified.",
    }
