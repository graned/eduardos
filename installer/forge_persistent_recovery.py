"""Read-only recovery classification for persistent Forge attempt records.

Never removes markers, invokes Disko, authorizes retries or infers a clean
disk from a missing record. A root-only caller supplies a dedicated, existing
attempt store; mount evidence is candidate-only, not durability attestation.
"""
from __future__ import annotations

import os
from pathlib import Path

import forge_attempt_store_provenance as provenance
import forge_persistent_attempt as attempts

SCHEMA = "eduardos.forge.persistent-recovery.v1"


class Refused(ValueError):
    pass


def report(store: Path, stable_id: str, *, mountinfo: str | None = None) -> dict:
    """Return a non-secret status; all states require independent disk review."""
    if os.geteuid() != 0:
        raise Refused("Persistent recovery inspection requires a trusted root caller")
    source = (Path("/proc/self/mountinfo").read_text()
              if mountinfo is None else mountinfo)
    try:
        evidence = provenance.check_candidate_directory(Path(store), source)
        state = attempts.inspect_attempt(Path(store), stable_id)
    except (provenance.Refused, attempts.Refused, OSError) as exc:
        raise Refused("Persistent recovery evidence is unsafe or unavailable") from exc

    if evidence.get("durability_proven") is not False or evidence.get("authorization_to_write") is not False:
        raise Refused("Unexpected persistent store evidence")

    if state == "none":
        status = "unproven-no-record"
        advice = ("No attempt marker was found. This DOES NOT prove a blank "
                  "disk or authorize a new installation; independently review storage.")
    elif state == "reserved-no-auto-retry":
        status = "manual-recovery-required"
        advice = ("An installation may have partially modified the disk. "
                  "Do not retry automatically. Inspect and recover manually.")
    else:
        raise Refused("Unrecognized attempt state")

    return {
        "version": SCHEMA,
        "status": status,
        "advice": advice,
        "store_evidence": "candidate-local-mount-only",
        "durability_proven": False,
        "write_operations_enabled": False,
        "authorization_to_write": False,
        "automatic_retry_enabled": False,
        "automatic_rollback_enabled": False,
    }
