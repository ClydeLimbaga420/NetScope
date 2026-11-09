"""ANSI colour and status symbols with safe fallbacks."""

from __future__ import annotations

import os
import sys
from typing import TextIO

from core.models import CheckResult, Status

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"

STATUS_COLORS = {
    Status.PASS: GREEN,
    Status.WARN: YELLOW,
    Status.FAIL: RED,
    Status.SKIP: DIM,
    Status.ERROR: MAGENTA,
}

STATUS_SYMBOLS = {
    Status.PASS: "+",
    Status.WARN: "!",
    Status.FAIL: "x",
    Status.SKIP: "-",
    Status.ERROR: "?",
}


def enable_virtual_terminal() -> bool:
    """Enable ANSI processing on Windows consoles (best effort)."""

    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):  # stdout, stderr
            handle = kernel32.GetStdHandle(handle_id)
            if handle in (0, -1):
                continue
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:
        return False


def color_supported(stream: TextIO | None = None, *, no_color: bool = False, json_mode: bool = False) -> bool:
    if no_color or json_mode:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    target = stream or sys.stdout
    try:
        if not target.isatty():
            return False
    except Exception:
        return False
    return enable_virtual_terminal()


class Colorizer:
    def __init__(self, enabled: bool, stream: TextIO | None = None):
        self.enabled = enabled
        self.stream = stream

    def paint(self, text: str, color: str | None = None, *, bold: bool = False) -> str:
        if not self.enabled:
            return text
        prefix = (BOLD if bold else "") + (color or "")
        return f"{prefix}{text}{RESET}"

    def status_symbol(self, status: Status) -> str:
        symbol = STATUS_SYMBOLS.get(status, "?")
        return self.paint(symbol, STATUS_COLORS.get(status))

    def status_word(self, status: Status) -> str:
        return self.paint(status.value.upper(), STATUS_COLORS.get(status), bold=status is Status.FAIL)

    def reset(self) -> None:
        if self.enabled and self.stream is not None:
            try:
                self.stream.write(RESET)
                self.stream.flush()
            except Exception:
                pass


def result_line(result: CheckResult, color: Colorizer) -> str:
    return (
        f"{color.status_symbol(result.status)} "
        f"{color.paint(result.id, CYAN)} "
        f"{result.title} - {result.message}"
    )
