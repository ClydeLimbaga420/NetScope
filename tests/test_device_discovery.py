from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.device_discovery import DeviceDiscovery
from core.runner import CommandResult
from powershell import scripts
from powershell.runner import PowerShellLayer


def _adapter(name, mac="3C-22-FB-AA-BB-CC", **overrides):
    row = {
        "Name": name,
        "InterfaceAlias": name,
        "InterfaceDescription": name,
        "Status": "Up",
        "MacAddress": mac,
        "PermanentAddress": mac,
        "LinkSpeed": "1 Gbps",
        "Virtual": False,
    }
    row.update(overrides)
    return row


def _address(ip, prefix, name):
    return {
        "IPAddress": ip,
        "PrefixLength": prefix,
        "InterfaceAlias": name,
    }


def _snapshot(snapshot_factory, adapters, addresses, *, routes=None, gateway=None):
    return snapshot_factory(
        data={
            "adapters": adapters,
            "ip_addresses": addresses,
            "routes": routes or [],
        },
        gateway=gateway,
    )


class DiscoveryRunner:
    def __init__(self, *, arp_output="", nbt_names=None, dns_names=None, delay=0.0):
        self.arp_output = arp_output
        self.nbt_names = dict(nbt_names or {})
        self.dns_names = dict(dns_names or {})
        self.delay = delay
        self.calls = []
        self.script_text = None
        self.active_pings = 0
        self.max_active_pings = 0
        self.lock = threading.Lock()

    def run(self, args, *, timeout=None, **_kwargs):
        argv = tuple(str(part) for part in args)
        with self.lock:
            self.calls.append((argv, timeout))

        executable = argv[0].lower()
        if executable == "powershell.exe":
            script_path = Path(argv[argv.index("-File") + 1])
            self.script_text = script_path.read_text(encoding="utf-8-sig")
            return CommandResult(argv, 0, stdout="true")
        if executable == "ping":
            with self.lock:
                self.active_pings += 1
                self.max_active_pings = max(
                    self.max_active_pings, self.active_pings
                )
            try:
                if self.delay:
                    time.sleep(self.delay)
                return CommandResult(argv, 1, stdout="Request timed out.")
            finally:
                with self.lock:
                    self.active_pings -= 1
        if executable == "arp":
            return CommandResult(argv, 0, stdout=self.arp_output)
        if executable == "nbtstat":
            name = self.nbt_names.get(argv[-1])
            output = f"{name} <00> UNIQUE Registered\n" if name else ""
            return CommandResult(argv, 0, stdout=output)
        if executable == "nslookup":
            name = self.dns_names.get(argv[-1])
            output = f"Name: {name}\nAddress: {argv[-1]}\n" if name else ""
            return CommandResult(argv, 0, stdout=output)
        return CommandResult(argv, 127, error=f"unexpected command: {argv[0]}")


def _discovery(tmp_path, runner=None, clock=lambda: 0.0):
    runner = runner or DiscoveryRunner()
    ps = PowerShellLayer(runner, temp_root=tmp_path)
    return DeviceDiscovery(runner, ps, clock=clock), runner


def _ping_hosts(runner):
    return {
        args[-1]
        for args, _timeout in runner.calls
        if args[0].lower() == "ping"
    }


def test_discovery_scans_only_active_local_private_ipv4_prefixes(
    snapshot_factory, tmp_path
):
    adapters = [
        _adapter("Ethernet"),
        _adapter("Disconnected", Status="Disconnected"),
        _adapter("vEthernet (Default Switch)"),
        _adapter("Virtual adapter", Virtual=True),
        _adapter("Public"),
        _adapter("Loopback"),
        _adapter("Link-local"),
    ]
    addresses = [
        _address("192.168.50.2", 30, "Ethernet"),
        _address("192.168.60.2", 30, "Disconnected"),
        _address("10.0.0.2", 30, "vEthernet (Default Switch)"),
        _address("172.16.0.2", 30, "Virtual adapter"),
        _address("8.8.8.2", 30, "Public"),
        _address("127.0.0.2", 8, "Loopback"),
        _address("169.254.1.2", 30, "Link-local"),
        _address("10.0.0.3", "invalid", "Ethernet"),
        _address("not-an-ip", 24, "Ethernet"),
    ]
    snapshot = _snapshot(
        snapshot_factory,
        adapters,
        addresses,
        routes=[
            {
                "DestinationPrefix": "10.99.0.0/16",
                "NextHop": "192.168.50.1",
                "InterfaceAlias": "Ethernet",
            }
        ],
        gateway="192.168.50.1",
    )
    discovery, runner = _discovery(tmp_path)

    discovery.discover(snapshot)

    assert _ping_hosts(runner) == {"192.168.50.1"}
    assert {args[0].lower() for args, _timeout in runner.calls} >= {
        "ping",
        "arp",
        "powershell.exe",
    }
    ps_call = next(
        args for args, _timeout in runner.calls if args[0].lower() == "powershell.exe"
    )
    target_index = ps_call.index("-Targets")
    assert ps_call[target_index + 1] == "192.168.50.1"
    assert runner.script_text == scripts.ARP_CACHE_WARMING
    assert "192.168.50.1" not in runner.script_text


def test_discovery_falls_back_to_the_local_slash_24_for_large_prefix(
    snapshot_factory, tmp_path
):
    snapshot = _snapshot(
        snapshot_factory,
        [_adapter("Ethernet")],
        [_address("10.20.30.5", 8, "Ethernet")],
        gateway="10.20.30.1",
    )
    discovery, runner = _discovery(tmp_path)

    discovery.discover(snapshot)

    hosts = _ping_hosts(runner)
    assert len(hosts) == 253
    assert all(host.startswith("10.20.30.") for host in hosts)
    assert "10.0.0.1" not in hosts


def test_discovery_caps_targets_at_1024_and_workers_at_64(
    snapshot_factory, tmp_path
):
    names_and_ips = [
        ("Ethernet 1", "10.0.1.1"),
        ("Ethernet 2", "10.1.1.1"),
        ("Ethernet 3", "10.2.1.1"),
        ("Ethernet 4", "10.3.1.1"),
        ("Ethernet 5", "172.16.1.1"),
    ]
    snapshot = _snapshot(
        snapshot_factory,
        [_adapter(name) for name, _ip in names_and_ips],
        [_address(ip, 16, name) for name, ip in names_and_ips],
    )
    runner = DiscoveryRunner(delay=0.002)
    discovery, _runner = _discovery(tmp_path, runner)

    discovery.discover(snapshot)

    assert len(_ping_hosts(runner)) == 1024
    assert runner.max_active_pings <= 64
    assert runner.max_active_pings > 1


def test_discovery_caches_results_for_fifteen_seconds(snapshot_factory, tmp_path):
    snapshot = _snapshot(
        snapshot_factory,
        [_adapter("Ethernet")],
        [_address("192.168.1.2", 30, "Ethernet")],
        gateway="192.168.1.1",
    )
    current_time = [20.0]
    discovery, runner = _discovery(
        tmp_path,
        clock=lambda: current_time[0],
    )

    first = discovery.discover(snapshot)
    call_count = len(runner.calls)
    current_time[0] += 14.0
    cached = discovery.discover(snapshot)

    assert cached == first
    assert len(runner.calls) == call_count

    current_time[0] += 2.0
    discovery.discover(snapshot)
    assert len(runner.calls) > call_count


def test_discovery_reports_arp_collection_failure(snapshot_factory, tmp_path):
    class FailedArpRunner(DiscoveryRunner):
        def run(self, args, *, timeout=None, **kwargs):
            if str(args[0]).lower() == "arp":
                argv = tuple(str(part) for part in args)
                self.calls.append((argv, timeout))
                return CommandResult(argv, 1, stderr="ARP unavailable")
            return super().run(args, timeout=timeout, **kwargs)

    snapshot = _snapshot(
        snapshot_factory,
        [_adapter("Ethernet")],
        [_address("192.168.1.2", 30, "Ethernet")],
    )
    discovery, _runner = _discovery(tmp_path, FailedArpRunner())

    with pytest.raises(RuntimeError, match="ARP"):
        discovery.discover(snapshot)


def test_discovery_formats_devices_and_routes_operations_through_runner(
    snapshot_factory, tmp_path
):
    adapters = [
        _adapter("Ethernet", PermanentAddress="3C-22-FB-AA-BB-CC"),
        _adapter(
            "Wi-Fi",
            mac="02-11-22-33-44-55",
            PermanentAddress=None,
        ),
    ]
    addresses = [
        _address("192.168.1.10", 29, "Ethernet"),
        _address("10.0.0.2", 29, "Wi-Fi"),
    ]
    arp_output = """
Interface: 192.168.1.10 --- 0x5
  192.168.1.9          00-00-0c-00-00-01     dynamic
  192.168.1.11         02-11-22-33-44-66     dynamic
  192.168.1.12         00-00-0c-00-00-02     dynamic
  192.168.1.13         00-17-f2-aa-bb-cc     dynamic
Interface: 172.16.0.1 --- 0x6
  192.168.1.14         00-00-0c-00-00-03     dynamic
Interface: 10.0.0.2 --- 0x7
  10.0.0.1             00-00-0c-00-00-04     dynamic
"""
    runner = DiscoveryRunner(
        arp_output=arp_output,
        nbt_names={"192.168.1.9": "gateway"},
        dns_names={"192.168.1.11": "randomized-client.local"},
    )
    discovery, _runner = _discovery(tmp_path, runner)
    snapshot = _snapshot(
        snapshot_factory,
        adapters,
        addresses,
        gateway="192.168.1.9",
    )

    devices = discovery.discover(snapshot)
    by_ip = {device["ip"]: device for device in devices}

    assert by_ip["192.168.1.9"]["connection"] == "Router"
    assert by_ip["192.168.1.9"]["vendor"] == "Cisco Systems, Inc"
    assert by_ip["192.168.1.11"]["mac"] == "02:11:22:33:44:66"
    assert by_ip["192.168.1.11"]["name"] == "randomized-client.local"
    assert by_ip["192.168.1.11"]["connection"] == "Wireless"
    assert by_ip["192.168.1.11"]["mac_randomized"] is True
    assert "randomized MAC" in by_ip["192.168.1.11"]["mac_note"]
    assert by_ip["192.168.1.12"]["connection"] == "Wired"
    assert by_ip["192.168.1.13"]["vendor"] == "Apple, Inc."
    assert by_ip["192.168.1.13"]["connection"] == "Wireless"
    assert by_ip["192.168.1.14"]["connection"] == "Unknown"
    assert by_ip["10.0.0.1"]["connection"] == "Wireless"

    local_ethernet = by_ip["192.168.1.10"]
    assert local_ethernet["type"] == "local"
    assert local_ethernet["connection"] == "This PC"
    assert local_ethernet["hardware_mac"] == "3c:22:fb:aa:bb:cc"
    assert local_ethernet["mac_randomized"] is False
    local_wifi = by_ip["10.0.0.2"]
    assert local_wifi["connection"] == "This PC"
    assert local_wifi["mac_randomized"] is True

    command_names = {args[0].lower() for args, _timeout in runner.calls}
    assert {"ping", "arp", "nbtstat", "nslookup", "powershell.exe"} <= command_names
    assert all(timeout is not None for _args, timeout in runner.calls)


def test_adapter_snapshot_query_includes_permanent_mac_address():
    assert "PermanentAddress" in scripts.ADAPTERS
