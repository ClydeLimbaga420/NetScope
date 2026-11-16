"""Console/launch helpers shared by the CLI and the web UI.

Windows console rules used here:

- ``GetConsoleProcessList`` returns the number of processes attached to this
  console. A frozen one-file build has a bootloader parent and child, so its
  owned console has a count of 2; an additional process means it is shared.
- ``ShowWindow(SW_HIDE)`` hides an owned console promptly; ``FreeConsole``
  then detaches this process.
- ``DETACHED_PROCESS`` spawns a child with no console of its own, so the web UI
  never flashes a console window.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

GUI_INTERNAL = "__gui__"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENTRY_POINT = _PROJECT_ROOT / "netscope.py"


def gui_relaunch_argv(replace: bool = False) -> list[str]:
    """Arguments (without the interpreter) that reopen the UI in a new process.

    Used both to spawn the detached UI and for elevated relaunches
    (:func:`cli.admin.relaunch_elevated` prepends ``sys.executable`` itself).
    """

    if getattr(sys, "frozen", False):
        argv = [GUI_INTERNAL]
    else:
        argv = [str(_ENTRY_POINT), GUI_INTERNAL]
    if replace:
        argv.append("--replace")
    return argv


def owns_console() -> bool:
    """True when this process is the only one attached to its console."""

    if os.name != "nt":
        return False
    try:
        import ctypes

        import ctypes.wintypes

        process_ids = (ctypes.wintypes.DWORD * 64)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(process_ids, len(process_ids))
        return count == 1 or (getattr(sys, "frozen", False) and count == 2)
    except Exception:
        return False


def detach_console() -> bool:
    """Hide an owned console window, then detach this process from it."""

    if os.name != "nt":
        return False
    try:
        import ctypes
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32
        get_console_window = kernel32.GetConsoleWindow
        get_console_window.restype = ctypes.wintypes.HWND
        hwnd = get_console_window()
        if hwnd:
            show_window = ctypes.windll.user32.ShowWindow
            show_window.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.INT)
            show_window.restype = ctypes.wintypes.BOOL
            show_window(hwnd, 0)
        free_console = kernel32.FreeConsole
        free_console.restype = ctypes.wintypes.BOOL
        return bool(free_console())
    except Exception:
        return False


def launch_detached_gui() -> bool:
    """Spawn the UI as a detached process with no console of its own."""

    argv = [sys.executable, *gui_relaunch_argv()]
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        popen_kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            cwd=str(_PROJECT_ROOT),
            **popen_kwargs,
        )
        return True
    except Exception:
        return False
