"""Pure configuration validation for a future Forge installation wizard.

No disk probing, credential handling, privileged invocation or filesystem writes.
Never treat validation of a draft as authority to install.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RESERVED_USERS = frozenset({"root", "nixbld", "forge", "greeter"})
USER_PATTERN = re.compile(r"[a-z_][a-z0-9_-]{0,30}\Z", re.ASCII)
HOST_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,62}\Z", re.ASCII)
DISK_PATTERN = re.compile(r"/dev/disk/by-id/[A-Za-z0-9_.:+-]+\Z", re.ASCII)
MAX_NAME_LENGTH = 64


@dataclass(frozen=True)
class InstallationDraft:
    hostname: str
    username: str
    disk_by_id: str


def validate_draft(payload: object) -> dict:
    """Validate a non-secret, non-executable draft and return a neutral result.

    Never accepts passwords, encryption passphrases, or arbitrary Nix options.
    A stable-looking disk identifier is not device authorization.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["Draft must be a JSON object"],
                "mode": "dry-run-only", "write_operations_enabled": False}
    required = {"hostname", "username", "disk_by_id"}
    extras = set(payload) - required
    if extras:
        errors.append("Unexpected fields are not allowed")
    if any(key not in payload for key in required):
        errors.append("hostname, username and disk_by_id are required")

    def safe_str(key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            errors.append(f"{key} must be a string")
            return ""
        return value

    hostname = safe_str("hostname")
    username = safe_str("username")
    disk_id = safe_str("disk_by_id")
    if not HOST_PATTERN.fullmatch(hostname) or hostname.endswith("-"):
        errors.append("Invalid hostname")
    if not USER_PATTERN.fullmatch(username) or username in RESERVED_USERS:
        errors.append("Invalid or reserved username")
    if not DISK_PATTERN.fullmatch(disk_id):
        errors.append("Invalid stable disk identifier")

    return {
        "valid": not errors,
        "errors": errors,
        "mode": "dry-run-only",
        "write_operations_enabled": False,
        "note": "Validation does not verify device identity or authorize disk writes.",
    }
