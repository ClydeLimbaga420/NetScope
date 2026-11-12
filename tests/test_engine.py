from __future__ import annotations

from core.engine import DiagnosticEngine, resolve_layers
from core.models import CheckResult, Layer, Status
from core.runner import FakeRunner

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_resolve_layers_keeps_pipeline_order():
    assert resolve_layers(None) == [
        Layer.ADAPTER,
        Layer.SERVICES,
        Layer.IP,
        Layer.GATEWAY,
        Layer.LAN,
        Layer.DNS,
        Layer.INTERNET,
        Layer.STACK,
    ]
    assert resolve_layers(["dns", "adapter", "dns"]) == [Layer.ADAPTER, Layer.DNS]
    try:
        resolve_layers(["nope"])
    except ValueError as exc:
        assert "unknown layer" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_engine_runs_selected_layers_and_reports_progress(monkeypatch, snapshot_factory, healthy_probe):
    import core.engine as engine_module

    probe, hosts = healthy_probe
    snapshot = snapshot_factory()

    class FakeModule:
        def __init__(self, results):
            self.results = results

        def run(self, ctx):
            return self.results

    adapter_result = CheckResult(
        id="ADP-01",
        layer=Layer.ADAPTER,
        status=Status.FAIL,
        title="Adapter disabled",
        message="disabled",
        fix_ids=["ADP-01"],
    )
    monkeypatch.setitem(engine_module.CHECK_MODULES, Layer.ADAPTER, (FakeModule([adapter_result]),))

    progress = []
    engine = DiagnosticEngine(
        runner=FakeRunner(),
        probe=probe,
        hosts_path=hosts,
    )
    report = engine.diagnose(
        ["adapter"],
        snapshot=snapshot,
        progress=lambda layer, results: progress.append((layer, results)),
    )

    assert report.results == [adapter_result]
    assert report.exit_code == 2
    assert report.first_failing_layer is Layer.ADAPTER
    assert progress == [(Layer.ADAPTER, [adapter_result])]
    payload = report.to_dict()
    assert payload["results"][0]["id"] == "ADP-01"
    assert payload["mode"] == "cli"


def test_engine_runs_only_selected_check_ids(monkeypatch, snapshot_factory, healthy_probe):
    import core.engine as engine_module

    probe, hosts = healthy_probe
    snapshot = snapshot_factory()

    class FakeModule:
        def run(self, ctx):
            return [
                CheckResult(id="ADP-01", layer=Layer.ADAPTER, status=Status.PASS, title="Adapter enabled", message="ok"),
                CheckResult(id="ADP-04", layer=Layer.ADAPTER, status=Status.PASS, title="Driver health", message="ok"),
            ]

    monkeypatch.setitem(engine_module.CHECK_MODULES, Layer.ADAPTER, (FakeModule(),))

    engine = DiagnosticEngine(runner=FakeRunner(), probe=probe, hosts_path=hosts)
    report = engine.diagnose(["adapter"], snapshot=snapshot, check_ids=["ADP-04"])

    assert [result.id for result in report.results] == ["ADP-04"]


def test_engine_selected_check_matches_expanded_result_ids(monkeypatch, snapshot_factory, healthy_probe):
    import core.engine as engine_module

    probe, hosts = healthy_probe
    snapshot = snapshot_factory()

    class FakeModule:
        def run(self, ctx):
            return [
                CheckResult(id="SVC-04-NlaSvc", layer=Layer.SERVICES, status=Status.PASS, title="NLA", message="ok"),
                CheckResult(id="SVC-04-netprofm", layer=Layer.SERVICES, status=Status.PASS, title="NLM", message="ok"),
                CheckResult(id="SVC-06", layer=Layer.SERVICES, status=Status.PASS, title="Sharing", message="ok"),
            ]

    monkeypatch.setitem(engine_module.CHECK_MODULES, Layer.SERVICES, (FakeModule(),))

    engine = DiagnosticEngine(runner=FakeRunner(), probe=probe, hosts_path=hosts)
    report = engine.diagnose(["services"], snapshot=snapshot, check_ids=["SVC-04"])

    assert [result.id for result in report.results] == ["SVC-04-NlaSvc", "SVC-04-netprofm"]


def test_engine_captures_check_exception(monkeypatch, snapshot_factory, healthy_probe):
    import core.engine as engine_module

    probe, hosts = healthy_probe
    snapshot = snapshot_factory()

    class ExplodingModule:
        def run(self, ctx):
            raise RuntimeError("boom")

    monkeypatch.setitem(engine_module.CHECK_MODULES, Layer.DNS, (ExplodingModule(),))

    engine = DiagnosticEngine(runner=FakeRunner(), probe=probe)
    report = engine.diagnose(["dns"], snapshot=snapshot)

    assert len(report.results) == 1
    assert report.results[0].status is Status.ERROR
    assert "boom" in report.results[0].message
    assert report.exit_code == 2


def test_engine_full_pipeline_passes_on_healthy_snapshot(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    snapshot = snapshot_factory()
    engine = DiagnosticEngine(runner=FakeRunner(), probe=probe, hosts_path=hosts)

    report = engine.diagnose(snapshot=snapshot)

    assert report.exit_code == 0, [
        (result.id, result.status.value, result.message) for result in report.results
    ]
    assert report.first_failing_layer is None
    assert len(report.results) > 8
