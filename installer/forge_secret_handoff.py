#!/usr/bin/env python3
"""Sealed dual-credential FD rehearsal for a future trusted Forge installer.

This is a pure in-process LIBRARY, not a privileged transport, daemon,
browser API, authentication service or physical-disk installer. It makes
LUKS and account credentials available as two independently sealed Linux
memfds with fixed roles, and validates a one-shot read under the same
trusted process. An authenticated cross-privilege FD handoff remains FUTURE
WORK: a caller-supplied FD number must never count as root authorization.

No secrets in CLI arguments, environment variables, JSON or Nix store.
Python cannot guarantee zeroization of immutable strings/internal copies.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
import stat
from collections.abc import Iterator

import forge_authorization as auth
import forge_credentials as credentials

_REQUIRED_SEALS = (
    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
)
_MAX_SECRET_BYTES = credentials.MAX_SECRET_BYTES


class Refused(ValueError):
    pass


@dataclass(frozen=True)
class CredentialFDs:
    luks: int
    account: int


@dataclass
class CredentialBuffers:
    """Mutable buffers valid ONLY within the consumer's context manager."""
    luks: bytearray
    account: bytearray


def _erase(secret: bytearray | None) -> None:
    if secret is not None:
        for index in range(len(secret)):
            secret[index] = 0


def _assert_fd(fd: int, role_label: str) -> os.stat_result:
    if isinstance(fd, bool) or not isinstance(fd, int) or fd < 0:
        raise Refused("Credential must be a valid inherited file descriptor")
    try:
        meta = os.fstat(fd)
        fd_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        seals = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
        link = os.readlink(f"/proc/self/fd/{fd}")
    except (OSError, ValueError):
        raise Refused("Credential FD is unavailable or unsealed") from None
    if (not stat.S_ISREG(meta.st_mode)
            or meta.st_size < 1 or meta.st_size > _MAX_SECRET_BYTES
            or not (fd_flags & fcntl.FD_CLOEXEC)
            or (seals & _REQUIRED_SEALS) != _REQUIRED_SEALS
            or link != f"/memfd:{role_label} (deleted)"):
        # A memfd name is a role label, NOT an attestation of its creator.
        raise Refused("Credential descriptor fails sealed role verification")
    return meta


def _read_secret(fd: int, role_label: str) -> bytearray:
    before = _assert_fd(fd, role_label)
    payload = bytearray(before.st_size)
    try:
        # preadv writes directly into our mutable bytearray, without a
        # Python bytes copy or altering the shared FD's seek position.
        view = memoryview(payload)
        try:
            read = os.preadv(fd, [view], 0)
        finally:
            view.release()
        after = _assert_fd(fd, role_label)
        if (read != before.st_size or after.st_size != before.st_size
                or after.st_dev != before.st_dev
                or after.st_ino != before.st_ino):
            raise Refused("Credential FD changed during consumption")
        try:
            value = payload.decode("utf-8", "strict")
            auth.validate_secret_pair(value, value, kind="Credential")
        except (UnicodeError, auth.Refused, TypeError):
            raise Refused("Credential contents failed validation") from None
        finally:
            # 'value' is an immutable Python string; the runtime cannot
            # guarantee its removal. This is not a hardened Rust helper.
            if "value" in locals():
                del value
        return payload
    except BaseException:
        _erase(payload)
        raise


class OneShotCredentialReader:
    """Consume two sealed role-labelled memfds only once.

    This one-shot property applies to this Python reader instance, not to
    arbitrary duplicate FDs held by an untrusted or malicious producer.
    """

    def __init__(self, handles: CredentialFDs):
        if not isinstance(handles, CredentialFDs):
            raise Refused("Expected explicit LUKS and account FD roles")
        self._handles = handles
        self._used = False

    @contextmanager
    def consume(self) -> Iterator[CredentialBuffers]:
        if self._used:
            raise Refused("Credential handoff was already consumed")
        self._used = True  # also consume on validation failure
        luks = None
        account = None
        try:
            first = _assert_fd(self._handles.luks, credentials.LUKS_MEMFD_LABEL)
            second = _assert_fd(self._handles.account, credentials.ACCOUNT_MEMFD_LABEL)
            if (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino):
                raise Refused("LUKS and account credentials must be distinct memfds")
            luks = _read_secret(self._handles.luks, credentials.LUKS_MEMFD_LABEL)
            account = _read_secret(self._handles.account, credentials.ACCOUNT_MEMFD_LABEL)
            yield CredentialBuffers(luks=luks, account=account)
        finally:
            _erase(account)
            _erase(luks)


@contextmanager
def sealed_credential_pair(luks: str, account: str) -> Iterator[CredentialFDs]:
    """Trusted, local producer rehearsal. FDs close on all exit paths."""
    with credentials.sealed_luks_fd(luks) as luks_fd:
        with credentials.sealed_account_fd(account) as account_fd:
            yield CredentialFDs(luks=luks_fd, account=account_fd)
