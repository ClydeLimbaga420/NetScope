from __future__ import annotations

from types import SimpleNamespace

from core.gateway_setup import active_target, default_route_gateway, detect_gateway
from core.models import Status
from core.runner import FakeRunner
from fixes.catalog import load_catalog
from fixes.executor import FixExecutor
from fixes.gateway_config import auto_configure_gateway
from powershell.runner import PowerShellLayer

from tests.test_fixes import StaticEngine


class FakePS:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def run_json(self, _expression):
        self.calls += 1
        return self.data


def missing_gateway_snapshot(snapshot_factory):
    return snapshot_factory(
        gateway=None,
        data={
            "adapters": [
                {
                    "Name": "Ethernet",
                    "InterfaceDescription": "Intel(R) Ethernet Connection",
                    "Status": "Up",
                    "MacAddress": "AA-BB-CC-DD-EE-01",
                    "ifIndex": 5,
                    "Virtual": False,
                }
            ],
            "ip_addresses": [
                {
                    "IPAddress": "192.168.1.10",
                    "PrefixLength": 24,
                    "PrefixOrigin": "Dhcp",
                    "AddressState": "Preferred",
                    "InterfaceAlias": "Ethernet",
                    "InterfaceIndex": 5,
                }
            ],
            "ip_configuration": [
                {
                    "InterfaceAlias": "Ethernet",
                    "InterfaceIndex": 5,
                    "IPv4Address": "192.168.1.10",
                    "PrefixLength": 24,
                    "IPv4Gateway": None,
                }
            ],
            "routes": [],
            "neighbors": [],
        },
    )


def reachable_runner() -> FakeRunner:
    return FakeRunner(default=(0, "Reply from 192.168.1.1: time=1ms TTL=64", ""))


def make_executor(tmp_path, snapshot, catalog, statuses=None):
    engine = StaticEngine(snapshot, check_id="IP-05", statuses=statuses or [Status.PASS])
    runner = reachable_runner()
    return FixExecutor(
        runner,
        PowerShellLayer(runner, None),
        None,
        engine,
        catalog,
        admin_check=lambda: True,
        backup_dir=tmp_path / "backups",
        session_id="gateway-test",
    )


def test_active_target_prefers_adapter_without_gateway(snapshot_factory):
    snapshot = snapshot_factory(
        data={
            "adapters": [
                {
                    "Name": "Wi-Fi",
                    "InterfaceDescription": "Intel(R) Wi-Fi",
                    "Status": "Up",
                    "Virtual": False,
                },
                {
                    "Name": "Ethernet",
                    "InterfaceDescription": "Intel(R) Ethernet Connection",
                    "Status": "Up",
                    "Virtual": False,
                },
            ],
            "ip_addresses": [
                {
                    "IPAddress": "192.168.1.20",
                    "PrefixLength": 24,
                    "AddressState": "Preferred",
                    "InterfaceAlias": "Wi-Fi",
                },
                {
                    "IPAddress": "192.168.1.10",
                    "PrefixLength": 24,
                    "AddressState": "Preferred",
                    "InterfaceAlias": "Ethernet",
                },
            ],
            "ip_configuration": [
                {"InterfaceAlias": "Wi-Fi", "IPv4Gateway": "192.168.1.1"},
                {"InterfaceAlias": "Ethernet", "IPv4Gateway": None},
            ],
            "routes": [],
        }
    )

    target = active_target(snapshot)

    assert target is not None
    assert target["alias"] == "Ethernet"


def test_detect_gateway_prefers_dhcp_server(snapshot_factory):
    snapshot = missing_gateway_snapshot(snapshot_factory)
    ps = FakePS(
        [
            {
                "InterfaceIndex": 5,
                "DHCPServer": "192.168.1.254",
                "DefaultIPGateway": [],
                "IPAddress": ["192.168.1.10"],
            }
        ]
    )

    suggestion = detect_gateway(snapshot, runner=reachable_runner(), ps=ps)

    assert ps.calls == 1
    assert suggestion.gateway == "192.168.1.254"
    assert suggestion.source == "DHCP server"
    assert suggestion.reachable is True
    assert suggestion.network == "192.168.1.0/24"


def test_detect_gateway_falls_back_to_first_address(snapshot_factory):
    snapshot = missing_gateway_snapshot(snapshot_factory)

    suggestion = detect_gateway(snapshot, runner=reachable_runner())

    assert suggestion.gateway == "192.168.1.1"
    assert suggestion.source == "first address in subnet"
    assert suggestion.reachable is True
    assert [candidate.host for candidate in suggestion.candidates][0] == "192.168.1.1"


def test_ip09_plan_resolves_adapter_and_detected_gateway(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("IP-09")
    snapshot = missing_gateway_snapshot(snapshot_factory)
    executor = make_executor(tmp_path, snapshot, catalog)

    plan = executor.prepare(entry, snapshot=snapshot)

    assert plan.values["AdapterName"] == "Ethernet"
    assert plan.values["Gateway"] == "192.168.1.1"
    assert any("192.168.1.1" in line for line in plan.preview_lines)
    assert any("New-NetRoute" in line for line in plan.preview_lines)


def test_ip09_runs_renew_then_route_when_gateway_stays_missing(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("IP-09")
    snapshot = missing_gateway_snapshot(snapshot_factory)
    executor = make_executor(tmp_path, snapshot, catalog, statuses=[Status.FAIL, Status.PASS])
    plan = executor.prepare(entry, snapshot=snapshot)

    outcome = executor.run(entry, plan=plan, assume_yes=True)

    assert outcome.status == "resolved"
    assert [step.status for step in outcome.steps] == ["ran", "ran"]
    assert any(
        "New-NetRoute" in " ".join(step.to_dict().get("commands", [])[0]["display"])
        for step in outcome.steps[1:]
    )
    assert any(call[:2] == ("ipconfig", "/renew") for call in executor.runner.calls)


def test_ip09_rollback_is_available(tmp_path, snapshot_factory):
    catalog = load_catalog()
    entry = catalog.require("IP-09")

    assert entry.state_changing is True
    assert entry.rollback
    assert any("Remove-NetRoute" in (command.script or "") for command in entry.rollback)


def test_default_route_gateway_reads_route_table(snapshot_factory):
    snapshot = missing_gateway_snapshot(snapshot_factory)
    assert default_route_gateway(snapshot) is None

    configured = snapshot_factory(
        data={
            "routes": [
                {
                    "DestinationPrefix": "0.0.0.0/0",
                    "NextHop": "192.168.1.1",
                    "InterfaceAlias": "Ethernet",
                }
            ]
        }
    )
    assert default_route_gateway(configured) == "192.168.1.1"


def test_auto_configure_gateway_skips_when_route_exists(snapshot_factory):
    snapshot = snapshot_factory(
        data={
            "routes": [
                {
                    "DestinationPrefix": "0.0.0.0/0",
                    "NextHop": "192.168.1.1",
                    "InterfaceAlias": "Ethernet",
                }
            ]
        }
    )
    runtime = SimpleNamespace(
        engine=SimpleNamespace(collect_snapshot=lambda: snapshot),
        catalog=None,
        executor=lambda: (_ for _ in ()).throw(AssertionError("executor must not run")),
    )

    result = auto_configure_gateway(runtime, snapshot=snapshot)

    assert result.status == "already_configured"
    assert result.gateway == "192.168.1.1"
    assert result.outcome is None


def test_auto_configure_gateway_applies_ip09_when_missing(tmp_path, snapshot_factory):
    catalog = load_catalog()
    snapshot = missing_gateway_snapshot(snapshot_factory)
    executor = make_executor(tmp_path, snapshot, catalog)
    runtime = SimpleNamespace(
        engine=SimpleNamespace(collect_snapshot=lambda: snapshot),
        catalog=catalog,
        executor=lambda: executor,
    )

    result = auto_configure_gateway(runtime, snapshot=snapshot)

    assert result.status == "resolved"
    assert result.adapter == "Ethernet"
    assert result.gateway == "192.168.1.1"
    assert result.outcome is not None
    assert result.outcome["status"] == "resolved"
