from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from cli import exit_codes
from cli.admin import format_admin_command
from cli.colors import Colorizer
from cli.commands import cmd_gui
from cli.context import CliContext, create_context
from cli.launch import GUI_INTERNAL, gui_relaunch_argv, owns_console
from cli.main import main
from cli.parser import apply_defaults, build_parser
from core.logging_config import NullLogger
from core.probes import FakeProbe
from core.runner import FakeRunner
from fixes.executor import FixExecutor
from web.runtime import build_runtime, runtime_from_context


class RecordingLogger:
    session_id = "launch-test-session"

    def __getattr__(self, name: str):
        def record(*args, **kwargs) -> None:
            return None

        return record


def make_cli_ctx() -> CliContext:
    return CliContext(
        logger=RecordingLogger(),
        runner=FakeRunner(default=(0, "", "")),
        ps=None,
        probe=FakeProbe(),
        color=Colorizer(False),
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )


# -- launch helpers -----------------------------------------------------------


def test_owns_console_returns_bool():
    assert isinstance(owns_console(), bool)


def test_gui_relaunch_argv_targets_internal_token():
    argv = gui_relaunch_argv()
    assert argv
    assert argv[-1] == GUI_INTERNAL
    if not getattr(sys, "frozen", False):
        entry = Path(argv[0])
        assert entry.name == "netscope.py"
        assert entry.exists()


def test_admin_command_quotes_interpreter_and_args():
    command = format_admin_command(["gui", "--no-browser"])
    assert command
    assert "gui" in command


# -- runtime ------------------------------------------------------------------


def test_build_runtime_loads_catalog_and_builds_executor():
    runtime = build_runtime()
    assert runtime.catalog.get("IP-01") is not None
    assert isinstance(runtime.executor(), FixExecutor)


def test_runtime_from_context_reuses_cli_objects():
    ctx = create_context("launch-test", logger=NullLogger())
    runtime = runtime_from_context(ctx)
    assert runtime.runner is ctx.runner
    assert runtime.ps is ctx.ps
    assert runtime.session_id == getattr(ctx.logger, "session_id", "-")
    assert runtime.catalog.get("IP-01") is not None


# -- CLI integration -----------------------------------------------------------


def test_cmd_gui_reports_launch(monkeypatch):
    calls = []
    monkeypatch.setattr("web.run.run_web_ui", lambda **kwargs: calls.append(kwargs) or 0)
    args = apply_defaults(build_parser().parse_args(["gui"]))
    ctx = make_cli_ctx()
    result = cmd_gui(args, ctx)
    assert result == exit_codes.OK, ctx.stderr.getvalue()
    assert calls == [{"port": None, "no_browser": False}]


def test_cmd_gui_failure_is_reported(monkeypatch):
    def fail_to_start(**_kwargs):
        raise RuntimeError("server failed")

    monkeypatch.setattr("web.run.run_web_ui", fail_to_start)
    args = apply_defaults(build_parser().parse_args(["gui"]))
    ctx = make_cli_ctx()
    result = cmd_gui(args, ctx)
    assert result == exit_codes.FAILURES, ctx.stderr.getvalue()
    assert "could not start web UI" in ctx.stderr.getvalue()


def test_cmd_gui_detached_launch_opens_valid_boot_url(monkeypatch):
    url = "http://127.0.0.1:54321/__boot__?token=launch-token"
    calls = []
    process = type("Process", (), {
        "stdout": io.StringIO(url + "\n"),
        "poll": lambda self: None,
        "terminate": lambda self: None,
        "wait": lambda self, **_kwargs: None,
    })()
    monkeypatch.setattr("cli.commands._stdin_is_tty", lambda _ctx: True)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr("web.run._open_url", lambda value: calls.append(value) or True)
    args = apply_defaults(build_parser().parse_args(["gui"]))
    ctx = make_cli_ctx()

    result = cmd_gui(args, ctx)
    assert result == exit_codes.OK, ctx.stderr.getvalue()
    assert calls == [url]
    assert "launched" in ctx.stderr.getvalue()


def test_cmd_gui_detached_launch_rejects_bad_startup_url(monkeypatch):
    terminated = []
    process = type("Process", (), {
        "stdout": io.StringIO("not-a-local-url\n"),
        "poll": lambda self: None,
        "terminate": lambda self: terminated.append(True),
        "wait": lambda self, **_kwargs: None,
    })()
    monkeypatch.setattr("cli.commands._stdin_is_tty", lambda _ctx: True)
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    args = apply_defaults(build_parser().parse_args(["gui"]))
    ctx = make_cli_ctx()

    result = cmd_gui(args, ctx)
    assert result == exit_codes.FAILURES, ctx.stderr.getvalue()
    assert terminated == [True]
    assert "did not publish a valid local URL" in ctx.stderr.getvalue()


def test_main_hidden_gui_token_runs_gui(monkeypatch):
    calls = []
    monkeypatch.setattr("web.run.run_web_ui", lambda **kwargs: calls.append(kwargs) or 7)
    assert main([GUI_INTERNAL]) == 7
    assert calls == [{}]


def test_main_no_args_with_owned_console_launches_gui(monkeypatch):
    monkeypatch.setattr("cli.main.owns_console", lambda: True)
    monkeypatch.setattr("cli.main.detach_console", lambda: True)
    calls = []
    monkeypatch.setattr("web.run.run_web_ui", lambda **kwargs: calls.append(kwargs) or 0)
    assert main([]) == exit_codes.OK
    assert calls == [{}]
