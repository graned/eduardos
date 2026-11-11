"""Non-executable physical installation command policy.

Models only a fixed sequence of steps. Nothing here executes commands,
creates credentials, opens a disk or grants permission to write. In particular
a browser-provided review hash is NEVER a capability to invoke Disko.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

SCHEMA = "eduardos.forge.physical-command-review.v1"
STORE = re.compile(r"/nix/store/[a-z0-9]{32}-[A-Za-z0-9+._-]+(?:/[A-Za-z0-9+._-]+)*\Z")
DEVNO = re.compile(r"[0-9]+:[0-9]+\Z")
STABLE_ID = re.compile(r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+\Z")
PHASES = ("reattest-device", "reserve-durable-attempt", "format", "attest-mounts",
          "stage-sealed-credentials", "install", "verify-boot")


class Refused(ValueError):
    pass


@dataclass(frozen=True)
class ReviewedStep:
    phase: str
    description: str
    executable: bool = False


@dataclass(frozen=True)
class PhysicalInstallReview:
    version: str
    target_id: str
    target_devno: str
    closure: str
    disko_script: str
    phases: tuple[ReviewedStep, ...]
    write_operations_enabled: bool = False
    authorization_to_write: bool = False
    executable: bool = False


def _store_path(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096 or not STORE.fullmatch(value):
        raise Refused("Expected an exact immutable Nix store path")
    if any(part in (".", "..") for part in value.split("/")):
        raise Refused("Store paths must not contain traversal")
    return value


def review_fixed_plan(*, target_id: str, target_devno: str,
                      disko_script: str, system_closure: str) -> PhysicalInstallReview:
    """Return a *description*, never argv or permission to perform a write.

    The caller must verify actual store object type and provenance at the
    future trusted executor boundary. Here no paths are opened or executed.
    """
    if not isinstance(target_id, str) or len(target_id) > 256 or not STABLE_ID.fullmatch(target_id):
        raise Refused("An exact stable target ID is required")
    if not isinstance(target_devno, str) or not DEVNO.fullmatch(target_devno):
        raise Refused("A kernel block identity is required")
    script, closure = _store_path(disko_script), _store_path(system_closure)
    descriptions = (
        "Independently reattest the exact held disk and boot/mount/swap ancestry",
        "Durably reserve one no-retry attempt before any irreversible write",
        "Run only an audited fixed Disko layout after independent authorization",
        "Prove encrypted installed subvolume and EFI mount ancestry",
        "Consume distinct sealed LUKS and account credential descriptors",
        "Install only the reviewed immutable NixOS closure",
        "Verify the resulting encrypted boot and account login",
    )
    return PhysicalInstallReview(
        version=SCHEMA,
        target_id=target_id,
        target_devno=target_devno,
        disko_script=script,
        closure=closure,
        phases=tuple(ReviewedStep(phase, description)
                     for phase, description in zip(PHASES, descriptions)),
    )


def verify_no_write_authority(review: PhysicalInstallReview) -> None:
    if (not isinstance(review, PhysicalInstallReview) or review.version != SCHEMA
            or review.executable is not False
            or review.write_operations_enabled is not False
            or review.authorization_to_write is not False
            or tuple(step.phase for step in review.phases) != PHASES
            or any(step.executable is not False for step in review.phases)):
        raise Refused("Command review must remain non-executable")
