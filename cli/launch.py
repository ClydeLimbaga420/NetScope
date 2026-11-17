"""Console/launch helpers shared by the CLI and the web UI.

Windows console rules used here:

- ``GetConsoleProcessList`` returns the number of processes attached to this
  console. A frozen one-file build has a bootloader parent and child, so its
  owned console has a count of 2; an additional process means it is shared.
- ``ShowWindow(SW_HIDE)`` hides an owned console promptly; ``FreeConsole``
  then detaches this process. Before hiding, the console is marked as a tool
  window (``WS_EX_TOOLWINDOW``) so it has no taskbar button or Alt+Tab entry.
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

# Extended window styles used to keep the transient console off the taskbar.
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000


def attach_parent_console() -> bool:
    """Attach a windowed frozen build to the terminal that launched it.

    The GUI build has no console of its own, so a double-click never creates a
    console window or taskbar button. When the exe is invoked from cmd or
    PowerShell, attaching to the parent console restores CLI output; redirected
    pipes already work and are left untouched.
    """

    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    try:
        import ctypes
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32
        attach = kernel32.AttachConsole
        attach.argtypes = (ctypes.wintypes.DWORD,)
        attach.restype = ctypes.wintypes.BOOL
        if attach(0xFFFFFFFF):  # ATTACH_PARENT_PROCESS
            return True
        return bool(kernel32.GetConsoleWindow())
    except Exception:
        return False


def gui_relaunch_argv(replace: bool = False, no_browser: bool = False) -> list[str]:
    """Arguments (without the interpreter) that reopen the UI in a new process.

    Used both to spawn the detached UI and for elevated relaunches
    (:func:`cli.admin.relaunch_elevated` prepends ``sys.executable`` itself).
    """

    if getattr(sys, "frozen", False):
        argv = [GUI_INTERNAL]
    else:
        argv = [str(_ENTRY_POINT), GUI_INTERNAL]
    if no_browser:
        argv.append("--no-browser")
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


def _hide_console_from_taskbar(user32: Any, hwnd: int) -> None:
    """Best effort: mark the console as a tool window so it has no taskbar button.

    Windows only gives "app" windows a taskbar button / Alt+Tab entry. Setting
    ``WS_EX_TOOLWINDOW`` and clearing ``WS_EX_APPWINDOW`` excludes this
    short-lived console. Any failure is ignored: hiding and detaching still run.
    """

    try:
        import ctypes.wintypes

        get_style = getattr(user32, "GetWindowLongPtrW", None) or getattr(user32, "GetWindowLongW", None)
        set_style = getattr(user32, "SetWindowLongPtrW", None) or getattr(user32, "SetWindowLongW", None)
        if get_style is None or set_style is None:
            return
        long_ptr = ctypes.c_ssize_t
        get_style.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.INT)
        get_style.restype = long_ptr
        set_style.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.INT, long_ptr)
        set_style.restype = long_ptr
        style = get_style(hwnd, _GWL_EXSTYLE)
        updated = (style | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW
        if updated != style:
            set_style(hwnd, _GWL_EXSTYLE, updated)
    except Exception:
        return


def detach_console() -> bool:
    """Hide an owned console window off the taskbar, then detach from it."""

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
            _hide_console_from_taskbar(ctypes.windll.user32, hwnd)
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
