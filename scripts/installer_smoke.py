"""Install, launch and uninstall the NetScope installer in a disposable profile.

Usage:
    python scripts/installer_smoke.py --installer dist/installer/NetScope-Setup.exe

The script is intended for CI or a throwaway Windows profile. It installs
silently, checks the shortcut, App Paths, PATH and ``--version`` output, then
runs the uninstaller and confirms the app and default user data are gone.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import winreg
from pathlib import Path

APP_EXE = "NetScope.exe"
START_MENU_LNK = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "NetScope.lnk"
APP_PATHS_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths\NetScope.exe"


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _ok(message: str) -> None:
    print(f"ok: {message}")


def _run(argv: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _read_user_path() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return str(value)
    except OSError:
        return ""


def _path_contains(directory: Path) -> bool:
    target = os.path.normcase(os.path.normpath(str(directory)))
    for entry in _read_user_path().split(";"):
        if entry.strip() and os.path.normcase(os.path.normpath(entry.strip())) == target:
            return True
    return False


def _app_paths_exists() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_PATHS_SUBKEY):
            return True
    except OSError:
        return False


def _wait_until(predicate, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return bool(predicate())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--installer",
        type=Path,
        default=Path("dist/installer/NetScope-Setup.exe"),
    )
    parser.add_argument(
        "--install-dir",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "NetScope",
    )
    args = parser.parse_args(argv)

    installer = args.installer.resolve()
    install_dir = args.install_dir.resolve()
    exe = install_dir / APP_EXE
    bin_dir = install_dir / "bin"
    shim = bin_dir / "netscope.cmd"
    data_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "NetScope"

    if not installer.is_file():
        _fail(f"installer not found: {installer}")

    install = _run(
        [
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            f"/DIR={install_dir}",
        ]
    )
    if install.returncode != 0:
        _fail(f"installer exited {install.returncode}: {install.stderr or install.stdout}")
    if not exe.is_file():
        _fail(f"{exe} was not installed")
    _ok("installer copied NetScope.exe")

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "installer-smoke-marker.txt").write_text("remove me", encoding="utf-8")

    if not START_MENU_LNK.is_file():
        _fail(f"Start Menu shortcut missing: {START_MENU_LNK}")
    _ok("Start Menu shortcut exists")

    if not _app_paths_exists():
        _fail("App Paths registration missing")
    _ok("App Paths registration exists")

    if not shim.is_file():
        _fail(f"CLI shim missing: {shim}")
    _ok("CLI shim was installed")
    if not _path_contains(bin_dir):
        _fail(f"user PATH does not contain {bin_dir}")
    _ok("user PATH contains the CLI shim directory")

    version = _run([str(shim), "--version"])
    if version.returncode != 0 or not version.stdout.strip().startswith("NetScope "):
        _fail(f"{shim} --version failed: {version.stdout!r} {version.stderr!r}")
    _ok(f"version check via shim: {version.stdout.strip()}")

    uninstaller = install_dir / "unins000.exe"
    if not uninstaller.is_file():
        _fail(f"uninstaller missing: {uninstaller}")
    uninstall = _run(
        [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    )
    if uninstall.returncode != 0:
        _fail(f"uninstaller exited {uninstall.returncode}: {uninstall.stderr or uninstall.stdout}")

    if not _wait_until(lambda: not exe.exists()):
        _fail(f"install directory still contains {exe}")
    if not _wait_until(lambda: not START_MENU_LNK.exists()):
        _fail(f"Start Menu shortcut still exists: {START_MENU_LNK}")
    if not _wait_until(lambda: not _app_paths_exists()):
        _fail("App Paths registration still exists")
    if not _wait_until(lambda: not shim.exists()):
        _fail(f"CLI shim still exists: {shim}")
    if not _wait_until(lambda: not _path_contains(bin_dir)):
        _fail(f"user PATH still contains {bin_dir}")
    if not _wait_until(lambda: not data_dir.exists()):
        _fail(f"user data was not removed: {data_dir}")
    _ok("uninstaller removed app, shortcut, App Paths, PATH entry and user data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
