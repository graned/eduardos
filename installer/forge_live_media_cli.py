#!/usr/bin/env python3
"""Read-only live ISO provenance diagnostic; never performs disk writes."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import forge_disk_identity as identity
import forge_live_media as live
import forge_privileged_guard as guard


def inspect() -> dict:
    mounts = live.mounts_from_mountinfo(Path("/proc/self/mountinfo").read_text())
    loops = live.sysfs_loop_backings()
    data = identity.probe()
    nodes, parents = guard.block_graph(data)
    proof = live.verify_live_overlay(mounts, loops, set(nodes))
    protected = set()
    for source in proof.iso_devnos:
        ancestors = guard.ancestor_devices(source, parents)
        if not any(nodes[key].get("type") in {"disk", "rom"}
                   for key in ancestors):
            raise live.Refused("ISO source lacks physical or optical backing")
        protected.update(ancestors)
    return {
        "status": "verified-live-media-provenance",
        "live_media": proof.report(),
        "protected_device_numbers": sorted(protected),
        "write_operations_enabled": False,
        "note": "This is a read-only diagnostic, not erasure authorization.",
    }


def main() -> int:
    try:
        result = inspect()
        print(json.dumps(result, indent=2))
        return 0
    except (live.Refused, guard.Refused, identity.Refused, OSError,
            ValueError, TypeError, KeyError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print(f"REFUSED: cannot prove live-media provenance: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
