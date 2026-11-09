#!/usr/bin/env python3
"""Physical VT-only operator confirmation for read-only Forge preflight.

No GUI, PTY, SSH, sudo prompt, cryptsetup, formatting, secret transport,
or disk writer. Explicitly requires a root process in the foreground
process group of an active Linux /dev/ttyN virtual console.
"""
from __future__ import annotations

import fcntl
import os
import re
import select
import stat
import struct
import termios
import time

VT_GETSTATE = 0x5603
MAX_CONFIRM_BYTES = 512
MAX_CONSENT_SECONDS = 60.0
_CONSOLE_RE = re.compile(r"/dev/tty([1-9]|[1-5][0-9]|6[0-3])\Z")
_CHALLENGE_RE = re.compile(r"ERASE /dev/disk/by-id/[A-Za-z0-9_.:+-]+\Z")
_FLAGS = os.O_RDWR | os.O_NOCTTY | os.O_NOFOLLOW | os.O_CLOEXEC


class Refused(ValueError):
    pass


def validate_console(fd: int, console: str) -> None:
    """Reject pseudo-terminals, SSH and inactive/not-foreground VTs.

    A root process running outside the selected virtual console cannot
    authorize by opening the console's device file remotely.
    """
    if os.geteuid() != 0:
        raise Refused("Virtual-console authorization requires root")
    match = _CONSOLE_RE.fullmatch(console) if isinstance(console, str) else None
    if match is None:
        raise Refused("Only an explicit Linux /dev/tty1..63 is accepted")
    try:
        node = os.fstat(fd)
        pathname = os.lstat(console)
        if (not stat.S_ISCHR(node.st_mode)
                or not stat.S_ISCHR(pathname.st_mode)
                or (node.st_dev, node.st_ino) != (pathname.st_dev, pathname.st_ino)
                or os.major(node.st_rdev) != 4
                or os.minor(node.st_rdev) != int(match.group(1))):
            raise Refused("TTY device identity changed or is not a virtual console")
        # Linux VT_GETSTATE: struct vt_stat { ushort active, signal, state; }
        raw = fcntl.ioctl(fd, VT_GETSTATE, bytes(6))
        active, _, _ = struct.unpack("=HHH", raw)
        if active != int(match.group(1)):
            raise Refused("Requested local virtual console is not active")
        if os.tcgetpgrp(fd) != os.getpgrp():
            raise Refused("Process is not the console's foreground job")
    except (OSError, ValueError, struct.error) as exc:
        if isinstance(exc, Refused):
            raise
        raise Refused("Cannot prove active foreground virtual console") from exc


def request_local_consent(challenge: str, console: str, *,
                          timeout: float = MAX_CONSENT_SECONDS) -> str:
    """Collect the exact response from an active root foreground VT.

    This reads only an explicit local kernel virtual console. The
    question is NOT secret; disable echo to avoid stray output.
    Neither confirmation nor errors are logged to stdout/stderr.
    """
    if (not isinstance(challenge, str)
            or not _CHALLENGE_RE.fullmatch(challenge)
            or len(challenge.encode("utf-8")) > MAX_CONFIRM_BYTES
            or not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not 0 < timeout <= MAX_CONSENT_SECONDS):
        raise Refused("Invalid virtual-console consent request")
    if _CONSOLE_RE.fullmatch(console) is None:
        raise Refused("Only explicit local virtual consoles are supported")
    if os.geteuid() != 0:
        raise Refused("Virtual-console authorization requires root")
    fd = os.open(console, _FLAGS)
    try:
        validate_console(fd, console)
        original = termios.tcgetattr(fd)
        updated = original.copy()
        updated[3] &= ~termios.ECHO
        response = bytearray()
        try:
            termios.tcsetattr(fd, termios.TCSAFLUSH, updated)
            question = (
                "\r\neduardOS FORGE - READ-ONLY disk review\r\n"
                "This does not erase, format or install anything.\r\n"
                "Type the full disk challenge to authorize one preflight:\r\n"
                + challenge + "\r\n> "
            )
            encoded = question.encode("ascii", "strict")
            if os.write(fd, encoded) != len(encoded):
                raise Refused("Cannot display local disk review challenge")
            deadline = time.monotonic() + float(timeout)
            while True:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([fd], [], [], left)[0]:
                    raise Refused("Local console confirmation timed out")
                char = os.read(fd, 1)
                if not char:
                    raise Refused("Local console disconnected")
                if char in (b"\n", b"\r"):
                    break
                if len(response) >= MAX_CONFIRM_BYTES:
                    raise Refused("Console confirmation is too long")
                response.extend(char)
            try:
                text = response.decode("ascii", "strict")
            except UnicodeError:
                raise Refused("Console confirmation is not ASCII") from None
            # The console might have switched during typing; fail closed.
            validate_console(fd, console)
            return text
        finally:
            for index in range(len(response)):
                response[index] = 0
            termios.tcsetattr(fd, termios.TCSAFLUSH, original)
            # Do not emit response or disk identity on stdout/stderr.
            os.write(fd, b"\r\n")
    finally:
        os.close(fd)
