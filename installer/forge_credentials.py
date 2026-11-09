#!/usr/bin/env python3
"""Credential primitives for the future *trusted* Forge installer.

This is deliberately a LIBRARY, not an executable installer or GUI endpoint.
It can stage one user password hash only under the already-open, trusted
installed-target root directory FD provided by a future privileged backend.

The backend must FIRST verify its mountpoints and encrypted target; this
module does not discover, format, mount, or authorize disks.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import re
import secrets
import stat
import subprocess
from collections.abc import Iterator

from forge_authorization import Refused as AuthorizationRefused
from forge_authorization import validate_secret_pair, validate_user_settings

_O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_O_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_SHA512 = re.compile(r"\$6\$[A-Za-z0-9./]{1,16}\$[A-Za-z0-9./]{80,120}\Z")
MAX_SECRET_BYTES = 4096


class Refused(ValueError):
    """No credential was installed; caller must abort the install."""


def account_hash_path(username: str) -> str:
    try:
        validate_user_settings(username, "eduardos")
    except (AuthorizationRefused, TypeError):
        raise Refused("Invalid or reserved installed account name") from None
    return f"/persist/eduardos/credentials/{username}.hash"


def _secret_bytes(secret: str) -> bytearray:
    if not isinstance(secret, str):
        raise Refused("Secret must be supplied directly in process memory")
    # Reject line-break and NUL; account hashing uses OpenSSL's stdin mode.
    try:
        validate_secret_pair(secret, secret, kind="Credential")
    except AuthorizationRefused as exc:
        raise Refused(str(exc)) from None
    payload = bytearray(secret.encode("utf-8"))
    if not payload or len(payload) > MAX_SECRET_BYTES:
        for i in range(len(payload)):
            payload[i] = 0
        raise Refused("Credential byte length is invalid")
    return payload


def hash_user_password(password: str) -> str:
    """Salted SHA-512-crypt with secrets on stdin (never in argv/env).

    Requiring the platform's openssl is intentional: Python 3.13 removed
    crypt(), and NixOS shadow/PAM supports SHA-512-crypt ($6$).

    Python strings and subprocess buffers are not guaranteed zeroizable:
    a future Rust helper can improve the memory handling at the trust edge.
    """
    payload = _secret_bytes(password)
    try:
        payload.extend(b"\n")
        try:
            result = subprocess.run(
                ["openssl", "passwd", "-6", "-stdin"],
                input=bytes(payload),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=15,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise Refused("Password hashing failed") from None
        try:
            output = result.stdout.decode("ascii").strip()
        except UnicodeError:
            raise Refused("Password hash returned invalid encoding") from None
        if not _SHA512.fullmatch(output):
            raise Refused("Password hash returned unexpected format")
        return output
    finally:
        for i in range(len(payload)):
            payload[i] = 0


def _assert_owned_dir(fd: int, uid: int, *, private: bool) -> None:
    meta = os.fstat(fd)
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != uid:
        raise Refused("Unexpected target-directory ownership or type")
    mode = stat.S_IMODE(meta.st_mode)
    if private:
        if mode != 0o700:
            raise Refused("Credential directory must be private (0700)")
    elif mode & 0o022:
        raise Refused("Target directory is writable by group or others")


def _child_dir(parent: int, name: str, uid: int) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    fd = os.open(name, _O_DIR, dir_fd=parent)
    try:
        _assert_owned_dir(fd, uid, private=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_user_hash(target_root_fd: int, username: str, password_hash: str,
                    *, expected_uid: int = 0) -> str:
    """Atomically CREATE ONLY the installed account hash from a trusted dirfd.

    The root FD must have been opened and independently validated by the
    future installer (including proof /persist belongs to target LUKS2).
    Neither this function nor a successful result authorizes disk erasure.
    No overwrites; partially written hash files are never published.
    """
    path = account_hash_path(username)
    if not isinstance(password_hash, str) or not _SHA512.fullmatch(password_hash):
        raise Refused("Refusing non-SHA512-crypt account password hash")
    _assert_owned_dir(target_root_fd, expected_uid, private=False)
    # /persist is pre-mounted by Disko; never create it if missing.
    persist_fd = os.open("persist", _O_DIR, dir_fd=target_root_fd)
    try:
        _assert_owned_dir(persist_fd, expected_uid, private=False)
        eduardos_fd = _child_dir(persist_fd, "eduardos", expected_uid)
        try:
            creds_fd = _child_dir(eduardos_fd, "credentials", expected_uid)
            try:
                _atomic_new_file(creds_fd, username + ".hash",
                                 (password_hash + "\n").encode("ascii"), expected_uid)
            finally:
                os.close(creds_fd)
        finally:
            os.close(eduardos_fd)
    finally:
        os.close(persist_fd)
    return path


def _atomic_new_file(dir_fd: int, name: str, content: bytes, owner: int) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}\.hash", name):
        raise Refused("Invalid installed credential filename")
    tmp = "." + secrets.token_hex(16) + ".tmp"
    fd = os.open(tmp, _O_FILE, 0o600, dir_fd=dir_fd)
    published = False
    try:
        try:
            os.fchmod(fd, 0o600)
            meta = os.fstat(fd)
            if meta.st_uid != owner or not stat.S_ISREG(meta.st_mode):
                raise Refused("Unsafe hash file owner or type")
            written = 0
            while written < len(content):
                count = os.write(fd, content[written:])
                if count <= 0:
                    raise OSError("Short hash file write")
                written += count
            os.fsync(fd)
        finally:
            os.close(fd)
        # Atomic create-only publication: os.link does NOT replace an
        # existing account hash, even if an attacker planted a symlink.
        os.link(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd,
                follow_symlinks=False)
        published = True
    finally:
        os.unlink(tmp, dir_fd=dir_fd)
        os.fsync(dir_fd)
    if not published:
        raise Refused("Credential hash file was not published")


@contextmanager
def sealed_luks_fd(passphrase: str) -> Iterator[int]:
    """One-use ephemeral LUKS passphrase in a Linux sealed anonymous memfd.

    The future backend may pass this FD to cryptsetup via pass_fds; only
    an FD number (never the secret) may appear in process arguments.
    No consumer or destructive disk invocation is provided here.
    """
    payload = _secret_bytes(passphrase)
    fd: int | None = None
    try:
        try:
            fd = os.memfd_create(
                "eduardos-ephemeral-luks",
                os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
            )
            view = memoryview(payload)
            try:
                written = 0
                while written < len(payload):
                    count = os.write(fd, view[written:])
                    if count <= 0:
                        raise OSError("Short LUKS secret write")
                    written += count
            finally:
                view.release()
            os.lseek(fd, 0, os.SEEK_SET)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                        fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW |
                        fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        except (OSError, AttributeError):
            raise Refused("Kernel cannot securely create a sealed LUKS secret FD") from None
        yield fd
    finally:
        if fd is not None:
            os.close(fd)
        for i in range(len(payload)):
            payload[i] = 0
