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

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

GUI_INTERNAL = "__gui__"
STOP_ALL_INTERNAL = "__stop_all__"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENTRY_POINT = _PROJECT_ROOT / "netscope.py"

# Extended window styles used to keep the transient console off the taskbar.
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_TH32CS_SNAPPROCESS = 0x00000002
_STD_INPUT_HANDLE = -10
_STD_OUTPUT_HANDLE = -11
_STD_ERROR_HANDLE = -12
_FILE_TYPE_DISK = 0x0001
_FILE_TYPE_PIPE = 0x0003
_ATTACH_PARENT_PROCESS = 0xFFFFFFFF


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _ancestor_process_ids(pid: int | None = None) -> list[int]:
    """Return parent process IDs, nearest first, without requiring a console."""

    if os.name != "nt":
        return []
    try:
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == -1:
            return []
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        parents: dict[int, int] = {}
        kernel32.Process32FirstW.argtypes = (
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(_ProcessEntry32W),
        )
        kernel32.Process32FirstW.restype = ctypes.wintypes.BOOL
        kernel32.Process32NextW.argtypes = kernel32.Process32FirstW.argtypes
        kernel32.Process32NextW.restype = ctypes.wintypes.BOOL
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        kernel32.CloseHandle(snapshot)
    except Exception:
        return []

    ancestors: list[int] = []
    seen: set[int] = set()
    current = pid if pid is not None else os.getpid()
    while True:
        parent = parents.get(current)
        if parent is None or parent == 0 or parent in seen:
            break
        ancestors.append(parent)
        seen.add(parent)
        current = parent
    return ancestors


def _console_stream_needs_rebind(stream: Any, std_handle: int) -> bool:
    if stream is None:
        return True
    try:
        if stream.isatty():
            return False
    except Exception:
        pass
    try:
        import ctypes
        import ctypes.wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.argtypes = (ctypes.wintypes.DWORD,)
        kernel32.GetStdHandle.restype = ctypes.wintypes.HANDLE
        handle = kernel32.GetStdHandle(std_handle)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return True
        kernel32.GetConsoleMode.argtypes = (
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        )
        kernel32.GetConsoleMode.restype = ctypes.wintypes.BOOL
        mode = ctypes.wintypes.DWORD()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return True
        kernel32.GetFileType.argtypes = (ctypes.wintypes.HANDLE,)
        kernel32.GetFileType.restype = ctypes.wintypes.DWORD
        return kernel32.GetFileType(handle) not in (_FILE_TYPE_DISK, _FILE_TYPE_PIPE)
    except Exception:
        return False


def _rebind_console_streams() -> None:
    """Reconnect Python's streams after attaching a windowed build to a console."""

    if _console_stream_needs_rebind(sys.stdout, _STD_OUTPUT_HANDLE):
        try:
            encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
            sys.stdout = open(
                "CONOUT$", "w", encoding=encoding, errors="replace", buffering=1
            )
        except Exception:
            pass
    if _console_stream_needs_rebind(sys.stderr, _STD_ERROR_HANDLE):
        try:
            encoding = getattr(sys.stderr, "encoding", None) or "utf-8"
            sys.stderr = open(
                "CONOUT$", "w", encoding=encoding, errors="replace", buffering=1
            )
        except Exception:
            pass


def ensure_console_input() -> bool:
    """Reconnect stdin to the attached console without overriding redirection."""

    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return False
        file_type = kernel32.GetFileType(handle)
        if file_type in (_FILE_TYPE_DISK, _FILE_TYPE_PIPE):
            return False
        encoding = getattr(sys.stdin, "encoding", None) or "utf-8"
        sys.stdin = open("CONIN$", "r", encoding=encoding, errors="replace")
        return True
    except Exception:
        return False


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
        attached = bool(attach(_ATTACH_PARENT_PROCESS))
        if not attached:
            for pid in _ancestor_process_ids():
                if bool(attach(pid)):
                    attached = True
                    break
        if not attached:
            return bool(kernel32.GetConsoleWindow())
        _rebind_console_streams()
        return True
    except Exception:
        return False


def gui_relaunch_argv(
    replace: bool = False,
    no_browser: bool = False,
    data_dir: str | None = None,
) -> list[str]:
    """Arguments (without the interpreter) that reopen the UI in a new process.

    Used both to spawn the detached UI and for elevated relaunches
    (:func:`cli.admin.relaunch_elevated` prepends ``sys.executable`` itself).
    ``data_dir`` is passed for elevation because UAC may switch to a different
    account with a different ``%LOCALAPPDATA%``.
    """

    if getattr(sys, "frozen", False):
        argv = [GUI_INTERNAL]
    else:
        argv = [str(_ENTRY_POINT), GUI_INTERNAL]
    if data_dir:
        argv.extend(["--data-dir", str(data_dir)])
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
