#!/usr/bin/env python3
"""Forge Installer pre-execution authorization session (NO DISK WRITES).

All authorization is process-local and short lived; NOT an authorization
boundary for a privileged installer. A future privileged helper MUST repeat
all checks independently and obtain its own local consent.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import forge_disk_identity as identity

TTL_SECONDS = 120
USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,30}")
ALLOWED_USERNAMES = {"root", "nixbld", "forge", "greeter"}
MIN_PASSPHRASE_LEN = 12


class Refused(ValueError):
    pass


@dataclass(frozen=True)
class UserSettings:
    username: str
    hostname: str


def validate_user_settings(username: str, hostname: str) -> UserSettings:
    if not USER_RE.fullmatch(username) or username in ALLOWED_USERNAMES:
        raise Refused("Invalid or reserved account name")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", hostname) or hostname.endswith("-"):
        raise Refused("Invalid hostname")
    return UserSettings(username, hostname)


def validate_secret_pair(first: str, second: str, *, kind: str) -> None:
    if len(first) < MIN_PASSPHRASE_LEN:
        raise Refused(f"{kind} must have at least {MIN_PASSPHRASE_LEN} characters")
    if "\n" in first or "\0" in first or "\r" in first:
        raise Refused(f"{kind} contains unsupported characters")
    if not secrets.compare_digest(first.encode(), second.encode()):
        raise Refused(f"{kind} entries do not match")


def prompt_credentials(settings: UserSettings,
                       prompt: Callable[[str], str] = getpass.getpass) -> None:
    """Validate secrets through a TTY without emitting or storing them.

    No secret is returned or written to disk. This is input UX rehearsal
    only: the future privileged helper must re-collect secrets securely.
    """
    if not sys.stdin.isatty():
        raise Refused("Secret input requires an interactive terminal")
    first = prompt("LUKS passphrase (never displayed): ")
    second = prompt("Repeat LUKS passphrase: ")
    validate_secret_pair(first, second, kind="LUKS passphrase")
    first = second = ""
    account = prompt(f"Password for {settings.username}: ")
    repeat = prompt("Repeat account password: ")
    validate_secret_pair(account, repeat, kind="Account password")
    account = repeat = ""


def confirm_text(identifier: str) -> str:
    return f"ERASE {identifier}"


class AuthorizationSession:
    def __init__(self, review: dict, *, clock: Callable[[], float] = time.monotonic):
        if not isinstance(review, dict) or not isinstance(review.get("snapshot"), dict):
            raise Refused("Malformed disk review")
        self._review = review
        self._clock = clock
        self._deadline = clock() + TTL_SECONDS
        self._used = False
        self._nonce = secrets.token_urlsafe(24)

    @property
    def challenge(self) -> str:
        return confirm_text(self._review["snapshot"].get("stable_id", ""))

    @property
    def nonce(self) -> str:
        return self._nonce

    def authorize(self, answer: str, nonce: str, *,
                  verify_review: Callable[[dict], dict] = identity.verify) -> dict:
        # Never treat a session token or review hash as permission to write.
        if self._used:
            raise Refused("Authorization session was already consumed")
        # Consume on any attempt to prevent multiple guesses/replays.
        self._used = True
        if self._clock() >= self._deadline:
            raise Refused("Authorization session expired")
        if not secrets.compare_digest(nonce, self._nonce):
            raise Refused("Invalid authorization nonce")
        if not secrets.compare_digest(answer, self.challenge):
            raise Refused("Disk erasure confirmation does not match selected device")
        verified = verify_review(self._review)
        if verified.get("verified") is not True or verified.get("write_operations_enabled") is not False:
            raise Refused("Selected disk identity failed independent revalidation")
        # Intentionally no 'execute', privilege grant, or secret material.
        return {"status": "review-confirmed", "disk_id": verified["stable_id"],
                "review_sha256": verified["sha256"],
                "write_operations_enabled": False,
                "note": "A future privileged installer must repeat checks and consent."}


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eduardOS installation consent rehearsal (read-only)")
    parser.add_argument("--review", required=True, help="Disk identity review JSON generated on this machine")
    parser.add_argument("--username", required=True, help="Proposed non-root user")
    parser.add_argument("--hostname", required=True, help="Proposed host name")
    parser.add_argument("--check-credentials", action="store_true",
                        help="Interactively validate two secret pairs; discard after checking")
    args = parser.parse_args(argv)
    try:
        settings = validate_user_settings(args.username, args.hostname)
        # The review must be a regular file, not a symlink. Treat it as
        # untrusted input; the live device is always re-probed during consent.
        path = Path(args.review)
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 128 * 1024:
            raise Refused("Review must be a small, regular JSON file")
        review = json.loads(path.read_text(encoding="utf-8"))
        # Fail before requesting credentials when hardware is not eligible.
        identity.verify(review)
        session = AuthorizationSession(review)
        print("eduardOS Forge Installer — authorization rehearsal, NO DISK WRITES")
        print(f"User: {settings.username} | Host: {settings.hostname}")
        print(f"Target: {review['snapshot']['stable_id']}")
        if not sys.stdin.isatty():
            raise Refused("Explicit local console confirmation requires a TTY")
        if args.check_credentials:
            prompt_credentials(settings)
            print("Credential syntax validated. No passwords were saved or passed to an installer.")
        print(f"Type exactly: {session.challenge}")
        answer = input("Confirmation: ")
        # A nonce is process-private, not displayed in terminal or browser.
        result = session.authorize(answer, session.nonce)
        print(json.dumps(result, indent=2))
        return 0
    except (Refused, identity.Refused, OSError, ValueError, TypeError,
            KeyError, json.JSONDecodeError, EOFError, KeyboardInterrupt) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
