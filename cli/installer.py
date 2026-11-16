"""Per-user installer and uninstaller for the NetScope executable.

Install layout (no administrator rights, no system-wide changes):

- ``%LOCALAPPDATA%\\Programs\\NetScope\\NetScope.exe``
- ``HKCU\\Environment\\Path`` gains the install directory
- ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\NetScope.exe``
- ``%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\NetScope.lnk``

Uninstall removes exactly those changes. User data (logs, reports, backups) is
kept unless ``purge=True``.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import config

APP_EXE_NAME = "NetScope.exe"
MARKER_NAME = ".netscope-install"
INNO_MARKER_NAME = ".netscope-inno"
APP_PATHS_KEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
USER_ENV_KEY = r"Environment"


class InstallerError(RuntimeError):
    """Raised when an install/uninstall request cannot be completed safely."""


class Registry(Protocol):
    def add_to_user_path(self, directory: str) -> bool: ...

    def remove_from_user_path(self, directory: str) -> bool: ...

    def set_app_path(self, exe_name: str, target: str) -> None: ...

    def remove_app_path(self, exe_name: str) -> bool: ...

    def broadcast_environment_change(self) -> None: ...


@dataclass
class InstallResult:
    action: str
    ok: bool = True
    dry_run: bool = False
    install_dir: str = ""
    target_exe: str = ""
    shortcut: str = ""
    path_changed: bool = False
    app_path_changed: bool = False
    removed: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "ok": self.ok,
            "dry_run": self.dry_run,
            "install_dir": self.install_dir,
            "target_exe": self.target_exe,
            "shortcut": self.shortcut,
            "path_changed": self.path_changed,
            "app_path_changed": self.app_path_changed,
            "removed": list(self.removed),
            "messages": list(self.messages),
        }


def default_install_dir() -> Path:
    if os.name == "nt":
        return config.local_app_data() / "Programs" / config.APP_NAME
    return config.local_app_data() / "Programs" / config.APP_NAME


def default_start_menu_dir() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return config.local_app_data() / "Start Menu" / "Programs"


def find_source_exe() -> Path:
    """Locate the executable to install.

    Frozen builds install themselves. Source checkouts look for a previously
    built ``dist/NetScope.exe`` (or ``NETSCOPE_EXE``); installing a Python
    script would not create a working Start Menu entry on its own.
    """

    override = os.environ.get("NETSCOPE_EXE")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        raise InstallerError(f"NETSCOPE_EXE does not point to a file: {candidate}")

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        if executable.is_file():
            return executable.resolve()

    project_root = Path(__file__).resolve().parents[1]
    for candidate in (project_root / "dist" / APP_EXE_NAME, project_root / "build" / "dist" / APP_EXE_NAME):
        if candidate.is_file():
            return candidate.resolve()

    raise InstallerError(
        "No NetScope.exe found. Build it first (scripts\\build.ps1) or pass --source PATH."
    )


class WindowsRegistry:
    """Minimal HKCU registry access with raw (unexpanded) PATH handling."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise InstallerError("registry installation is only supported on Windows")
        import winreg

        self._winreg = winreg

    def _open_env(self, access: int):
        return self._winreg.OpenKey(
            self._winreg.HKEY_CURRENT_USER, USER_ENV_KEY, 0, access
        )

    def _read_user_path(self) -> tuple[str, int]:
        winreg = self._winreg
        try:
            with self._open_env(winreg.KEY_READ) as key:
                value, kind = winreg.QueryValueEx(key, "Path")
                return str(value), int(kind)
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ

    def _write_user_path(self, value: str, kind: int) -> None:
        winreg = self._winreg
        with self._open_env(winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, kind, value)

    @staticmethod
    def _entries(value: str) -> list[str]:
        return [part for part in value.split(";") if part.strip()]

    def add_to_user_path(self, directory: str) -> bool:
        value, kind = self._read_user_path()
        entries = self._entries(value)
        normalized = os.path.normcase(os.path.normpath(directory))
        if any(os.path.normcase(os.path.normpath(entry)) == normalized for entry in entries):
            return False
        entries.append(directory)
        self._write_user_path(";".join(entries), kind)
        return True

    def remove_from_user_path(self, directory: str) -> bool:
        value, kind = self._read_user_path()
        entries = self._entries(value)
        normalized = os.path.normcase(os.path.normpath(directory))
        kept = [
            entry
            for entry in entries
            if os.path.normcase(os.path.normpath(entry)) != normalized
        ]
        if len(kept) == len(entries):
            return False
        self._write_user_path(";".join(kept), kind)
        return True

    def set_app_path(self, exe_name: str, target: str) -> None:
        winreg = self._winreg
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, rf"{APP_PATHS_KEY}\{exe_name}", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, target)
            winreg.SetValueEx(key, "Path", 0, winreg.REG_SZ, str(Path(target).parent))

    def remove_app_path(self, exe_name: str) -> bool:
        winreg = self._winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{APP_PATHS_KEY}\{exe_name}")
            return True
        except FileNotFoundError:
            return False

    def broadcast_environment_change(self) -> None:
        try:
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            result = ctypes.c_ulong()
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                "Environment",
                SMTO_ABORTIFHUNG,
                5000,
                ctypes.byref(result),
            )
        except Exception:
            pass


def create_shortcut(shortcut: Path, target: Path) -> None:
    """Create a Windows ``.lnk`` using the WScript.Shell COM object.

    The PowerShell text is static; paths are passed as separate argv values.
    """

    if os.name != "nt":
        raise InstallerError("Start Menu shortcuts are only supported on Windows")
    script = (
        "param([string]$ShortcutPath, [string]$TargetPath, [string]$WorkingDirectory)\n"
        "$shell = New-Object -ComObject WScript.Shell\n"
        "$link = $shell.CreateShortcut($ShortcutPath)\n"
        "$link.TargetPath = $TargetPath\n"
        "$link.WorkingDirectory = $WorkingDirectory\n"
        "$link.Description = 'NetScope network troubleshooting'\n"
        "$link.Save()\n"
    )
    from core.logging_config import NullLogger
    from core.runner import SubprocessRunner

    handle = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".ps1", delete=False, encoding="utf-8-sig"
        ) as script_file:
            script_file.write(script)
            handle = Path(script_file.name)
        runner = SubprocessRunner(NullLogger())
        result = runner.run(
            [
                config.POWERSHELL_EXE,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(handle),
                "-ShortcutPath",
                str(shortcut),
                "-TargetPath",
                str(target),
                "-WorkingDirectory",
                str(target.parent),
            ],
            timeout=30,
        )
        if not result.ok:
            raise InstallerError(
                f"could not create Start Menu shortcut: {result.combined or result.returncode}"
            )
    finally:
        if handle is not None:
            handle.unlink(missing_ok=True)


def _write_marker(install_dir: Path, source: Path) -> None:
    marker = install_dir / MARKER_NAME
    marker.write_text(
        f"NetScope {config.APP_VERSION}\ninstalled_from={source}\n", encoding="utf-8"
    )


def _is_our_install(install_dir: Path) -> bool:
    return (install_dir / APP_EXE_NAME).is_file() or (install_dir / MARKER_NAME).is_file()


def _reject_inno_managed(install_dir: Path) -> None:
    if (install_dir / INNO_MARKER_NAME).is_file():
        raise InstallerError(
            "NetScope is managed by the Windows installer. "
            "Use Settings > Apps to uninstall it."
        )


def install(
    *,
    source_exe: Path | None = None,
    install_dir: Path | None = None,
    start_menu_dir: Path | None = None,
    registry: Registry | None = None,
    dry_run: bool = False,
    create_start_menu: bool = True,
) -> InstallResult:
    target_dir = Path(install_dir) if install_dir else default_install_dir()
    target_dir = target_dir.expanduser()
    if not target_dir.is_absolute():
        raise InstallerError("install directory must be an absolute path")
    _reject_inno_managed(target_dir)
    source = Path(source_exe).resolve() if source_exe else find_source_exe()
    if not source.is_file():
        raise InstallerError(f"installer source does not exist: {source}")
    target = target_dir / APP_EXE_NAME
    shortcut = (Path(start_menu_dir) if start_menu_dir else default_start_menu_dir()) / "NetScope.lnk"

    result = InstallResult(
        action="install",
        dry_run=dry_run,
        install_dir=str(target_dir),
        target_exe=str(target),
        shortcut=str(shortcut) if create_start_menu else "",
    )

    if dry_run:
        result.messages.append(f"Would copy {source} to {target}")
        result.messages.append(f"Would add {target_dir} to the user PATH")
        result.messages.append(f"Would register {target} in App Paths")
        if create_start_menu:
            result.messages.append(f"Would create Start Menu shortcut {shortcut}")
        return result

    target_dir.mkdir(parents=True, exist_ok=True)
    if source != target:
        shutil.copy2(source, target)
    _write_marker(target_dir, source)

    active_registry = registry or WindowsRegistry()
    result.path_changed = active_registry.add_to_user_path(str(target_dir))
    active_registry.set_app_path(APP_EXE_NAME, str(target))
    result.app_path_changed = True
    if create_start_menu:
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        create_shortcut(shortcut, target)
    active_registry.broadcast_environment_change()

    result.messages.append(f"Installed NetScope to {target_dir}")
    result.messages.append("Open a new terminal for the PATH change to take effect.")
    return result


def uninstall(
    *,
    install_dir: Path | None = None,
    start_menu_dir: Path | None = None,
    registry: Registry | None = None,
    dry_run: bool = False,
    purge: bool = False,
) -> InstallResult:
    target_dir = Path(install_dir) if install_dir else default_install_dir()
    target_dir = target_dir.expanduser()
    if not target_dir.is_absolute():
        raise InstallerError("install directory must be an absolute path")
    _reject_inno_managed(target_dir)
    target = target_dir / APP_EXE_NAME
    shortcut = (Path(start_menu_dir) if start_menu_dir else default_start_menu_dir()) / "NetScope.lnk"
    data_dir = config.data_dir()

    result = InstallResult(
        action="uninstall",
        dry_run=dry_run,
        install_dir=str(target_dir),
        target_exe=str(target),
        shortcut=str(shortcut),
    )

    if dry_run:
        result.messages.append(f"Would remove {target_dir} from the user PATH")
        result.messages.append("Would remove the App Paths registration")
        result.messages.append(f"Would remove Start Menu shortcut {shortcut}")
        if _is_our_install(target_dir):
            result.messages.append(f"Would remove {target_dir}")
        if purge:
            result.messages.append(f"Would remove user data at {data_dir}")
        return result

    active_registry = registry or WindowsRegistry()
    result.path_changed = active_registry.remove_from_user_path(str(target_dir))
    result.app_path_changed = active_registry.remove_app_path(APP_EXE_NAME)

    if shortcut.is_file():
        shortcut.unlink()
        result.removed.append(str(shortcut))

    if _is_our_install(target_dir):
        for name in (APP_EXE_NAME, MARKER_NAME):
            path = target_dir / name
            if path.is_file():
                path.unlink()
                result.removed.append(str(path))
        try:
            target_dir.rmdir()
            result.removed.append(str(target_dir))
        except OSError:
            result.messages.append(
                f"Kept {target_dir}: it still contains files that were not installed by NetScope."
            )
    else:
        result.messages.append(f"{target_dir} does not look like a NetScope install; left untouched.")

    if purge and data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
        result.removed.append(str(data_dir))

    active_registry.broadcast_environment_change()
    result.messages.append("Uninstalled NetScope. Open a new terminal for the PATH change to take effect.")
    return result
