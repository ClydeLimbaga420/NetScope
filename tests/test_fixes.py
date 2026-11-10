from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cli.context import CliContext
from cli.colors import Colorizer
from cli.parser import apply_defaults, build_parser
from cli.render import render_report_text
from core.models import CheckResult, DiagnosticReport, Layer, Status
from core.probes import FakeProbe
from core.runner import FakeRunner
from fixes.catalog import CatalogError, load_catalog
from fixes.executor import FixExecutor
from fixes.if_unresolved import (
    build_unresolved_sections,
    rank_causes,
    unresolved_section,
)
from powershell.runner import PowerShellLayer

ROOT = Path(__file__).resolve().parents[1]


class RecordingLogger:
    session_id = "fix-test-session"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


class StaticEngine:
    def __init__(self, snapshot, report=None, check_id=None, statuses=None):
        self.snapshot = snapshot
        self.report = report
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
                id=self.check_id or "IP-01",
                layer=Layer.IP,
                status=status,
                title="verification check",
                message="resolved" if status is Status.PASS else "still failing",
            )
        )
        report.finish()
        return report


def make_ctx(runner=None, snapshot=None) -> CliContext:
    return CliContext(
        logger=RecordingLogger(),
        runner=runner or FakeRunner(default=(0, "", "")),
        ps=None,
        probe=FakeProbe(),
        color=Colorizer(False),
        stdout=__import__("io").StringIO(),
        stderr=__import__("io").StringIO(),
    )


def parse(argv):
    return apply_defaults(build_parser().parse_args(argv))


def make_executor(tmp_path, snapshot, engine, catalog=None):
    runner = FakeRunner(default=(0, "", ""))
    ps = PowerShellLayer(runner, None)
    return FixExecutor(
        runner,
        ps,
        None,
        engine,
        catalog or load_catalog(),
        admin_check=lambda: True,
        backup_dir=tmp_path / "backups",
        session_id="fix-test",
    )


# -- catalog -----------------------------------------------------------------


def test_catalog_contains_every_seeded_entry():
    catalog = load_catalog()
    expected = set()
    for prefix, count in (
        ("ADP", 6),
        ("SVC", 6),
        ("IP", 8),
        ("LAN", 11),
        ("DNS", 5),
        ("NET", 11),
        ("VPN", 6),
        ("WIFI", 4),
        ("STK", 4),
    ):
        expected.update(f"{prefix}-{index:02d}" for index in range(1, count + 1))
    assert set(catalog.ids) == expected
    assert len(catalog.entries) == 61
    assert catalog.version >= 1


def test_catalog_entries_have_required_fields_and_unresolved_blocks():
    catalog = load_catalog()
    for entry in catalog.entries:
        payload = entry.to_dict()
        for key in (
            "id",
            "name",
            "symptom",
            "detection",
            "explanation",
            "admin",
            "risk",
            "reboot",
            "snapshot",
            "rollback",
            "verify",
            "ladder",
            "if_unresolved",
        ):
            assert key in payload
        block = payload["if_unresolved"]
        assert block["this_device"]
        assert block["beyond_device"]
        assert block["next_checks"]
        assert block["evidence_to_collect"]


def test_detect_only_entries_never_contain_commands():
    catalog = load_catalog()
    detect_only = [entry for entry in catalog.entries if entry.detection_only]
    assert detect_only
    for entry in detect_only:
        assert entry.state_changing is False
        assert not entry.ladder
        assert not entry.commands


def test_verify_flags_are_exactly_the_required_entries():
    catalog = load_catalog()
    assert set(catalog.verify_flagged()) == {
        "IP-08",
        "LAN-10",
        "DNS-04",
        "DNS-05",
        "NET-06",
        "NET-08",
        "NET-11",
    }


def test_check_fix_ids_refer_to_catalog_entries():
    catalog = load_catalog()
    pattern = re.compile(r"fix_ids=\[([^\]]*)\]")
    quoted = re.compile(r'"([A-Za-z]{2,5}-[0-9]{2})"')
    referenced: set[str] = set()
    for path in (ROOT / "core" / "checks").glob("*.py"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            referenced.update(quoted.findall(match.group(1)))
    assert referenced
    assert referenced <= set(catalog.ids)


def test_catalog_rejects_unknown_fix_id():
    catalog = load_catalog()
    assert catalog.get("NOPE-99") is None
    with pytest.raises(CatalogError):
        catalog.require("NOPE-99")


def test_ip06_route_flush_is_gated_last_resort():
    catalog = load_catalog()
    entry = catalog.require("IP-06")

    final = entry.ladder[-1]
    assert final.risk == "high"
    assert final.requires_second_confirmation is True
    native = [command for command in final.commands if command.kind == "native"]
    assert any("route" in command.args and "-f" in command.args for command in native)

    for step in entry.ladder[:-1]:
        for command in step.commands:
            if command.kind == "native":
                assert not ("route" in command.args and "-f" in command.args)


# -- executor ----------------------------------------------------------------


def test_executor_resolves_and_saves_snapshot(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("IP-01")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="IP-01", statuses=[Status.PASS])
    executor = make_executor(tmp_path, snapshot, engine, catalog)
    plan = executor.prepare(entry, snapshot=snapshot)

    outcome = executor.run(entry, plan=plan, assume_yes=True)

    assert outcome.status == "resolved"
    assert outcome.exit_code == 0
    assert outcome.snapshot_file is not None
    assert Path(outcome.snapshot_file).exists()
    assert any("ipconfig" in call[0] for call in executor.runner.calls)


def test_executor_dry_run_does_not_execute(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("IP-01")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="IP-01", statuses=[Status.PASS])
    executor = make_executor(tmp_path, snapshot, engine, catalog)

    outcome = executor.run(entry, assume_yes=True, dry_run=True)

    assert outcome.status == "dry_run"
    assert outcome.exit_code == 0
    assert executor.runner.calls == []
    assert any("powershell" in line.lower() or "ipconfig" in line.lower() for line in executor.preview_lines(entry, executor.prepare(entry, snapshot=snapshot).values))


def test_executor_declined_confirmation_runs_nothing(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("IP-01")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="IP-01", statuses=[Status.PASS])
    executor = make_executor(tmp_path, snapshot, engine, catalog)

    outcome = executor.run(
        entry,
        assume_yes=False,
        confirm=lambda prompt: False,
    )

    assert outcome.status == "declined"
    assert outcome.exit_code == 3
    assert executor.runner.calls == []


def test_executor_requires_admin(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("ADP-01")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="ADP-01", statuses=[Status.PASS])
    executor = FixExecutor(
        FakeRunner(default=(0, "", "")),
        PowerShellLayer(FakeRunner(default=(0, "", "")), None),
        None,
        engine,
        catalog,
        admin_check=lambda: False,
        backup_dir=tmp_path / "backups",
        session_id="fix-test",
    )

    outcome = executor.run(entry, assume_yes=True)

    assert outcome.status == "needs_admin"
    assert outcome.exit_code == 4
    assert executor.runner.calls == []


def test_executor_high_risk_step_needs_second_confirmation(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("NET-07")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="NET-PING", statuses=[Status.FAIL])
    executor = make_executor(tmp_path, snapshot, engine, catalog)
    prompts: list[str] = []

    def confirm(prompt: str) -> bool:
        prompts.append(prompt)
        return "HIGH RISK" not in prompt

    outcome = executor.run(entry, assume_yes=False, confirm=confirm)

    assert outcome.status == "declined"
    assert any("HIGH RISK" in prompt for prompt in prompts)
    assert not any("firewall" in " ".join(call) for call in executor.runner.calls)


def test_executor_rolls_back_latest_snapshot(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("ADP-01")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="ADP-01", statuses=[Status.PASS])
    executor = make_executor(tmp_path, snapshot, engine, catalog)

    first = executor.run(entry, assume_yes=True)
    assert first.status == "resolved"
    assert first.snapshot_file

    outcome = executor.rollback(entry, assume_yes=True)

    assert outcome.status == "rolled_back"
    assert outcome.exit_code == 0
    assert outcome.snapshot_file == first.snapshot_file


def test_executor_rollback_without_snapshot_is_an_error(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("ADP-01")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="ADP-01", statuses=[Status.PASS])
    executor = make_executor(tmp_path, snapshot, engine, catalog)

    outcome = executor.rollback(entry, assume_yes=True)

    assert outcome.status == "error"
    assert outcome.exit_code == 3


def test_executor_detect_only_never_runs_commands(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("LAN-10")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="LAN-08", statuses=[Status.FAIL])
    executor = make_executor(tmp_path, snapshot, engine, catalog)

    outcome = executor.run(entry, assume_yes=True, isolation=lambda: True)

    assert outcome.status == "detection_only"
    assert outcome.exit_code == 2
    assert outcome.unresolved is not None
    assert outcome.unresolved["another_device_works"] is True
    assert executor.runner.calls == []


def test_executor_declined_optional_step_is_skipped(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("NET-10")
    snapshot = snapshot_factory()
    engine = StaticEngine(snapshot, check_id="NET-10", statuses=[Status.FAIL])
    executor = make_executor(tmp_path, snapshot, engine, catalog)

    def confirm(prompt: str) -> bool:
        return "Run step 2" not in prompt

    outcome = executor.run(entry, assume_yes=False, confirm=confirm)

    assert outcome.status == "unresolved"
    assert outcome.exit_code == 2
    assert outcome.steps[0].status == "ran"
    assert outcome.steps[1].status == "skipped"
    assert outcome.unresolved is not None
    assert any("autotuninglevel=normal" in " ".join(call) for call in executor.runner.calls)
    assert not any("highlyrestricted" in " ".join(call) for call in executor.runner.calls)


# -- if_unresolved -----------------------------------------------------------


def test_rank_causes_uses_isolation_answer():
    entry = load_catalog().require("ADP-01")
    beyond = rank_causes(entry.if_unresolved, another_device_works=True)
    this_device = rank_causes(entry.if_unresolved, another_device_works=False)

    assert beyond["beyond_device"][0]["likelihood"] == "probable"
    assert this_device["this_device"][0]["likelihood"] == "probable"
    assert beyond["ranked"]
    assert beyond["next_checks"]


def test_unresolved_section_uses_probabilistic_wording():
    entry = load_catalog().require("ADP-01")
    section = unresolved_section(entry, another_device_works=False)

    assert "probable or possible" in section["wording"]
    assert "not a confirmed diagnosis" in section["wording"]
    assert section["ranked"]
    assert section["fix_id"] == "ADP-01"


def test_unresolved_sections_only_include_unfixable_findings_by_default():
    catalog = load_catalog()
    report = DiagnosticReport.create("sid")
    report.add(
        CheckResult(
            id="IP-01",
            layer=Layer.IP,
            status=Status.FAIL,
            title="APIPA",
            message="no lease",
            fix_ids=["IP-01"],
        )
    )
    report.add(
        CheckResult(
            id="LAN-10",
            layer=Layer.LAN,
            status=Status.FAIL,
            title="Isolation",
            message="cannot reach peers",
            fix_ids=["LAN-10"],
            detection_only=True,
        )
    )
    report.finish()

    sections = build_unresolved_sections(report, catalog)
    assert [section["fix_id"] for section in sections] == ["LAN-10"]

    all_sections = build_unresolved_sections(report, catalog, include_fixable=True)
    assert {section["fix_id"] for section in all_sections} == {"IP-01", "LAN-10"}


def test_report_text_includes_unresolved_sections():
    entry = load_catalog().require("ADP-01")
    section = unresolved_section(entry, another_device_works=True)
    section["finding_id"] = "ADP-01"
    section["finding_title"] = "Adapter disabled"
    payload = {
        "info": {"hostname": "host", "adapters": [], "routes": [], "arp": []},
        "diagnostic": {
            "overall_status": "fail",
            "exit_code": 2,
            "summary": {"fail": 1},
            "results": [],
        },
        "unresolved": [section],
    }

    text = render_report_text(payload)
    assert "Still not working? ADP-01 - Adapter disabled" in text
    assert "probable or possible" in text
    assert "Next checks (cheapest first)" in text


# -- CLI ---------------------------------------------------------------------


def test_cli_fix_rejects_bad_ids(monkeypatch):
    from cli.commands import dispatch

    ctx = make_ctx()
    assert dispatch(parse(["fix", "not-an-id"]), ctx) == 64


def test_cli_fix_dry_run_returns_preview(monkeypatch, snapshot_factory):
    from cli.commands import dispatch

    monkeypatch.setattr("cli.commands.is_admin", lambda: True)
    snapshot = snapshot_factory()
    ctx = make_ctx(snapshot=snapshot)
    ctx.engine = lambda: StaticEngine(snapshot, check_id="IP-01", statuses=[Status.PASS])

    code = dispatch(parse(["fix", "IP-01", "--dry-run", "--yes", "--json"]), ctx)

    assert code == 0
    payload = json.loads(ctx.stdout.getvalue())
    assert payload["status"] == "dry_run"
    assert payload["preview"]
    assert payload["exit_code"] == 0


def test_cli_fix_runs_and_verifies(monkeypatch, snapshot_factory):
    from cli.commands import dispatch

    monkeypatch.setattr("cli.commands.is_admin", lambda: True)
    snapshot = snapshot_factory()
    ctx = make_ctx(snapshot=snapshot)
    ctx.engine = lambda: StaticEngine(snapshot, check_id="IP-01", statuses=[Status.PASS])

    code = dispatch(parse(["fix", "IP-01", "--yes", "--json"]), ctx)

    assert code == 0
    payload = json.loads(ctx.stdout.getvalue())
    assert payload["status"] == "resolved"
    assert payload["snapshot_file"]


def test_cli_fix_detect_only_returns_unresolved(monkeypatch, snapshot_factory):
    from cli.commands import dispatch

    monkeypatch.setattr("cli.commands.is_admin", lambda: True)
    snapshot = snapshot_factory()
    ctx = make_ctx(snapshot=snapshot)
    ctx.engine = lambda: StaticEngine(snapshot, check_id="LAN-08", statuses=[Status.FAIL])

    code = dispatch(parse(["fix", "LAN-10", "--yes", "--json"]), ctx)

    assert code == 2
    payload = json.loads(ctx.stdout.getvalue())
    assert payload["status"] == "detection_only"
    assert payload["unresolved"]
