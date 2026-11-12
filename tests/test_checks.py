from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.checks import adapter, dns, gateway, internet, ip, lan, services, stack
from core.checks.context import CheckContext
from core.probes import DnsAnswer, FakeProbe, HttpResult
from core.runner import FakeRunner

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def ctx(snapshot, probe, hosts_path=None):
    return CheckContext(snapshot=snapshot, probe=probe, hosts_path=hosts_path)


def by_id(results, check_id):
    return next(result for result in results if result.id == check_id)


def test_adapter_disabled(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    snapshot = snapshot_factory(
        data={
            "adapters": [
                {
                    "Name": "Ethernet",
                    "InterfaceDescription": "Intel Ethernet",
                    "Status": "Disabled",
                    "LinkSpeed": "0 bps",
                    "Virtual": False,
                }
            ]
        }
    )
    result = by_id(adapter.run(ctx(snapshot, probe, hosts)), "ADP-01")
    assert result.status.value == "fail"
    assert result.fix_ids == ["ADP-01"]


def test_adapter_low_link_speed(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    snapshot = snapshot_factory(
        data={
            "adapters": [
                {
                    "Name": "Ethernet",
                    "InterfaceDescription": "Intel Ethernet",
                    "Status": "Up",
                    "LinkSpeed": "10 Mbps",
                    "MediaType": "802.3",
                    "Virtual": False,
                }
            ]
        }
    )
    result = by_id(adapter.run(ctx(snapshot, probe, hosts)), "ADP-05")
    assert result.status.value == "warn"
    assert result.fix_ids == ["ADP-05"]


def test_services_dhcp_stopped(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    rows = [
        {"Name": "Dhcp", "State": "Stopped", "StartMode": "Auto"},
        {"Name": "Dnscache", "State": "Running", "StartMode": "Auto"},
        {"Name": "NlaSvc", "State": "Running", "StartMode": "Auto"},
        {"Name": "netprofm", "State": "Running", "StartMode": "Auto"},
        {"Name": "BFE", "State": "Running", "StartMode": "Auto"},
        {"Name": "LanmanServer", "State": "Running", "StartMode": "Auto"},
        {"Name": "LanmanWorkstation", "State": "Running", "StartMode": "Auto"},
    ]
    snapshot = snapshot_factory(data={"services": rows})
    result = by_id(services.run(ctx(snapshot, probe, hosts)), "SVC-02")
    assert result.status.value == "fail"
    assert result.fix_ids == ["SVC-02"]


def test_ip_apipa(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    snapshot = snapshot_factory(
        data={
            "ip_addresses": [
                {
                    "IPAddress": "169.254.12.34",
                    "PrefixLength": 16,
                    "PrefixOrigin": "WellKnown",
                    "AddressState": "Preferred",
                    "InterfaceAlias": "Ethernet",
                }
            ]
        }
    )
    result = by_id(ip.run(ctx(snapshot, probe, hosts)), "IP-01")
    assert result.status.value == "fail"
    assert "169.254.12.34" in result.message


def test_ip_missing_default_route(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    from core.runner import CommandResult

    snapshot = snapshot_factory(
        data={"routes": []},
        native={
            "route_print": CommandResult(
                args=(),
                returncode=0,
                stdout=(
                    "IPv4 Route Table\n"
                    "Network Destination  Netmask  Gateway  Interface  Metric\n"
                    "192.168.1.0  255.255.255.0  On-link  192.168.1.10  281\n"
                ),
            )
        },
    )
    result = by_id(ip.run(ctx(snapshot, probe, hosts)), "IP-05")
    assert result.status.value == "fail"
    assert result.fix_ids == ["IP-09"]


def test_ip_overlapping_routes(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    snapshot = snapshot_factory(
        data={
            "routes": [
                {"DestinationPrefix": "0.0.0.0/0", "NextHop": "192.168.1.1", "InterfaceMetric": 25},
                {"DestinationPrefix": "10.0.0.0/8", "NextHop": "192.168.1.1", "InterfaceMetric": 25},
                {"DestinationPrefix": "10.0.0.0/8", "NextHop": "10.8.0.1", "InterfaceMetric": 5},
            ]
        }
    )
    result = by_id(ip.run(ctx(snapshot, probe, hosts)), "IP-06")
    assert result.status.value == "warn"
    assert "10.0.0.0/8" in result.message


def test_gateway_unreachable_arp_incomplete(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    from core.native import PingResult

    snapshot = snapshot_factory(
        pings={
            "192.168.1.1": PingResult("192.168.1.1", False),
            "1.1.1.1": PingResult("1.1.1.1", False),
            "8.8.8.8": PingResult("8.8.8.8", False),
        },
        data={
            "neighbors": [
                {"IPAddress": "192.168.1.1", "LinkLayerAddress": "", "State": "Incomplete"}
            ]
        },
    )
    result = by_id(gateway.run(ctx(snapshot, probe, hosts)), "GW-02")
    assert result.status.value == "fail"
    assert result.detection_only
    assert "LAN-02" in result.fix_ids


def test_dns_configured_fails_public_works(snapshot_factory):
    configured_fail = DnsAnswer("x", "192.168.1.1", False, error="timeout")
    public_ok = DnsAnswer("x", "1.1.1.1", True, ["23.1.1.1"])
    probe = FakeProbe(
        dns={
            "www.msftconnecttest.com@192.168.1.1": configured_fail,
            "www.msftconnecttest.com@1.1.1.1": public_ok,
            "www.msftconnecttest.com@8.8.8.8": public_ok,
            "www.msftconnecttest.com": DnsAnswer("x", None, False, error="fail"),
        }
    )
    snapshot = snapshot_factory()
    results = dns.run(ctx(snapshot, probe, FIXTURES / "empty_hosts"))
    result = by_id(results, "DNS-02")
    assert result.status.value == "fail"
    assert result.fix_ids == ["DNS-01", "DNS-02"]


def test_dns_hosts_override(snapshot_factory, healthy_probe, tmp_path):
    probe, _ = healthy_probe
    hosts = tmp_path / "hosts"
    hosts.write_text("0.0.0.0 ads.example.com\n127.0.0.1 www.msftconnecttest.com\n", encoding="utf-8")
    snapshot = snapshot_factory()
    result = by_id(dns.run(ctx(snapshot, probe, hosts)), "DNS-03")
    assert result.status.value == "warn"
    assert result.fix_ids == ["DNS-03"]


def test_internet_unreachable_beyond_gateway(snapshot_factory):
    from core.native import PingResult

    probe = FakeProbe(http={"http://www.msftconnecttest.com/connecttest.txt": HttpResult("u", False, error="no")})
    snapshot = snapshot_factory(
        pings={
            "192.168.1.1": PingResult("192.168.1.1", True, 1.0),
            "1.1.1.1": PingResult("1.1.1.1", False),
            "8.8.8.8": PingResult("8.8.8.8", False),
        }
    )
    result = by_id(internet.run(ctx(snapshot, probe)), "NET-PING")
    assert result.status.value == "fail"
    assert result.detection_only
    assert "router WAN" in result.cause or "ISP" in result.cause


def test_internet_captive_portal(snapshot_factory, healthy_probe):
    _, _ = healthy_probe
    probe = FakeProbe(
        http={
            "http://www.msftconnecttest.com/connecttest.txt": HttpResult(
                "http://www.msftconnecttest.com/connecttest.txt",
                False,
                302,
                "<html>Please log in to the hotel Wi-Fi</html>",
                headers={},
            )
        }
    )
    snapshot = snapshot_factory()
    result = by_id(internet.run(ctx(snapshot, probe)), "NET-01")
    assert result.status.value == "warn"
    assert result.fix_ids == ["NET-01"]


def test_internet_dead_user_proxy(snapshot_factory, healthy_probe):
    _, _ = healthy_probe
    probe = FakeProbe(
        http={
            "http://www.msftconnecttest.com/connecttest.txt": HttpResult(
                "u", True, 200, "Microsoft Connect Test", date=datetime.now(timezone.utc)
            )
        },
        tcp={},
    )
    snapshot = snapshot_factory(
        data={
            "system_proxy": [
                {"ProxyEnable": 1, "ProxyServer": "127.0.0.1:9", "AutoConfigURL": ""}
            ]
        }
    )
    result = by_id(internet.run(ctx(snapshot, probe)), "NET-04")
    assert result.status.value == "warn"
    assert result.fix_ids == ["NET-04"]


def test_lan_public_profile(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    snapshot = snapshot_factory(
        data={
            "connection_profiles": [
                {"Name": "Home", "InterfaceAlias": "Ethernet", "NetworkCategory": "Public"}
            ]
        }
    )
    result = by_id(lan.run(ctx(snapshot, probe, hosts)), "LAN-04")
    assert result.status.value == "warn"
    assert result.fix_ids == ["LAN-04"]


def test_lan_cross_subnet_warns_when_next_hop_is_unreachable(snapshot_factory, healthy_probe):
    from core.native import PingResult

    probe, hosts = healthy_probe
    snapshot = snapshot_factory(
        data={
            "routes": [
                {
                    "DestinationPrefix": "0.0.0.0/0",
                    "NextHop": "192.168.1.1",
                    "InterfaceAlias": "Ethernet",
                    "InterfaceMetric": 25,
                    "RouteMetric": 0,
                },
                {
                    "DestinationPrefix": "10.20.0.0/24",
                    "NextHop": "192.168.1.2",
                    "InterfaceAlias": "Ethernet",
                    "InterfaceMetric": 25,
                    "RouteMetric": 5,
                },
            ]
        },
        pings={
            "192.168.1.1": PingResult("192.168.1.1", True, 1.0),
            "192.168.1.2": PingResult("192.168.1.2", False, error="timeout"),
        },
    )

    result = by_id(lan.run(ctx(snapshot, probe, hosts)), "LAN-03")

    assert result.status.value == "warn"
    assert result.fix_ids == ["LAN-03"]
    assert result.evidence["subnets"][0]["network"] == "10.20.0.0/24"
    assert result.evidence["subnets"][0]["next_hop"] == "192.168.1.2"
    assert result.evidence["subnets"][0]["status"] == "unreachable"


def test_lan_cross_subnet_passes_when_next_hop_answers(snapshot_factory, healthy_probe):
    from core.native import PingResult

    probe, hosts = healthy_probe
    snapshot = snapshot_factory(
        data={
            "routes": [
                {
                    "DestinationPrefix": "10.20.0.0/24",
                    "NextHop": "192.168.1.2",
                    "InterfaceAlias": "Ethernet",
                    "InterfaceMetric": 25,
                    "RouteMetric": 5,
                }
            ]
        },
        pings={
            "192.168.1.1": PingResult("192.168.1.1", True, 1.0),
            "192.168.1.2": PingResult("192.168.1.2", True, 2.0),
        },
    )

    result = by_id(lan.run(ctx(snapshot, probe, hosts)), "LAN-03")

    assert result.status.value == "pass"
    assert result.fix_ids == []
    assert result.evidence["subnets"][0]["status"] == "reachable"


def test_lan_cross_subnet_skips_without_remote_routes(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    snapshot = snapshot_factory()

    result = by_id(lan.run(ctx(snapshot, probe, hosts)), "LAN-03")

    assert result.status.value == "skip"


def test_stack_third_party_lsp(snapshot_factory, healthy_probe):
    probe, hosts = healthy_probe
    from core.runner import CommandResult

    native = {
        "winsock_catalog": CommandResult(
            args=(), returncode=0, stdout=(FIXTURES / "sample_winsock.txt").read_text(encoding="utf-8")
        ),
        "tcp_global": CommandResult(args=(), returncode=0, stdout="Receive Window Auto-Tuning Level : normal\n"),
    }
    snapshot = snapshot_factory(native=native)
    result = by_id(stack.run(ctx(snapshot, probe, hosts)), "STK-01")
    assert result.status.value == "warn"
    assert result.fix_ids == ["STK-01"]
