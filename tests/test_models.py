from __future__ import annotations

from core.models import (
    CheckResult,
    DiagnosticReport,
    Layer,
    Status,
    combine_status,
)


def make(check_id: str, layer: Layer, status: Status) -> CheckResult:
    return CheckResult(id=check_id, layer=layer, status=status, title="t", message="m")


def test_status_severity_and_combine():
    results = [
        make("a", Layer.ADAPTER, Status.PASS),
        make("b", Layer.SERVICES, Status.WARN),
        make("c", Layer.IP, Status.FAIL),
    ]
    assert combine_status(results) is Status.FAIL
    assert combine_status([make("a", Layer.ADAPTER, Status.PASS)]) is Status.PASS
    assert combine_status([]) is Status.PASS


def test_report_exit_codes_and_first_layer():
    report = DiagnosticReport.create(session_id="abc")
    report.add(make("ADP-01", Layer.ADAPTER, Status.PASS))
    report.add(make("DNS-02", Layer.DNS, Status.WARN))
    assert report.exit_code == 1
    assert report.first_failing_layer is Layer.DNS

    report.add(make("GW-02", Layer.GATEWAY, Status.FAIL))
    assert report.exit_code == 2
    assert report.first_failing_layer is Layer.GATEWAY

    report.finish()
    payload = report.to_dict()
    assert payload["session_id"] == "abc"
    assert payload["results"][0]["id"] == "ADP-01"
    assert payload["first_failing_layer"] == "gateway"


def test_check_result_round_trip():
    original = CheckResult(
        id="IP-01",
        layer=Layer.IP,
        status=Status.FAIL,
        title="APIPA",
        message="169.254.1.2",
        cause="DHCP failed",
        evidence={"apipa": ["169.254.1.2"]},
        fix_ids=["IP-01"],
        detection_only=True,
    )
    restored = CheckResult.from_dict(original.to_dict())
    assert restored == original
