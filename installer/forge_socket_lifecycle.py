#!/usr/bin/env python3
"""Root-owned, private Unix socket lifecycle for a *future* Forge preflight.

Library only: no systemd unit, service runner, listener thread, executable,
GUI access, credential endpoint or physical disk operation is installed.
The real path is fixed and must be pre-created by an independently audited
root-controlled deployment policy. No automatic path overwrite/removal.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import socket
import stat
from collections.abc import Iterator

RUNTIME_DIR = "/run/eduardos"
SOCKET_NAME = "forge-preflight.sock"
SOCKET_MODE = 0o600
DIRECTORY_MODE = 0o700


class Refused(ValueError):
    pass


def _private_parent(directory: str, owner_uid: int) -> None:
    if not isinstance(directory, str) or not os.path.isabs(directory):
        raise Refused("Private runtime directory must be absolute")
    # O_NOFOLLOW and lstat defend the final directory component. The
    # production directory path is a fixed root-controlled /run location.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(directory, flags)
    try:
        held = os.fstat(fd)
        name = os.lstat(directory)
        if (not stat.S_ISDIR(held.st_mode)
                or not stat.S_ISDIR(name.st_mode)
                or (held.st_dev, held.st_ino) != (name.st_dev, name.st_ino)
                or held.st_uid != owner_uid
                or stat.S_IMODE(held.st_mode) != DIRECTORY_MODE):
            raise Refused("Runtime directory ownership/mode is unsafe")
    finally:
        os.close(fd)


@contextmanager
def _private_listener(directory: str, owner_uid: int) -> Iterator[socket.socket]:
    """Private socket fixture shared by audited root wrapper and tests.

    Never unlink a pre-existing pathname; that could remove someone else's
    Unix socket. Clean up only the exact socket inode created here.
    """
    _private_parent(directory, owner_uid)
    path = os.path.join(directory, SOCKET_NAME)
    if len(os.fsencode(path)) >= 104:
        raise Refused("Unix socket pathname exceeds portable bound")
    try:
        os.lstat(path)
    except FileNotFoundError:
        pass
    else:
        raise Refused("Local socket path already exists")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    socket_identity = None
    try:
        sock.bind(path)
        os.chmod(path, SOCKET_MODE)
        actual = os.lstat(path)
        if (not stat.S_ISSOCK(actual.st_mode)
                or actual.st_uid != owner_uid
                or stat.S_IMODE(actual.st_mode) != SOCKET_MODE):
            raise Refused("Local socket ownership/mode is unsafe")
        socket_identity = (actual.st_dev, actual.st_ino)
        _private_parent(directory, owner_uid)
        sock.listen(1)
        sock.settimeout(5.0)
        yield sock
    finally:
        sock.close()
        # A root-controlled private directory prevents untrusted swaps;
        # still compare the inode to avoid unlinking a replaced path.
        try:
            current = os.lstat(path)
            if (socket_identity is not None
                    and stat.S_ISSOCK(current.st_mode)
                    and (current.st_dev, current.st_ino) == socket_identity):
                _private_parent(directory, owner_uid)
                os.unlink(path)
        except FileNotFoundError:
            pass


@contextmanager
def root_listener() -> Iterator[socket.socket]:
    """Optional root-only API. NOT wired into any installed service.

    The directory must ALREADY exist, be root-owned and have mode 0700.
    This function never creates root files/dirs or auto-binds on import.
    """
    if os.geteuid() != 0:
        raise Refused("Only root may open a production preflight listener")
    with _private_listener(RUNTIME_DIR, 0) as sock:
        yield sock
