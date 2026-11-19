"""Discovery and termination of NetScope-owned processes.

Used when a front end exits and when an installer removes a running copy. Only
processes owned by the current user are considered, and WebView2/browser
processes are only killed when they are descendants of a NetScope process.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Iterable

import psutil

_PROCESS_MARKERS = (
    "__gui__",
    "__stop_all__",
    "netscope.py",
    "-m cli",
    "--handoff-url",
)
_EXCLUDED_NAMES = frozenset({"msedgewebview2.exe", "msedge.exe", "chrome.exe"})

# Children that must outlive the launching CLI (notably the detached web UI).
PERSISTENT_CHILD_PIDS: set[int] = set()


def current_username() -> str | None:
    try:
        return psutil.Process(os.getpid()).username()
    except (psutil.Error, OSError):
        return None


def _info(proc: Any, name: str, default: Any = None) -> Any:
    info = getattr(proc, "info", None)
    if isinstance(info, dict) and name in info:
        return info[name]
    try:
        return getattr(info, name)
    except (AttributeError, TypeError):
        return default


def is_netscope_process(proc: Any, *, install_dirs: Iterable[Path] | None = None) -> bool:
    """Return True when ``proc`` belongs to this NetScope installation."""

    try:
        exe = proc.exe() or ""
        cmdline = " ".join(proc.cmdline() or [])
    except (psutil.Error, OSError, TypeError):
        return False
    name = Path(exe).name.lower()
    if name in _EXCLUDED_NAMES:
        return False
    lowered = cmdline.lower()
    if name == "netscope.exe":
        if install_dirs is None:
            return True
        try:
            resolved = Path(exe).resolve()
        except OSError:
            resolved = Path(exe)
        for directory in install_dirs:
            try:
                resolved.relative_to(Path(directory).resolve())
                return True
            except (ValueError, OSError):
                continue
    return any(marker in lowered for marker in _PROCESS_MARKERS)


def netscope_processes(
    *,
    install_dirs: Iterable[Path] | None = None,
    exclude_pids: Iterable[int] = (),
) -> list[psutil.Process]:
    """Return other NetScope processes belonging to the current user."""

    excluded = {int(pid) for pid in exclude_pids}
    excluded.add(os.getpid())
    username = current_username()
    found: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "username"]):
        try:
            pid = int(proc.pid)
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
        if pid in excluded:
            continue
        owner = _info(proc, "username")
        if username and owner and owner != username:
            continue
        if is_netscope_process(proc, install_dirs=install_dirs):
            found.append(proc)
    return found


def is_pid_netscope(
    pid: int, *, install_dirs: Iterable[Path] | None = None
) -> bool:
    try:
        return is_netscope_process(psutil.Process(int(pid)), install_dirs=install_dirs)
    except (psutil.Error, OSError, ValueError):
        return False


def descendant_processes(
    root_pid: int, *, exclude_pids: Iterable[int] = ()
) -> list[psutil.Process]:
    """Return the live descendants of ``root_pid`` (deepest first)."""

    excluded = {int(pid) for pid in exclude_pids}
    try:
        children = psutil.Process(int(root_pid)).children(recursive=True)
    except (psutil.Error, OSError, ValueError):
        return []
    result: list[psutil.Process] = []
    for child in reversed(children):
        try:
            if int(child.pid) not in excluded:
                result.append(child)
        except (psutil.Error, OSError, ValueError):
            continue
    return result


def terminate_processes(processes: Iterable[psutil.Process], *, grace: float = 2.0) -> int:
    """Terminate processes, escalating to kill. Returns the number signalled."""

    targets = list(processes)
    if not targets:
        return 0
    signalled: set[int] = set()
    for proc in targets:
        try:
            proc.terminate()
            signalled.add(int(proc.pid))
        except (psutil.Error, OSError, ValueError):
            continue
    if not signalled:
        return 0
    _, alive = psutil.wait_procs(targets, timeout=grace)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.Error, OSError, ValueError):
            continue
    return len(signalled)


def terminate_tree(
    root_pid: int,
    *,
    grace: float = 2.0,
    exclude_pids: Iterable[int] = (),
) -> int:
    """Terminate the descendants of ``root_pid`` and then the root itself."""

    excluded = {int(pid) for pid in exclude_pids}
    descendants = descendant_processes(root_pid, exclude_pids=excluded)
    count = terminate_processes(descendants, grace=grace)
    if int(root_pid) in excluded or int(root_pid) == os.getpid():
        return count
    try:
        root = psutil.Process(int(root_pid))
    except (psutil.Error, OSError, ValueError):
        return count
    return count + terminate_processes([root], grace=grace)


def terminate_children_of_current_process(
    *, grace: float = 2.0, exclude_pids: Iterable[int] = ()
) -> int:
    """Kill every descendant of this process except the listed PIDs."""

    return terminate_tree(os.getpid(), grace=grace, exclude_pids=exclude_pids)


def terminate_netscope_processes(
    *,
    install_dirs: Iterable[Path] | None = None,
    grace: float = 2.0,
    exclude_pids: Iterable[int] = (),
) -> int:
    """Kill other NetScope processes (not browser/WebView2 helpers by name)."""

    return terminate_processes(
        netscope_processes(install_dirs=install_dirs, exclude_pids=exclude_pids),
        grace=grace,
    )


def wait_for_exit(pid: int, *, timeout: float = 8.0) -> bool:
    """Wait for a PID to disappear; return True if it is gone."""

    deadline = time.monotonic() + timeout
    while True:
        if not psutil.pid_exists(int(pid)):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
