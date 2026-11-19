from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import cli.launch as launch
from cli import exit_codes
from cli.admin import format_admin_command
from cli.colors import Colorizer
from cli.commands import cmd_gui
from cli.context import CliContext, create_context
from cli.launch import GUI_INTERNAL, STOP_ALL_INTERNAL, gui_relaunch_argv, owns_console
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


class FakeWinApiFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


def mock_console_process_count(monkeypatch, count: int) -> None:
    def get_console_process_list(process_ids, capacity):
        assert process_ids is not None
        assert capacity > 0
        return count

    kernel32 = SimpleNamespace(GetConsoleProcessList=get_console_process_list)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(kernel32=kernel32),
        raising=False,
    )


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


def test_frozen_onefile_bootloader_pair_still_owns_its_console(monkeypatch):
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    mock_console_process_count(monkeypatch, 2)

    assert owns_console() is True


def test_frozen_app_in_shared_terminal_does_not_own_console(monkeypatch):
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    mock_console_process_count(monkeypatch, 3)

    assert owns_console() is False


def test_detach_console_hides_window_before_freeing_console(monkeypatch):
    calls = []
    get_console_window = FakeWinApiFunction(lambda: calls.append("get") or 123)
    show_window = FakeWinApiFunction(
        lambda hwnd, command: calls.append((hwnd, command))
    )
    free_console = FakeWinApiFunction(lambda: calls.append("free") or 1)
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(
            kernel32=SimpleNamespace(
                GetConsoleWindow=get_console_window,
                FreeConsole=free_console,
            ),
            user32=SimpleNamespace(ShowWindow=show_window),
        ),
        raising=False,
    )

    assert launch.detach_console() is True
    assert get_console_window.restype is ctypes.wintypes.HWND
    assert show_window.argtypes == (ctypes.wintypes.HWND, ctypes.wintypes.INT)
    assert show_window.restype is ctypes.wintypes.BOOL
    assert calls == ["get", (123, 0), "free"]


def test_detach_console_removes_taskbar_button_before_hiding(monkeypatch):
    calls = []
    original_style = 0x00040000 | 0x00010000  # WS_EX_APPWINDOW | WS_EX_OVERLAPPEDWINDOW

    def get_style(hwnd, index):
        calls.append(("get_style", hwnd, index))
        return original_style

    def set_style(hwnd, index, value):
        calls.append(("set_style", hwnd, index, value))
        return 1

    get_console_window = FakeWinApiFunction(lambda: calls.append("get") or 123)
    get_style_fn = FakeWinApiFunction(get_style)
    set_style_fn = FakeWinApiFunction(set_style)
    show_window = FakeWinApiFunction(
        lambda hwnd, command: calls.append(("hide", hwnd, command))
    )
    free_console = FakeWinApiFunction(lambda: calls.append("free") or 1)
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(
            kernel32=SimpleNamespace(
                GetConsoleWindow=get_console_window,
                FreeConsole=free_console,
            ),
            user32=SimpleNamespace(
                GetWindowLongPtrW=get_style_fn,
                SetWindowLongPtrW=set_style_fn,
                ShowWindow=show_window,
            ),
        ),
        raising=False,
    )

    assert launch.detach_console() is True
    expected_style = (original_style | 0x00000080) & ~0x00040000
    assert ("set_style", 123, -20, expected_style) in calls
    assert calls.index(("set_style", 123, -20, expected_style)) < calls.index(("hide", 123, 0))
    assert calls[-1] == "free"


def test_detach_console_frees_console_when_window_handle_is_missing(monkeypatch):
    calls = []
    get_console_window = FakeWinApiFunction(lambda: 0)
    show_window = FakeWinApiFunction(lambda *_args: calls.append("hide"))
    free_console = FakeWinApiFunction(lambda: calls.append("free") or 1)
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(
            kernel32=SimpleNamespace(
                GetConsoleWindow=get_console_window,
                FreeConsole=free_console,
            ),
            user32=SimpleNamespace(ShowWindow=show_window),
        ),
        raising=False,
    )

    assert launch.detach_console() is True
    assert calls == ["free"]


def test_attach_parent_console_attaches_to_launching_terminal(monkeypatch):
    calls = []
    attach = FakeWinApiFunction(lambda pid: calls.append(pid) or 1)
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(AttachConsole=attach)),
        raising=False,
    )

    assert launch.attach_parent_console() is True
    assert calls == [0xFFFFFFFF]


def test_attach_parent_console_is_noop_for_source_runs(monkeypatch):
    monkeypatch.setattr(launch.sys, "frozen", False, raising=False)
    assert launch.attach_parent_console() is False


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
    assert calls == [{"port": None, "no_browser": False, "browser": False, "print_url": False, "replace": False}]


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
    popen_calls = []
    process = type("Process", (), {
        "stdout": io.StringIO(url + "\n"),
        "poll": lambda self: None,
        "terminate": lambda self: None,
        "wait": lambda self, **_kwargs: None,
    })()
    monkeypatch.setattr("cli.commands._stdin_is_tty", lambda _ctx: True)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: popen_calls.append(argv) or process)
    args = apply_defaults(build_parser().parse_args(["gui"]))
    ctx = make_cli_ctx()

    result = cmd_gui(args, ctx)
    assert result == exit_codes.OK, ctx.stderr.getvalue()
    assert "--print-url" in popen_calls[0]
    assert "launched" in ctx.stderr.getvalue().lower()


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
    monkeypatch.setattr(
        "cli.main.build_parser",
        lambda: pytest.fail("owned-console GUI launch should bypass argparse"),
    )
    calls = []
    monkeypatch.setattr("web.run.run_web_ui", lambda **kwargs: calls.append(kwargs) or 0)
    assert main([]) == exit_codes.OK
    assert calls == [{}]


def test_main_no_args_from_frozen_onefile_launches_gui(monkeypatch):
    monkeypatch.setattr(launch.os, "name", "nt")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    mock_console_process_count(monkeypatch, 2)
    monkeypatch.setattr("cli.main.detach_console", lambda: True)
    calls = []
    monkeypatch.setattr("web.run.run_web_ui", lambda **kwargs: calls.append(kwargs) or 0)

    assert main([]) == exit_codes.OK
    assert calls == [{}]


def test_main_no_args_in_shared_terminal_keeps_interactive_shell(monkeypatch):
    ctx = make_cli_ctx()
    shell_calls = []
    monkeypatch.setattr("cli.main.owns_console", lambda: False)
    monkeypatch.setattr("cli.main._stdin_is_tty", lambda: True)
    monkeypatch.setattr("cli.main.create_context", lambda *_args, **_kwargs: ctx)
    monkeypatch.setattr(
        "cli.main.run_shell",
        lambda parser, shell_ctx: shell_calls.append((parser, shell_ctx)) or 0,
    )

    assert main([]) == exit_codes.OK
    assert len(shell_calls) == 1
    assert shell_calls[0][1] is ctx


def test_gui_relaunch_argv_can_request_replace():
    argv = gui_relaunch_argv(replace=True)
    assert argv[-2:] == [GUI_INTERNAL, "--replace"]


def test_gui_parser_accepts_browser_and_print_url():
    args = apply_defaults(build_parser().parse_args(["gui", "--browser", "--print-url"]))
    assert args.browser is True
    assert args.print_url is True


def test_cmd_gui_detached_child_opens_window(monkeypatch):
    url = "http://127.0.0.1:54321/__boot__?token=launch-token"
    popen_calls = []
    process = type("Process", (), {
        "stdout": io.StringIO(url + "\n"),
        "poll": lambda self: None,
        "terminate": lambda self: None,
        "wait": lambda self, **_kwargs: None,
    })()
    monkeypatch.setattr("cli.commands._stdin_is_tty", lambda _ctx: True)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: popen_calls.append(argv) or process)
    args = apply_defaults(build_parser().parse_args(["gui", "--browser"]))
    ctx = make_cli_ctx()

    assert cmd_gui(args, ctx) == exit_codes.OK, ctx.stderr.getvalue()
    assert "--print-url" in popen_calls[0]
    assert "--browser" in popen_calls[0]
    assert "window launched" in ctx.stderr.getvalue().lower()


def test_main_hidden_stop_all_token_stops_everything(monkeypatch):
    calls = []
    monkeypatch.setattr("cli.stop.stop_running_ui", lambda: calls.append(True) or "stopped")
    assert main([STOP_ALL_INTERNAL]) == exit_codes.OK
    assert calls == [True]


def test_main_finalizes_child_processes_on_cli_exit(monkeypatch):
    calls = []
    monkeypatch.setattr("cli.main.attach_parent_console", lambda: False)
    monkeypatch.setattr("cli.main.owns_console", lambda: False)
    monkeypatch.setattr("cli.main._stdin_is_tty", lambda: False)
    monkeypatch.setattr("cli.main.finalize_processes", lambda: calls.append(True))
    monkeypatch.setattr("cli.commands.dispatch", lambda _args, _ctx: exit_codes.OK)

    assert main(["info", "--json"]) == exit_codes.OK
    assert calls == [True]


def test_main_hidden_gui_token_passes_replace(monkeypatch):
    calls = []
    monkeypatch.setattr("web.run.run_web_ui", lambda **kwargs: calls.append(kwargs) or 0)
    assert main([GUI_INTERNAL, "--replace"]) == 0
    assert calls == [{"replace": True}]
