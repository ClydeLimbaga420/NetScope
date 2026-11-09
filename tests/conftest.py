from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.probes import DnsAnswer, FakeProbe, HttpResult
from core.runner import CommandResult, FakeRunner
from core.snapshot import Snapshot

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def cmd(stdout: str = "", returncode: int = 0, stderr: str = "") -> CommandResult:
    return CommandResult(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


DEFAULT_SERVICES = [
    {"Name": "WlanSvc", "State": "Running", "StartMode": "Auto"},
    {"Name": "Dhcp", "State": "Running", "StartMode": "Auto"},
    {"Name": "Dnscache", "State": "Running", "StartMode": "Auto"},
    {"Name": "NlaSvc", "State": "Running", "StartMode": "Auto"},
    {"Name": "netprofm", "State": "Running", "StartMode": "Auto"},
    {"Name": "BFE", "State": "Running", "StartMode": "Auto"},
    {"Name": "LanmanServer", "State": "Running", "StartMode": "Auto"},
    {"Name": "LanmanWorkstation", "State": "Running", "StartMode": "Auto"},
    {"Name": "FDResPub", "State": "Running", "StartMode": "Auto"},
    {"Name": "SSDPSRV", "State": "Running", "StartMode": "Auto"},
    {"Name": "upnphost", "State": "Running", "StartMode": "Manual"},
]


@pytest.fixture
def snapshot_factory(tmp_path):
    """Build a healthy Windows snapshot; override any section per test."""

    def make(**overrides) -> Snapshot:
        from core.native import PingResult

        data = {
            "adapters": [
                {
                    "Name": "Ethernet",
                    "InterfaceDescription": "Intel(R) Ethernet Connection",
                    "Status": "Up",
                    "LinkSpeed": "1 Gbps",
                    "MacAddress": "AA-BB-CC-DD-EE-01",
                    "ifIndex": 5,
                    "MediaType": "802.3",
                    "PhysicalMediaType": "802.3",
                    "Virtual": False,
                }
            ],
            "ip_addresses": [
                {
                    "IPAddress": "192.168.1.10",
                    "PrefixLength": 24,
                    "PrefixOrigin": "Dhcp",
                    "SuffixOrigin": "Dhcp",
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
                    "IPv4Gateway": "192.168.1.1",
                    "DnsServers": ["192.168.1.1"],
                }
            ],
            "routes": [
                {
                    "DestinationPrefix": "0.0.0.0/0",
                    "NextHop": "192.168.1.1",
                    "InterfaceAlias": "Ethernet",
                    "InterfaceIndex": 5,
                    "RouteMetric": 0,
                    "InterfaceMetric": 25,
                    "Store": "ActiveStore",
                }
            ],
            "neighbors": [
                {
                    "IPAddress": "192.168.1.1",
                    "LinkLayerAddress": "AA-BB-CC-DD-EE-FF",
                    "State": "Reachable",
                    "InterfaceAlias": "Ethernet",
                }
            ],
            "dns_servers": [
                {"InterfaceAlias": "Ethernet", "InterfaceIndex": 5, "ServerAddresses": ["192.168.1.1"]}
            ],
            "services": [dict(row) for row in DEFAULT_SERVICES],
            "pnp_network_devices": [
                {"FriendlyName": "Intel Ethernet", "Status": "OK", "Problem": 0}
            ],
            "adapter_power": [{"Name": "Ethernet", "AllowComputerToTurnOffDevice": "Disabled"}],
            "adapter_statistics": [],
            "connection_profiles": [
                {
                    "Name": "Home",
                    "InterfaceAlias": "Ethernet",
                    "NetworkCategory": "Private",
                    "IPv4Connectivity": "Internet",
                }
            ],
            "firewall_profiles": [{"Name": "Domain", "Enabled": "True"}],
            "firewall_discovery_rules": [
                {
                    "Group": "@FirewallAPI.dll,-32752",
                    "DisplayGroup": "Network Discovery",
                    "DisplayName": "Network discovery",
                    "Enabled": "True",
                    "Direction": "Inbound",
                    "Action": "Allow",
                }
            ],
            "smb_client": [{"EnableSMB2Protocol": "True"}],
            "system_proxy": [{"ProxyEnable": 0, "ProxyServer": "", "AutoConfigURL": ""}],
            "ncsi_settings": [],
            "vpn_connections": [],
        }
        data.update(overrides.pop("data", {}))

        pings = overrides.pop("pings", None)
        if pings is None:
            pings = {
                "192.168.1.1": PingResult("192.168.1.1", True, 1.0),
                "1.1.1.1": PingResult("1.1.1.1", True, 12.0),
                "8.8.8.8": PingResult("8.8.8.8", True, 14.0),
            }

        native = overrides.pop("native", None)
        if native is None:
            native = {
                "tcp_global": cmd("Receive Window Auto-Tuning Level    : normal\n"),
                "winsock_catalog": cmd("Description:            MSAFD Tcpip [TCP/IP]\n"),
                "winhttp_proxy": cmd("Direct access (no proxy server).\n"),
            }

        return Snapshot(
            is_windows=overrides.pop("is_windows", True),
            language_mode=overrides.pop("language_mode", "FullLanguage"),
            ps_available=overrides.pop("ps_available", True),
            constrained=overrides.pop("constrained", False),
            data=data,
            errors=overrides.pop("errors", {}),
            native=native,
            pings=pings,
            gateway=overrides.pop("gateway", "192.168.1.1"),
        )

    return make


@pytest.fixture
def healthy_probe(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text("# empty hosts file\n", encoding="utf-8")
    return FakeProbe(
        dns={
            "www.msftconnecttest.com@192.168.1.1": DnsAnswer(
                "www.msftconnecttest.com", "192.168.1.1", True, ["23.1.1.1"], 10.0
            ),
            "www.msftconnecttest.com@1.1.1.1": DnsAnswer(
                "www.msftconnecttest.com", "1.1.1.1", True, ["23.1.1.1"], 11.0
            ),
            "www.msftconnecttest.com@8.8.8.8": DnsAnswer(
                "www.msftconnecttest.com", "8.8.8.8", True, ["23.1.1.1"], 12.0
            ),
            "www.msftconnecttest.com": DnsAnswer(
                "www.msftconnecttest.com", None, True, ["23.1.1.1"], 1.0
            ),
        },
        http={
            "http://www.msftconnecttest.com/connecttest.txt": HttpResult(
                "http://www.msftconnecttest.com/connecttest.txt",
                True,
                200,
                "Microsoft Connect Test",
                {"date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")},
                date=datetime.now(timezone.utc),
            )
        },
        tcp={("192.168.1.1", 80): True},
    ), hosts


@pytest.fixture
def fake_runner():
    return FakeRunner()
