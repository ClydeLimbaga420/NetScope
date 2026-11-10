from __future__ import annotations

import io
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

tkinter = pytest.importorskip("tkinter")

import config
from cli import exit_codes
from cli.colors import Colorizer
from cli.commands import cmd_gui
from cli.context import CliContext, create_context
from cli.main import main
from cli.parser import apply_defaults, build_parser
from core.logging_config import NullLogger
from core.models import LAYER_ORDER, CheckResult, DiagnosticReport, Layer, Status
from core.probes import FakeProbe
from core.runner import FakeRunner
from fixes.catalog import load_catalog
from fixes.executor import FixExecutor
from gui.app import NetScopeGui
from gui.dialogs import DialogBridge
from gui.launch import GUI_INTERNAL, gui_relaunch_argv, owns_console
from gui.runtime import GuiRuntime, build_runtime, runtime_from_context
from powershell.runner import PowerShellLayer


class RecordingLogger:
    session_id = "gui-test-session"

    def __getattr__(self, name: str):
        def record(*args: Any, **kwargs: Any) -> None:
            return None

        return record


class StaticEngine:
    def __init__(self, snapshot, check_id="IP-01", statuses=None):
        self.snapshot = snapshot
        self.check_id = check_id
        self.statuses = list(statuses or [])
        self.diagnose_calls = 0

    def collect_snapshot(self):
        return self.snapshot

    def diagnose(self, layers=None, *, on_check=None, mode="cli", snapshot=None):
        self.diagnose_calls += 1
        if self.statuses:
            index = min(self.diagnose_calls - 1, len(self.statuses) - 1)
            status = self.statuses[index]
        else:
            status = Status.PASS
        report = DiagnosticReport.create("sid", mode=mode)
        report.add(
            CheckResult(
                id=self.check_id,
                layer=Layer.IP,
                status=status,
                title="verification check",
                message="resolved" if status is Status.PASS else "still failing",
            )
        )
        report.finish()
        if on_check is not None:
            on_check(report.results[0])
        return report


class BrokenEngine:
    def collect_snapshot(self):
        raise RuntimeError("boom")

    def diagnose(self, *args: Any, **kwargs: Any):
        raise AssertionError("diagnose should not run after collection failed")


def make_gui(root, tmp_path, snapshot, *, check_id="IP-01", statuses=None):
    runner = FakeRunner(default=(0, "", ""))
    ps = PowerShellLayer(runner, None)
    runtime = GuiRuntime(
        engine=StaticEngine(snapshot, check_id=check_id, statuses=statuses),
        catalog=load_catalog(),
        runner=runner,
        ps=ps,
        logger=RecordingLogger(),
        admin_check=lambda: True,
        session_id="gui-test",
        backup_dir=tmp_path / "backups",
    )
    return NetScopeGui(root, runtime, auto_confirm=True)


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


@pytest.fixture
def tk_root():
    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display available for tkinter")
    yield root
    root.destroy()


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


# -- dialog bridge ------------------------------------------------------------


def test_dialog_bridge_round_trip_from_worker_thread():
    bridge = DialogBridge()
    bridge.handler = lambda kind, payload: f"{kind}:{payload}"
    result: dict[str, Any] = {}

    def worker() -> None:
        result["answer"] = bridge.submit("confirm", "prompt", timeout=10)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.time() + 10
    while thread.is_alive() and time.time() < deadline:
        bridge.poll()
    thread.join(2)
    assert result == {"answer": "confirm:prompt"}


def test_dialog_bridge_without_handler_answers_none():
    bridge = DialogBridge()
    result: dict[str, Any] = {}

    def worker() -> None:
        result["answer"] = bridge.submit("isolation", None, timeout=10)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.time() + 10
    while thread.is_alive() and time.time() < deadline:
        bridge.poll()
    thread.join(2)
    assert result == {"answer": None}


def test_dialog_bridge_submit_from_ui_thread_answers_directly():
    bridge = DialogBridge()
    seen: list[str] = []
    bridge.handler = lambda kind, payload: seen.append(kind) or "ok"
    assert bridge.submit("confirm", "x") == "ok"
    bridge.poll()
    assert seen == ["confirm"]


# -- runtime ------------------------------------------------------------------


def test_build_runtime_loads_catalog_and_builds_executor():
    runtime = build_runtime()
    assert runtime.catalog.get("IP-01") is not None
    assert isinstance(runtime.executor(), FixExecutor)


def test_runtime_from_context_reuses_cli_objects():
    ctx = create_context("gui-test", logger=NullLogger())
    runtime = runtime_from_context(ctx)
    assert runtime.runner is ctx.runner
    assert runtime.ps is ctx.ps
    assert runtime.session_id == getattr(ctx.logger, "session_id", "-")
    assert runtime.catalog.get("IP-01") is not None


# -- GUI construction and rendering -------------------------------------------


def test_gui_constructs_and_lists_findings(tk_root, tmp_path, snapshot_factory):
    app = make_gui(tk_root, tmp_path, snapshot_factory())
    report = DiagnosticReport.create("sid", mode="gui")
    report.add(
        CheckResult(
            id="IP-CONFIG-01",
            layer=Layer.IP,
            status=Status.FAIL,
            title="APIPA address",
            message="DHCP did not answer; the adapter self-assigned an address.",
            cause="no DHCP lease",
            evidence={"address": "169.254.10.20"},
            fix_ids=["IP-01"],
        )
    )
    report.add(
        CheckResult(
            id="GW-02",
            layer=Layer.GATEWAY,
            status=Status.PASS,
            title="Gateway reachable",
            message="ok",
        )
    )
    report.finish()

    app._populate(report)
    assert len(app.tree.get_children()) == 2

    app._on_select()
    detail = app.detail_text.get("1.0", "end")
    assert "APIPA address" in detail
    buttons = app.fix_frame.winfo_children()
    assert len(buttons) == 1
    assert str(buttons[0].cget("text")).startswith("Proceed to Fix IP-01")


def test_gui_detail_for_passing_result_has_no_fix_button(tk_root, tmp_path, snapshot_factory):
    app = make_gui(tk_root, tmp_path, snapshot_factory())
    result = CheckResult(
        id="GW-02",
        layer=Layer.GATEWAY,
        status=Status.PASS,
        title="Gateway reachable",
        message="ok",
    )
    app._show_detail(result)
    assert app.fix_frame.winfo_children() == []


def test_gui_selected_layers_respect_checkboxes(tk_root, tmp_path, snapshot_factory):
    app = make_gui(tk_root, tmp_path, snapshot_factory())
    all_names = [layer.value for layer in LAYER_ORDER]
    assert app.selected_layers() == all_names
    for var in app._layer_vars.values():
        var.set(False)
    assert app.selected_layers() == all_names
    app._layer_vars["dns"].set(True)
    assert app.selected_layers() == ["dns"]


def test_gui_start_diagnosis_runs_engine_and_fills_tree(tk_root, tmp_path, snapshot_factory):
    app = make_gui(
        tk_root, tmp_path, snapshot_factory(), check_id="IP-CONFIG-01", statuses=[Status.FAIL]
    )
    app.start_diagnosis()
    deadline = time.time() + 10
    while time.time() < deadline and app.report is None:
        app._poll_queue()
        tk_root.update()
    assert app.report is not None
    assert len(app.tree.get_children()) == 1
    assert app.report.exit_code == 2


def test_gui_diagnose_failure_is_reported_not_raised(tk_root, tmp_path, snapshot_factory):
    snapshot = snapshot_factory()
    runtime = GuiRuntime(
        engine=BrokenEngine(),
        catalog=load_catalog(),
        runner=FakeRunner(default=(0, "", "")),
        ps=None,
        logger=RecordingLogger(),
        admin_check=lambda: True,
        session_id="gui-test",
        backup_dir=tmp_path / "backups",
    )
    app = NetScopeGui(tk_root, runtime, auto_confirm=True)
    app.worker_diagnose(["ip"])
    app._poll_queue()
    assert "Diagnosis failed" in app.status_label.cget("text")


# -- fix flow ------------------------------------------------------------------


def test_gui_worker_fix_resolves_and_renders_outcome(tk_root, tmp_path, snapshot_factory):
    app = make_gui(tk_root, tmp_path, snapshot_factory(), statuses=[Status.PASS])
    app._last_snapshot = snapshot_factory()
    result = CheckResult(
        id="IP-CONFIG-01",
        layer=Layer.IP,
        status=Status.FAIL,
        title="APIPA address",
        message="self-assigned address",
        fix_ids=["IP-01"],
    )
    app._selected = result
    entry = app.catalog.require("IP-01")
    assert not entry.detection_only

    app.worker_fix(entry, result)
    app._poll_queue()

    assert app.status_label.cget("text") == "Fix IP-01: resolved"
    assert "Verification: resolved" in app.detail_text.get("1.0", "end")


def test_gui_declined_fix_confirm_cancels_without_running(tk_root, tmp_path, snapshot_factory):
    app = make_gui(tk_root, tmp_path, snapshot_factory())
    app.auto_confirm = False
    app._dialog_fix_confirm = lambda plan: False
    result = CheckResult(
        id="IP-CONFIG-01",
        layer=Layer.IP,
        status=Status.FAIL,
        title="APIPA address",
        message="self-assigned address",
        fix_ids=["IP-01"],
    )
    app._selected = result
    engine = app.runtime.engine
    app.worker_fix(app.catalog.require("IP-01"), result)
    app._poll_queue()
    assert app.status_label.cget("text") == "Fix was cancelled."
    assert engine.diagnose_calls == 0


def test_gui_detection_only_shows_likely_causes_panel(tk_root, tmp_path, snapshot_factory):
    app = make_gui(tk_root, tmp_path, snapshot_factory())
    entry = app.catalog.require("LAN-09")
    assert entry.detection_only
    result = CheckResult(
        id="LAN-09",
        layer=Layer.LAN,
        status=Status.WARN,
        title="Insecure guest authentication in use",
        message="an SMB share allows guest access",
        fix_ids=["LAN-09"],
    )
    app._selected = result
    app.proceed_to_fix("LAN-09")
    body = app.causes.body.get("1.0", "end")
    assert "Still not working?" in body
    assert "Probable or possible causes" in body
    assert "DETECT-ONLY" in app.status_label.cget("text")


def test_gui_report_export_writes_txt_report(tk_root, tmp_path, snapshot_factory, monkeypatch):
    monkeypatch.setattr(config, "report_dir", lambda: tmp_path / "reports")
    app = make_gui(tk_root, tmp_path, snapshot_factory())
    app.worker_report("txt")
    app._poll_queue()
    assert "Report written to" in app.status_label.cget("text")
    files = list((tmp_path / "reports").glob("netscope-report-*.txt"))
    assert len(files) == 1
    assert "NetScope diagnostic report" in files[0].read_text(encoding="utf-8")


# -- CLI integration -----------------------------------------------------------


def test_cmd_gui_reports_launch(monkeypatch):
    monkeypatch.setattr("gui.launch.launch_detached_gui", lambda: True)
    args = apply_defaults(build_parser().parse_args(["gui"]))
    ctx = make_cli_ctx()
    assert cmd_gui(args, ctx) == exit_codes.OK
    assert "launched" in ctx.stderr.getvalue()


def test_cmd_gui_failure_is_reported(monkeypatch):
    monkeypatch.setattr("gui.launch.launch_detached_gui", lambda: False)
    args = apply_defaults(build_parser().parse_args(["gui"]))
    ctx = make_cli_ctx()
    assert cmd_gui(args, ctx) == exit_codes.FAILURES
    assert "could not start the GUI" in ctx.stderr.getvalue()


def test_main_hidden_gui_token_runs_gui(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_run_gui(runtime=None):
        seen["runtime"] = runtime
        return 7

    monkeypatch.setattr("gui.app.run_gui", fake_run_gui)
    assert main([GUI_INTERNAL]) == 7
    assert seen["runtime"] is not None


def test_main_no_args_with_owned_console_launches_gui(monkeypatch):
    monkeypatch.setattr("cli.main.owns_console", lambda: True)
    monkeypatch.setattr("cli.main.detach_console", lambda: True)
    monkeypatch.setattr("cli.main.launch_detached_gui", lambda: True)
    assert main([]) == exit_codes.OK
