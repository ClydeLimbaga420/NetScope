from __future__ import annotations

import importlib
import io
import threading
import time
from pathlib import Path

import pytest

from core.device_discovery import (
    DeviceDiscovery,
    _normalize_mac,
    _parse_dns_cache,
    _parse_nbt_cache,
    _ping_hostname,
    _wireless_interface,
)
from core.runner import CommandResult
from powershell import scripts
from powershell.runner import PowerShellLayer


def _vendors_module():
    if importlib.util.find_spec("core.vendors") is None:
        pytest.fail("core.vendors resource loader is not implemented")
    return importlib.import_module("core.vendors")


class _FakeVendorResource:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error

    def joinpath(self, name):
        assert name == "oui_vendors.json"
        return self

    def open(self, _mode, encoding):
        if self.error:
            raise self.error
        return io.StringIO(self.content)


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
    def __init__(
        self,
        *,
        arp_output="",
        nbt_names=None,
        dns_names=None,
        nbt_cache_output="",
        dns_cache_output="",
        ping_names=None,
        delay=0.0,
    ):
        self.arp_output = arp_output
        self.nbt_names = dict(nbt_names or {})
        self.dns_names = dict(dns_names or {})
        self.nbt_cache_output = nbt_cache_output
        self.dns_cache_output = dns_cache_output
        self.ping_names = dict(ping_names or {})
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
                if "-a" in argv:
                    ip = argv[-1]
                    name = self.ping_names.get(ip)
                    banner = (
                        f"Pinging {name} [{ip}] with 32 bytes of data:\n"
                        if name
                        else f"Pinging {ip} with 32 bytes of data:\n"
                    )
                    return CommandResult(argv, 0, stdout=banner)
                return CommandResult(argv, 1, stdout="Request timed out.")
            finally:
                with self.lock:
                    self.active_pings -= 1
        if executable == "arp":
            return CommandResult(argv, 0, stdout=self.arp_output)
        if executable == "nbtstat":
            if len(argv) > 1 and argv[1].lower() == "-c":
                return CommandResult(argv, 0, stdout=self.nbt_cache_output)
            name = self.nbt_names.get(argv[-1])
            output = f"{name} <00> UNIQUE Registered\n" if name else ""
            return CommandResult(argv, 0, stdout=output)
        if executable == "ipconfig":
            return CommandResult(argv, 0, stdout=self.dns_cache_output)
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


def test_name_lookup_timeout_falls_back_to_dns_and_never_aborts_scan(
    snapshot_factory, tmp_path
):
    class TimeoutNamesRunner(DiscoveryRunner):
        def run(self, args, *, timeout=None, **kwargs):
            argv = tuple(str(part) for part in args)
            if (
                argv[0].lower() in {"nbtstat", "nslookup"}
                and argv[-1] == "192.168.1.9"
            ):
                return CommandResult(
                    argv, 1, timed_out=True, error="command timed out"
                )
            return super().run(args, timeout=timeout, **kwargs)

    arp_output = """
Interface: 192.168.1.10 --- 0x5
  192.168.1.9          00-00-0c-00-00-01     dynamic
  192.168.1.11         00-00-0c-00-00-02     dynamic
"""
    runner = TimeoutNamesRunner(
        arp_output=arp_output,
        dns_names={"192.168.1.11": "client.local"},
    )
    discovery, _runner = _discovery(tmp_path, runner)
    snapshot = _snapshot(
        snapshot_factory,
        [_adapter("Ethernet")],
        [_address("192.168.1.10", 29, "Ethernet")],
    )

    devices = discovery.discover(snapshot)
    by_ip = {device["ip"]: device for device in devices}

    # A NetBIOS (and DNS) timeout leaves that device unnamed, not the scan failed.
    assert by_ip["192.168.1.9"]["name"] is None
    # Other devices still resolve despite one host's lookup failures.
    assert by_ip["192.168.1.11"]["name"] == "client.local"


def test_netbios_timeout_still_tries_reverse_dns(snapshot_factory, tmp_path):
    class NetbiosTimeoutRunner(DiscoveryRunner):
        def run(self, args, *, timeout=None, **kwargs):
            argv = tuple(str(part) for part in args)
            if argv[0].lower() == "nbtstat":
                return CommandResult(
                    argv, 1, timed_out=True, error="command timed out"
                )
            return super().run(args, timeout=timeout, **kwargs)

    arp_output = """
Interface: 192.168.1.10 --- 0x5
  192.168.1.9          00-00-0c-00-00-01     dynamic
"""
    runner = NetbiosTimeoutRunner(
        arp_output=arp_output,
        dns_names={"192.168.1.9": "router.local"},
    )
    discovery, _runner = _discovery(tmp_path, runner)
    snapshot = _snapshot(
        snapshot_factory,
        [_adapter("Ethernet")],
        [_address("192.168.1.10", 29, "Ethernet")],
    )

    devices = discovery.discover(snapshot)

    assert devices[0]["name"] == "router.local"
    assert any(args[0].lower() == "nslookup" for args, _ in runner.calls)


def test_ping_hostname_parser_reads_windows_and_linux_banners():
    assert _ping_hostname(
        "Pinging OFFICE-PC [192.168.1.9] with 32 bytes of data:\n", "192.168.1.9"
    ) == "OFFICE-PC"
    # Localized Windows text still carries the bracketed address.
    assert _ping_hostname(
        "Ping wird ausgefuehrt fuer PRINTER [192.168.1.11] mit 32 Bytes:\n",
        "192.168.1.11",
    ) == "PRINTER"
    assert _ping_hostname(
        "PING camera.local (192.168.1.12) 56(84) bytes of data.\n", "192.168.1.12"
    ) == "camera.local"
    # No reverse resolution: the banner echoes the IP, which must be ignored.
    assert _ping_hostname(
        "Pinging 192.168.1.9 with 32 bytes of data:\n", "192.168.1.9"
    ) is None
    assert _ping_hostname("", "192.168.1.9") is None


def test_ping_reverse_name_used_when_netbios_and_dns_are_silent(
    snapshot_factory, tmp_path
):
    arp_output = """
Interface: 192.168.1.10 --- 0x5
  192.168.1.9          00-00-0c-00-00-01     dynamic
"""
    # No NetBIOS answer, no DNS cache hint, no PTR record -- only ping -a
    # (the OS resolver, e.g. LLMNR/mDNS) knows the host name.
    runner = DiscoveryRunner(
        arp_output=arp_output,
        ping_names={"192.168.1.9": "living-room-tv"},
    )
    discovery, _runner = _discovery(tmp_path, runner)
    snapshot = _snapshot(
        snapshot_factory,
        [_adapter("Ethernet")],
        [_address("192.168.1.10", 29, "Ethernet")],
    )

    devices = discovery.discover(snapshot)

    assert devices[0]["name"] == "living-room-tv"
    assert any("-a" in args for args, _timeout in runner.calls)


def test_nbt_cache_parser_maps_private_addresses_to_names():
    output = """
    NetBIOS Remote Cache Name Table

    Name              Type       Host Address    Life [sec]
    ------------------------------------------------------------
    OFFICE-PC      <20>  UNIQUE          192.168.1.9        360
    PRINTER        <00>  GROUP           192.168.1.11       120
   STALE          <20>  UNIQUE          8.8.8.8            360
    """
    assert _parse_nbt_cache(output) == {
        "192.168.1.9": "OFFICE-PC",
        "192.168.1.11": "PRINTER",
    }


def test_dns_cache_parser_maps_a_records_to_names():
    output = """
    printer.local
    ----------------------------------------
    Record Name . . . . . : printer.local
    Record Type . . . . . : 1
    A (Host) Record . . . : 192.168.1.11
    camera.local
    ----------------------------------------
    Record Name . . . . . : camera.local
    A (Host) Record . . . : 192.168.1.12
    """
    assert _parse_dns_cache(output) == {
        "192.168.1.11": "printer.local",
        "192.168.1.12": "camera.local",
    }


def test_name_caches_label_devices_that_answer_no_direct_query(
    snapshot_factory, tmp_path
):
    arp_output = """
Interface: 192.168.1.10 --- 0x5
  192.168.1.9          00-00-0c-00-00-01     dynamic
  192.168.1.11         00-00-0c-00-00-02     dynamic
  192.168.1.12         00-00-0c-00-00-03     dynamic
"""
    runner = DiscoveryRunner(
        arp_output=arp_output,
        nbt_cache_output="OFFICE-PC <20> UNIQUE 192.168.1.9 360\n",
        dns_cache_output=(
            "Record Name . . . . . : printer.local\n"
            "A (Host) Record . . . : 192.168.1.11\n"
        ),
    )
    discovery, _runner = _discovery(tmp_path, runner)
    snapshot = _snapshot(
        snapshot_factory,
        [_adapter("Ethernet")],
        [_address("192.168.1.10", 29, "Ethernet")],
    )

    devices = discovery.discover(snapshot)
    by_ip = {device["ip"]: device for device in devices}

    assert by_ip["192.168.1.9"]["name"] == "OFFICE-PC"
    assert by_ip["192.168.1.11"]["name"] == "printer.local"
    assert by_ip["192.168.1.12"]["name"] is None
    assert {"nbtstat", "ipconfig"} <= {
        args[0].lower() for args, _timeout in runner.calls
    }


def test_direct_netbios_name_wins_over_a_stale_cache_hint(
    snapshot_factory, tmp_path
):
    arp_output = """
Interface: 192.168.1.10 --- 0x5
  192.168.1.9          00-00-0c-00-00-01     dynamic
"""
    runner = DiscoveryRunner(
        arp_output=arp_output,
        nbt_names={"192.168.1.9": "gateway"},
        nbt_cache_output="OLD-GATEWAY <20> UNIQUE 192.168.1.9 360\n",
    )
    discovery, _runner = _discovery(tmp_path, runner)
    snapshot = _snapshot(
        snapshot_factory,
        [_adapter("Ethernet")],
        [_address("192.168.1.10", 29, "Ethernet")],
    )

    devices = discovery.discover(snapshot)

    assert devices[0]["name"] == "gateway"


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


def test_wireless_interface_hints():
    assert _wireless_interface("Wi-Fi 2")
    assert _wireless_interface("WLAN")
    assert not _wireless_interface("Ethernet")


def test_mac_normalization_accepts_compact_and_dashed_addresses():
    assert _normalize_mac("3052CB020E0D") == "30:52:cb:02:0e:0d"
    assert _normalize_mac("DA-1E-6F-D1-02-33") == "da:1e:6f:d1:02:33"
    assert _normalize_mac("not-a-mac") is None


def test_oui_resource_resolves_vendor_from_normalized_mac():
    vendors = _vendors_module()

    assert vendors.load_oui_vendors()["00000C"] == "Cisco Systems, Inc"
    assert vendors.lookup_vendor("00-00-0C-12-34-56") == "Cisco Systems, Inc"


def test_vendor_resource_missing_file_is_reported(monkeypatch):
    vendors = _vendors_module()
    monkeypatch.setattr(
        vendors,
        "files",
        lambda _package: _FakeVendorResource(error=FileNotFoundError("missing")),
    )

    with pytest.raises(RuntimeError, match="OUI vendor resource"):
        vendors.load_oui_vendors()


def test_vendor_resource_malformed_json_is_reported(monkeypatch):
    vendors = _vendors_module()
    monkeypatch.setattr(
        vendors,
        "files",
        lambda _package: _FakeVendorResource(content="{not json"),
    )

    with pytest.raises(RuntimeError, match="OUI vendor resource"):
        vendors.load_oui_vendors()


def test_device_discovery_logs_loaded_oui_prefix_count(tmp_path):
    class RecordingLogger:
        def __init__(self):
            self.events = []

        def event(self, event, **fields):
            self.events.append((event, fields))

    runner = DiscoveryRunner()
    logger = RecordingLogger()
    DeviceDiscovery(runner, PowerShellLayer(runner, temp_root=tmp_path), logger)

    assert len(logger.events) == 1
    assert logger.events[0][0] == "oui_map_loaded"
    assert logger.events[0][1]["prefix_count"] > 0
