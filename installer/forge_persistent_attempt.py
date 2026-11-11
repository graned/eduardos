"""Persistent fail-closed installation attempt marker (policy primitive only).

Unlike the existing /run disposable-VM lab marker, this record is designed
for a caller-provided persistent, root-controlled filesystem that survives
reboots. It never grants permission to write or performs disk operations.
A future privileged executor must validate the mount, storage identity and
independent authorization BEFORE integrating this primitive.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

FILE_MODE = 0o600
DIRECTORY_MODE = 0o700


class Refused(RuntimeError):
    pass


def marker_name(stable_id: str) -> str:
    if not isinstance(stable_id, str) or not stable_id.startswith("/dev/disk/by-id/"):
        raise Refused("A stable device identifier is required")
    if len(stable_id) > 256 or not stable_id.removeprefix("/dev/disk/by-id/").replace(
            "-", "").replace("_", "").replace(".", "").replace(":", "").replace("+", "").isalnum():
        raise Refused("Invalid stable device identifier")
    return hashlib.sha256(stable_id.encode("utf-8")).hexdigest() + ".attempt"


def _open_store(directory: Path) -> int:
    # Fail closed if the directory is missing, symlinked, group/world
    # accessible, or not owned by the effective caller.
    try:
        meta = directory.lstat()
    except OSError as exc:
        raise Refused("Persistent attempt directory is missing") from exc
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o077:
        raise Refused("Persistent attempt directory ownership or permissions are unsafe")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(directory, flags)
    except OSError as exc:
        raise Refused("Cannot hold persistent attempt directory safely") from exc
    current = os.fstat(fd)
    if current.st_dev != meta.st_dev or current.st_ino != meta.st_ino:
        os.close(fd)
        raise Refused("Persistent attempt directory changed while opening")
    return fd


def begin_attempt(directory: Path, stable_id: str) -> str:
    """Reserve a durable, one-way marker before the irreversible operation.

    No caller-visible reset or retry mechanism is exposed. The marker can
    only be cleared by a separate, future audited recovery workflow.
    This does not prove persistence of the directory's underlying mount.
    """
    name = marker_name(stable_id)
    dirfd = _open_store(Path(directory))
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            fd = os.open(name, flags, FILE_MODE, dir_fd=dirfd)
        except FileExistsError as exc:
            raise Refused("Prior installation attempt exists; automatic retry forbidden") from exc
        except OSError as exc:
            raise Refused("Cannot reserve installation attempt") from exc
        try:
            payload = b"EDOS_ATTEMPT_V1\nSTATE=RESERVED_NO_AUTO_RETRY\n"
            while payload:
                written = os.write(fd, payload)
                if written <= 0:
                    raise Refused("Could not persist attempt record")
                payload = payload[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(dirfd)
        return name
    finally:
        os.close(dirfd)


def inspect_attempt(directory: Path, stable_id: str) -> str:
    """Read only, refuse ambiguous/invalid persisted state."""
    name = marker_name(stable_id)
    dirfd = _open_store(Path(directory))
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=dirfd)
        except FileNotFoundError:
            return "none"
        except OSError as exc:
            raise Refused("Unable to read persistent attempt") from exc
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > 1024 or meta.st_uid != os.geteuid():
                raise Refused("Unexpected attempt record metadata")
            value = os.read(fd, 1025)
            if value != b"EDOS_ATTEMPT_V1\nSTATE=RESERVED_NO_AUTO_RETRY\n":
                raise Refused("Partial or unexpected attempt marker: manual recovery required")
            return "reserved-no-auto-retry"
        finally:
            os.close(fd)
    finally:
        os.close(dirfd)
