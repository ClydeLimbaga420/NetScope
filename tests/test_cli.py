from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import config
from cli.admin import format_admin_command, is_admin
from cli.colors import Colorizer, color_supported
from cli.context import CliContext
from cli.main import main
from cli.parser import apply_defaults, build_parser
from cli.render import render_report_text
from cli.utilities import UtilityRunner, expand_ports, parse_packet_loss, parse_ping_latencies
from core.models import CheckResult, DiagnosticReport, Layer, Status
from core.probes import FakeProbe
from core.runner import CommandResult, FakeRunner, SubprocessRunner


class RecordingLogger:
    session_id = "test-session"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        if name in {
            "event",
            "debug",
            "warning",
            "error",
            "command",
            "check",
            "confirmation",
            "fix_applied",
            "unresolved",
            "action",
        }:
            def record(*args, **kwargs):
                self.calls.append((name, args, kwargs))

            return record
        raise AttributeError(name)


def make_ctx(runner=None, probe=None) -> CliContext:
    return CliContext(
        logger=RecordingLogger(),
        runner=runner or FakeRunner(),
        ps=None,
        probe=probe or FakeProbe(),
        color=Colorizer(False),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )


def parse(argv):
    args = build_parser().parse_args(argv)
    return apply_defaults(args)


class StaticEngine:
    def __init__(self, report=None, snapshot=None):
        self.report = report
        self.snapshot = snapshot

    def diagnose(self, layers=None, *, on_check=None, mode="cli", snapshot=None):
        report = self.report or DiagnosticReport.create("sid")
        for result in report.results:
            if on_check is not None:
                on_check(result)
        return report

    def collect_snapshot(self):
        return self.snapshot


def cmd_result(stdout: str = "", returncode: int = 0) -> CommandResult:
    return CommandResult(args=(), returncode=returncode, stdout=stdout)


def test_parser_global_flags_before_and_after_command():
    before = parse(["--json", "diagnose", "--layer", "dns"])
    assert before.json is True
    assert before.layer == ["dns"]

    after = parse(["diagnose", "--layer", "dns", "--json", "--quiet"])
    assert after.json is True
    assert after.quiet is True
    assert after.layer == ["dns"]

    bare = parse([])
    assert bare.command is None
    assert bare.json is False
    assert bare.dry_run is False


def test_main_version_and_usage(monkeypatch, capsys):
    assert main(["--version"]) == 0
    assert config.APP_VERSION in capsys.readouterr().out

    monkeypatch.setattr("cli.main._stdin_is_tty", lambda: False)
    assert main([]) == 64
    assert "usage:" in capsys.readouterr().err

    assert main(["diagnose", "--layer", "bogus"]) == 64
    assert "invalid choice" in capsys.readouterr().err


def test_help_for_every_command(capsys):
    parser = build_parser()
    for name in parser._subparsers_action.choices:
        with pytest.raises(SystemExit) as info:
            parser.parse_args([name, "--help"])
        assert info.value.code == 0
        assert "usage:" in capsys.readouterr().out


def test_main_ctrl_c_returns_130(monkeypatch):
    ctx = make_ctx()
    monkeypatch.setattr("cli.main.create_context", lambda *args, **kwargs: ctx)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("cli.commands.dispatch", interrupted)
    assert main(["diagnose"]) == 130
    assert "interrupted" in ctx.stderr.getvalue()


def test_no_ansi_when_not_a_tty_or_no_color(monkeypatch):
    class TtyStream(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert color_supported(io.StringIO()) is False
    assert "\x1b[" not in Colorizer(False).status_word(Status.FAIL)

    monkeypatch.setenv("NO_COLOR", "1")
    assert color_supported(TtyStream()) is False


def test_admin_helpers():
    command = format_admin_command(["netscope.py", "fix", "IP-01"])
    assert "netscope.py" in command
    assert "IP-01" in command
    assert isinstance(is_admin(), bool)


def test_diagnose_json_omits_snapshot_and_returns_exit_code():
    report = DiagnosticReport.create("sid")
    report.add(
        CheckResult(
            id="DNS-01",
            layer=Layer.DNS,
            status=Status.WARN,
            title="DNS latency",
            message="slow",
            cause="server busy",
            fix_ids=["DNS-02"],
        )
    )
    report.finish()

    ctx = make_ctx()
    ctx.engine = lambda: StaticEngine(report=report)
    args = parse(["diagnose", "--json"])
    from cli.commands import dispatch

    assert dispatch(args, ctx) == 1
    payload = json.loads(ctx.stdout.getvalue())
    assert payload["results"][0]["id"] == "DNS-01"
    assert "snapshot" not in payload
    assert payload["summary"]["warn"] == 1


def test_diagnose_human_prints_result_and_summary():
    report = DiagnosticReport.create("sid")
    report.add(
        CheckResult(
            id="ADP-01",
            layer=Layer.ADAPTER,
            status=Status.PASS,
            title="Adapter enabled",
            message="ok",
        )
    )
    report.finish()

    ctx = make_ctx()
    ctx.engine = lambda: StaticEngine(report=report)
    args = parse(["diagnose"])
    from cli.commands import dispatch

    assert dispatch(args, ctx) == 0
    out = ctx.stdout.getvalue()
    assert "ADP-01" in out
    assert "Overall: PASS" in out


def test_fix_command_rejects_unknown_ids():
    ctx = make_ctx()
    from cli.commands import dispatch

    assert dispatch(parse(["fix", "not-an-id"]), ctx) == 64
    assert "unknown finding or fix id" in ctx.stderr.getvalue()


def test_info_json_is_plain_data(snapshot_factory):
    native = {
        "mtu_interfaces": cmd_result(
            "                              1500          1     100     100  Ethernet\n"
        ),
        "arp": cmd_result(
            "  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic\n"
        ),
    }
    snapshot = snapshot_factory(native=native)
    ctx = make_ctx()
    ctx.engine = lambda: StaticEngine(snapshot=snapshot)

    from cli.commands import dispatch

    assert dispatch(parse(["info", "--json"]), ctx) == 0
    payload = json.loads(ctx.stdout.getvalue())
    adapter = payload["adapters"][0]
    assert adapter["name"] == "Ethernet"
    assert adapter["dhcp"] == "DHCP"
    assert adapter["mtu"] == 1500
    assert adapter["dns"] == ["192.168.1.1"]
    assert payload["mtu"]["Ethernet"] == 1500
    assert payload["arp"][0]["ip"] == "192.168.1.1"


def test_info_unknown_adapter_is_usage_error(snapshot_factory):
    ctx = make_ctx()
    ctx.engine = lambda: StaticEngine(snapshot=snapshot_factory())
    from cli.commands import dispatch

    assert dispatch(parse(["info", "--adapter", "Does Not Exist"]), ctx) == 64


def test_report_writes_txt_file(tmp_path, snapshot_factory):
    report = DiagnosticReport.create("sid")
    report.add(
        CheckResult(
            id="NET-PING",
            layer=Layer.INTERNET,
            status=Status.PASS,
            title="Internet reachable",
            message="ok",
        )
    )
    report.finish()
    ctx = make_ctx()
    ctx.engine = lambda: StaticEngine(report=report, snapshot=snapshot_factory())
    destination = tmp_path / "report.txt"

    from cli.commands import dispatch

    assert dispatch(parse(["report", "--output", str(destination)]), ctx) == 0
    text = destination.read_text(encoding="utf-8")
    assert "NetScope diagnostic report" in text
    assert "NET-PING" in text
    assert "report.txt" in ctx.stdout.getvalue()


def test_report_text_renderer_includes_causes():
    payload = {
        "info": {"hostname": "host", "adapters": [], "routes": [], "arp": []},
        "diagnostic": {
            "overall_status": "fail",
            "exit_code": 2,
            "summary": {"fail": 1},
            "results": [
                {
                    "id": "GW-02",
                    "layer": "gateway",
                    "status": "fail",
                    "title": "Gateway unreachable",
                    "message": "no reply",
                    "cause": "gateway down",
                    "evidence": {},
                    "fix_ids": ["GW-01"],
                    "detection_only": False,
                }
            ],
        },
    }
    text = render_report_text(payload)
    assert "GW-02" in text
    assert "gateway down" in text
    assert "GW-01" in text


def test_logs_tail_and_export(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "netscope.log"
    log_file.write_text("one\ntwo\nthree\n", encoding="utf-8")
    monkeypatch.setattr(config, "log_dir", lambda: log_dir)

    ctx = make_ctx()
    from cli.commands import dispatch

    assert dispatch(parse(["logs", "--tail", "2"]), ctx) == 0
    out = ctx.stdout.getvalue()
    assert "two" in out and "three" in out
    assert "one\n" not in out

    destination = tmp_path / "export.log"
    ctx = make_ctx()
    assert dispatch(parse(["logs", "--export", str(destination)]), ctx) == 0
    assert destination.read_text(encoding="utf-8") == "one\ntwo\nthree\n"


def test_parse_helpers():
    output = (
        "Reply from 1.1.1.1: bytes=32 time=10ms TTL=55\n"
        "Reply from 1.1.1.1: bytes=32 time<1ms TTL=55\n"
        "Minimum = 0ms, Maximum = 10ms, Average = 5ms\n"
    )
    assert parse_ping_latencies(output) == [10, 1]
    assert parse_packet_loss("Packets: Sent = 4, Lost = 1 (25% loss)") == 25
    assert expand_ports("80,443,8000-8002,80") == [80, 443, 8000, 8001, 8002]
    with pytest.raises(ValueError):
        expand_ports("1-2000", cap=10)


def test_ping_and_ports_utilities():
    runner = FakeRunner(
        {
            "ping": (
                0,
                "Reply from 1.1.1.1: bytes=32 time=12ms TTL=55\n"
                "Reply from 1.1.1.1: bytes=32 time=14ms TTL=55\n",
                "",
            )
        }
    )
    probe = FakeProbe(tcp={("1.1.1.1", 80): True, ("1.1.1.1", 443): False})
    ctx = make_ctx(runner=runner, probe=probe)
    utility = UtilityRunner(ctx)

    ping = utility.ping("1.1.1.1", count=2)
    assert ping["online"] is True
    assert ping["latencies_ms"] == [12, 14]

    ports = utility.ports("1.1.1.1", "80,443")
    assert ports["open"] == [80]
    assert ports["closed"] == [443]


def test_mtu_binary_search_uses_fake_ping():
    runner = FakeRunner(
        {"ping": (0, "Reply from 1.1.1.1: bytes=1472 time=1ms TTL=55\n", "")}
    )
    ctx = make_ctx(runner=runner)
    payload = UtilityRunner(ctx).mtu("1.1.1.1")
    assert payload["path_mtu"] == 1500
    assert payload["payload"] == 1472
    assert len(payload["tested"]) == 10 or payload["tested"]


def test_shell_help_and_exit():
    from cli.shell import run_shell

    ctx = make_ctx()
    inputs = iter(["help", "exit"])
    code = run_shell(build_parser(), ctx, input_func=lambda _prompt: next(inputs))
    assert code == 0
    assert "NetScope interactive shell" in ctx.stdout.getvalue()
    assert "usage:" in ctx.stdout.getvalue()


def test_shell_dispatches_commands():
    from cli.shell import run_shell

    report = DiagnosticReport.create("sid")
    report.add(
        CheckResult(
            id="ADP-01",
            layer=Layer.ADAPTER,
            status=Status.PASS,
            title="Adapter enabled",
            message="ok",
        )
    )
    report.finish()
    ctx = make_ctx()
    ctx.engine = lambda: StaticEngine(report=report)
    inputs = iter(["diagnose", "exit"])
    assert run_shell(build_parser(), ctx, input_func=lambda _prompt: next(inputs)) == 0
    assert "ADP-01" in ctx.stdout.getvalue()


def test_shell_survives_ctrl_c_during_command():
    from cli.shell import run_shell

    class InterruptingEngine:
        def diagnose(self, *args, **kwargs):
            raise KeyboardInterrupt

    ctx = make_ctx()
    ctx.engine = lambda: InterruptingEngine()
    inputs = iter(["diagnose", "exit"])
    assert run_shell(build_parser(), ctx, input_func=lambda _prompt: next(inputs)) == 0
    assert "interrupted" in ctx.stderr.getvalue()


def test_subprocess_runner_timeout_kills_child():
    runner = SubprocessRunner()
    result = runner.run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=0.2,
    )
    assert result.returncode == 124
    assert result.timed_out is True
    assert "timed out" in (result.error or "")


def test_subprocess_runner_kills_child_on_keyboard_interrupt(monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False
            self.calls = 0

        def communicate(self, input=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            return "", ""

        def kill(self):
            self.killed = True

    fake = FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake)

    runner = SubprocessRunner()
    with pytest.raises(KeyboardInterrupt):
        runner.run(["ping", "1.1.1.1"])
    assert fake.killed is True
