"""Read a secret from the keyboard and echo * for each character.

getpass shows nothing, which makes paste look like it failed. This still
hides the real value, but stars appear so you can see that something landed.
"""

from __future__ import annotations

import getpass
import sys


def _handle_secret_char(chars: list[str], ch: str) -> str | None:
    """Apply one keypress. Returns text to echo, or None when Enter ends input."""
    if ch in ("\r", "\n"):
        return None
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch in ("\x7f", "\b"):
        if chars:
            chars.pop()
            return "\b \b"
        return ""
    if len(ch) != 1 or ord(ch) < 32:
        return ""
    chars.append(ch)
    return "*"


def _read_secret_posix(prompt: str) -> str:
    import termios
    import tty

    sys.stdout.write(prompt)
    sys.stdout.flush()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    chars: list[str] = []
    try:
        tty.setraw(fd)
        while True:
            echoed = _handle_secret_char(chars, sys.stdin.read(1))
            if echoed is None:
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                break
            if echoed:
                sys.stdout.write(echoed)
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return "".join(chars).strip()


def _read_secret_windows(prompt: str) -> str:
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars: list[str] = []
    while True:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue
        echoed = _handle_secret_char(chars, ch)
        if echoed is None:
            sys.stdout.write("\n")
            sys.stdout.flush()
            break
        if echoed:
            sys.stdout.write(echoed)
            sys.stdout.flush()
    return "".join(chars).strip()


def read_secret(prompt: str) -> str:
    """Read a secret, echoing * per character. Falls back to getpass."""
    if not sys.stdin.isatty():
        return getpass.getpass(prompt).strip()
    try:
        if sys.platform == "win32":
            return _read_secret_windows(prompt)
        return _read_secret_posix(prompt)
    except OSError:
        return getpass.getpass(prompt).strip()
