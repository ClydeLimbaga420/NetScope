"""Admin/elevation helpers used by the CLI and later the fix flow."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def is_admin() -> bool:
    """Return True when the current process is elevated."""

    if os.name == "nt":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:
        return False


def format_admin_command(argv: Sequence[str]) -> str:
    return subprocess.list2cmdline([sys.executable, *argv])


def relaunch_elevated(argv: Sequence[str], *, windowless: bool = False) -> bool:
    """Ask Windows for an elevated relaunch. Returns False if the user cancels."""

    if os.name != "nt":
        return False
    try:
        import ctypes

        executable = sys.executable
        show_command = 1
        if windowless:
            interpreter = Path(executable)
            if interpreter.name.lower() == "python.exe":
                pythonw = interpreter.with_name("pythonw.exe")
                if pythonw.is_file():
                    executable = str(pythonw)
            show_command = 0
        params = subprocess.list2cmdline([*argv])
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            None,
            show_command,
        )
        return int(result) > 32
    except Exception:
        return False


def admin_guidance(argv: Sequence[str]) -> str:
    return (
        "This action needs administrator privileges. Either relaunch NetScope "
        "elevated or run this command from an elevated terminal:\n  "
        + format_admin_command(argv)
    )
