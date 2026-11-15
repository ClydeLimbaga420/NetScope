from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

import config
from cli import exit_codes
from cli.colors import Colorizer
from cli.commands import cmd_install, cmd_uninstall
from cli.context import CliContext
from cli.installer import InstallResult, install, uninstall
from cli.parser import apply_defaults, build_parser
from core.probes import FakeProbe
from core.runner import FakeRunner


class MemoryRegistry:
    def __init__(self, path: str = "") -> None:
        self.path = path
        self.app_paths: dict[str, str] = {}
        self.broadcasts = 0

    def _entries(self) -> list[str]:
        return [part for part in self.path.split(";") if part]

    def add_to_user_path(self, directory: str) -> bool:
        entries = self._entries()
        normalized = os.path.normcase(os.path.normpath(directory))
        if any(os.path.normcase(os.path.normpath(entry)) == normalized for entry in entries):
            return False
        entries.append(directory)
        self.path = ";".join(entries)
        return True

    def remove_from_user_path(self, directory: str) -> bool:
        entries = self._entries()
        normalized = os.path.normcase(os.path.normpath(directory))
        kept = [
            entry
            for entry in entries
            if os.path.normcase(os.path.normpath(entry)) != normalized
        ]
        if len(kept) == len(entries):
            return False
        self.path = ";".join(kept)
        return True

    def set_app_path(self, exe_name: str, target: str) -> None:
        self.app_paths[exe_name] = target

    def remove_app_path(self, exe_name: str) -> bool:
        return self.app_paths.pop(exe_name, None) is not None

    def broadcast_environment_change(self) -> None:
        self.broadcasts += 1


class RecordingLogger:
    session_id = "installer-test"

    def __getattr__(self, name: str):
        def record(*args, **kwargs) -> None:
            return None

        return record


def make_ctx(*, stdout: io.StringIO | None = None) -> CliContext:
    return CliContext(
        logger=RecordingLogger(),
        runner=FakeRunner(default=(0, "", "")),
        ps=None,
        probe=FakeProbe(),
        color=Colorizer(False),
        stdin=io.StringIO(),
        stdout=stdout or io.StringIO(),
        stderr=io.StringIO(),
    )


def make_source(tmp_path: Path) -> Path:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "NetScope.exe"
    source.write_bytes(b"MZ fake exe")
    return source


def shortcut_writer(monkeypatch):
    def write(shortcut: Path, target: Path) -> None:
        shortcut.write_text(f"shortcut -> {target}", encoding="utf-8")

    monkeypatch.setattr("cli.installer.create_shortcut", write)


def test_install_copies_exe_and_registers(monkeypatch, tmp_path):
    shortcut_writer(monkeypatch)
    source = make_source(tmp_path)
    install_dir = tmp_path / "install"
    start_menu = tmp_path / "start"
    registry = MemoryRegistry(path=r"C:\Windows\System32")

    result = install(
        source_exe=source,
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )

    target = install_dir / "NetScope.exe"
    assert result.ok
    assert target.read_bytes() == b"MZ fake exe"
    assert (install_dir / ".netscope-install").is_file()
    assert (start_menu / "NetScope.lnk").is_file()
    assert registry.app_paths["NetScope.exe"] == str(target)
    assert result.path_changed
    assert str(install_dir) in registry.path.split(";")
    assert registry.broadcasts == 1


def test_install_is_idempotent_for_path(monkeypatch, tmp_path):
    shortcut_writer(monkeypatch)
    source = make_source(tmp_path)
    install_dir = tmp_path / "install"
    start_menu = tmp_path / "start"
    registry = MemoryRegistry()

    first = install(
        source_exe=source,
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )
    second = install(
        source_exe=source,
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )

    assert first.path_changed
    assert not second.path_changed
    assert registry.path.split(";").count(str(install_dir)) == 1


def test_install_dry_run_changes_nothing(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr("cli.installer.create_shortcut", lambda *_args: called.append(True))
    source = make_source(tmp_path)
    install_dir = tmp_path / "install"
    registry = MemoryRegistry()

    result = install(
        source_exe=source,
        install_dir=install_dir,
        start_menu_dir=tmp_path / "start",
        registry=registry,
        dry_run=True,
    )

    assert result.dry_run
    assert not install_dir.exists()
    assert registry.path == ""
    assert registry.app_paths == {}
    assert called == []
    assert any("Would copy" in message for message in result.messages)


def test_uninstall_removes_everything_it_installed(monkeypatch, tmp_path):
    shortcut_writer(monkeypatch)
    source = make_source(tmp_path)
    install_dir = tmp_path / "install"
    start_menu = tmp_path / "start"
    registry = MemoryRegistry(path=r"C:\Windows\System32")

    install(
        source_exe=source,
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )
    result = uninstall(
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )

    assert result.ok
    assert not install_dir.exists()
    assert not (start_menu / "NetScope.lnk").exists()
    assert "NetScope.exe" not in registry.app_paths
    assert str(install_dir) not in registry.path.split(";")
    assert registry.broadcasts == 2


def test_uninstall_keeps_foreign_files(monkeypatch, tmp_path):
    shortcut_writer(monkeypatch)
    source = make_source(tmp_path)
    install_dir = tmp_path / "install"
    start_menu = tmp_path / "start"
    registry = MemoryRegistry()

    install(
        source_exe=source,
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )
    foreign = install_dir / "notes.txt"
    foreign.write_text("keep me", encoding="utf-8")

    result = uninstall(
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )

    assert install_dir.is_dir()
    assert foreign.read_text(encoding="utf-8") == "keep me"
    assert not (install_dir / "NetScope.exe").exists()
    assert any("still contains files" in message for message in result.messages)


def test_uninstall_leaves_unrelated_directory_untouched(tmp_path):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    unrelated = install_dir / "user-data.txt"
    unrelated.write_text("do not delete", encoding="utf-8")
    registry = MemoryRegistry()

    result = uninstall(
        install_dir=install_dir,
        start_menu_dir=tmp_path / "start",
        registry=registry,
    )

    assert unrelated.exists()
    assert any("does not look like a NetScope install" in message for message in result.messages)


def test_uninstall_purge_removes_user_data(monkeypatch, tmp_path):
    shortcut_writer(monkeypatch)
    source = make_source(tmp_path)
    install_dir = tmp_path / "install"
    start_menu = tmp_path / "start"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "netscope.log").write_text("log", encoding="utf-8")
    monkeypatch.setattr(config, "data_dir", lambda: data_dir)
    registry = MemoryRegistry()

    install(
        source_exe=source,
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )
    result = uninstall(
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
        purge=True,
    )

    assert not data_dir.exists()
    assert str(data_dir) in result.removed


def test_uninstall_dry_run_changes_nothing(monkeypatch, tmp_path):
    shortcut_writer(monkeypatch)
    source = make_source(tmp_path)
    install_dir = tmp_path / "install"
    start_menu = tmp_path / "start"
    registry = MemoryRegistry()

    install(
        source_exe=source,
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
    )
    result = uninstall(
        install_dir=install_dir,
        start_menu_dir=start_menu,
        registry=registry,
        dry_run=True,
    )

    assert result.dry_run
    assert (install_dir / "NetScope.exe").exists()
    assert (start_menu / "NetScope.lnk").exists()
    assert registry.app_paths["NetScope.exe"]


def test_install_non_tty_requires_yes(monkeypatch):
    called = []
    monkeypatch.setattr("cli.installer.install", lambda **kwargs: called.append(kwargs))
    args = apply_defaults(build_parser().parse_args(["install"]))
    ctx = make_ctx()

    assert cmd_install(args, ctx) == exit_codes.USAGE
    assert called == []
    assert "rerun with --yes" in ctx.stderr.getvalue()


def test_install_yes_calls_installer(monkeypatch):
    seen = {}

    def fake_install(**kwargs):
        seen.update(kwargs)
        return InstallResult(action="install", install_dir="C:/x", target_exe="C:/x/NetScope.exe")

    monkeypatch.setattr("cli.installer.install", fake_install)
    args = apply_defaults(
        build_parser().parse_args(["install", "--yes", "--source", "C:/src/NetScope.exe"])
    )
    ctx = make_ctx()

    assert cmd_install(args, ctx) == exit_codes.OK
    assert seen["source_exe"] == Path("C:/src/NetScope.exe")
    assert seen["dry_run"] is False


def test_uninstall_yes_json_calls_uninstaller(monkeypatch):
    seen = {}

    def fake_uninstall(**kwargs):
        seen.update(kwargs)
        return InstallResult(action="uninstall", install_dir="C:/x", target_exe="C:/x/NetScope.exe")

    monkeypatch.setattr("cli.installer.uninstall", fake_uninstall)
    out = io.StringIO()
    args = apply_defaults(build_parser().parse_args(["uninstall", "--yes", "--purge", "--json"]))
    ctx = make_ctx(stdout=out)

    assert cmd_uninstall(args, ctx) == exit_codes.OK
    assert seen["purge"] is True
    assert json.loads(out.getvalue())["action"] == "uninstall"


def test_install_dry_run_does_not_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "cli.installer.install",
        lambda **kwargs: seen.update(kwargs) or InstallResult(action="install", dry_run=True),
    )
    args = apply_defaults(build_parser().parse_args(["install", "--dry-run"]))
    ctx = make_ctx()

    assert cmd_install(args, ctx) == exit_codes.OK
    assert seen["dry_run"] is True


def test_installer_error_returns_failure(monkeypatch):
    from cli.installer import InstallerError

    def fail(**kwargs):
        raise InstallerError("no exe")

    monkeypatch.setattr("cli.installer.install", fail)
    args = apply_defaults(build_parser().parse_args(["install", "--yes"]))
    ctx = make_ctx()

    assert cmd_install(args, ctx) == exit_codes.FAILURES
    assert "no exe" in ctx.stderr.getvalue()
