"""Dual-mode launch helpers: console detection, detach, detached GUI spawn.

Windows console rules used here:

- ``GetConsoleProcessList`` returns the number of processes attached to this
  console. ``1`` means this process owns the console (double-click / Win+R),
  ``>= 2`` means it is shared with a terminal, ``0`` means there is none.
- ``FreeConsole`` detaches this process so an owned console window disappears.
- ``DETACHED_PROCESS`` spawns a child with no console of its own, so the GUI
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


def gui_relaunch_argv() -> list[str]:
    """Arguments (without the interpreter) that reopen the GUI in a new process.

    Used both to spawn the detached GUI and for elevated relaunches
    (:func:`cli.admin.relaunch_elevated` prepends ``sys.executable`` itself).
    """

    if getattr(sys, "frozen", False):
        return [GUI_INTERNAL]
    return [str(_ENTRY_POINT), GUI_INTERNAL]


def owns_console() -> bool:
    """True when this process is the only one attached to its console."""

    if os.name != "nt":
        return False
    try:
        import ctypes

        count = ctypes.windll.kernel32.GetConsoleProcessList(None, 0)
        return count == 1
    except Exception:
        return False


def detach_console() -> bool:
    """Detach this process from its console so the window disappears."""

    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.FreeConsole())
    except Exception:
        return False


def launch_detached_gui() -> bool:
    """Spawn the GUI as a detached process with no console of its own."""

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
