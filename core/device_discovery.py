"""Bounded local-network device discovery using the shared command runner."""

from __future__ import annotations

import copy
import ipaddress
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from core.native import ping_args
from core.runner import CommandResult
from core.snapshot import Snapshot
from core.vendors import load_oui_vendors, lookup_vendor
from powershell import scripts
from powershell.validation import validate_ip

SCAN_CACHE_SECONDS = 15.0
SCAN_MAX_HOSTS = 1024
SCAN_MAX_WORKERS = 64
SCAN_PING_TIMEOUT_SECONDS = 1.5
SCAN_PING_TIMEOUT_MS = 500
ARP_TIMEOUT_SECONDS = 3.0
NAME_RESOLVE_TIMEOUT_SECONDS = 1.5
NAME_RESOLVE_MAX_WORKERS = 10
SCAN_PORT = 33434

VIRTUAL_INTERFACE_HINTS = (
    "bluetooth",
    "hyper-v",
    "isatap",
    "loopback",
    "npcap",
    "tailscale",
    "tap-",
    "teredo",
    "tunnel",
    "vethernet",
    "virtualbox",
    "vmware",
    "vpn",
    "wireguard",
    "wintun",
    "wsl",
    "zerotier",
)
WIFI_INTERFACE_HINTS = ("wi-fi", "wifi", "wireless", "wlan", "802.11")
WIRELESS_VENDOR_HINTS = (
    "apple",
    "samsung",
    "xiaomi",
    "huawei",
    "honor",
    "oneplus",
    "oppo",
    "vivo",
    "realme",
    "google",
    "motorola",
    "lg electronics",
    "nintendo",
    "amazon",
    "roku",
    "sonos",
    "espressif",
    "tuya",
    "ring llc",
    "nest labs",
    "tcl",
    "hisense",
    "vizio",
    "nothing technology",
)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_mac(value: Any) -> str | None:
    digits = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(digits) != 12:
        return None
    return ":".join(digits[index : index + 2] for index in range(0, 12, 2)).lower()


def _locally_administered(mac: str | None) -> bool:
    if not mac:
        return False
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


def _usable_private_ipv4(value: Any) -> ipaddress.IPv4Address | None:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return None
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return None
    return address


def _virtual_adapter(adapter: dict[str, Any]) -> bool:
    if _truthy(adapter.get("Virtual")):
        return True
    label = " ".join(
        str(adapter.get(key) or "")
        for key in ("Name", "InterfaceAlias", "InterfaceDescription")
    ).lower()
    return any(hint in label for hint in VIRTUAL_INTERFACE_HINTS)


def _wireless_interface(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in WIFI_INTERFACE_HINTS)


def _clean_name(value: str | None, ip: str) -> str | None:
    name = (value or "").strip().rstrip(".")
    if not name or name.lower() in {"unknown", "localhost"} or name == ip:
        return None
    if re.fullmatch(r"[\d.]+", name):
        return None
    return name


def _vendor_for_mac(mac: str | None, mapping: dict[str, str]) -> str | None:
    if _locally_administered(mac):
        return "Private MAC"
    return lookup_vendor(mac, mapping)


def _in_networks(ip: str, networks: list[ipaddress.IPv4Network]) -> bool:
    address = ipaddress.IPv4Address(ip)
    return any(address in network for network in networks)


def _parse_arp(
    output: str,
    networks: list[ipaddress.IPv4Network],
    vendor_mapping: dict[str, str],
) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    seen: set[str] = set()
    interface_ip: str | None = None
    windows_header = re.compile(
        r"^\s*Interface:\s*([0-9.]+)\s+---\s+0x[0-9a-f]+",
        re.I,
    )
    windows_entry = re.compile(
        r"^\s*([0-9.]+)\s+([0-9a-fA-F:-]{17})\s+(\w+)\s*$"
    )
    unix_entry = re.compile(
        r"\((?P<ip>[0-9.]+)\)\s+at\s+(?P<mac>[0-9a-fA-F:]{17})",
        re.I,
    )

    for line in (output or "").splitlines():
        header = windows_header.search(line)
        if header:
            interface_ip = header.group(1)
            continue
        windows = windows_entry.match(line)
        unix = unix_entry.search(line) if not windows else None
        if windows:
            ip, raw_mac, entry_type = windows.groups()
        elif unix:
            ip, raw_mac = unix.group("ip"), unix.group("mac")
            entry_type = "arp"
        else:
            continue
        address = _usable_private_ipv4(ip)
        mac = _normalize_mac(raw_mac)
        if (
            address is None
            or mac is None
            or str(address) in seen
            or not _in_networks(str(address), networks)
        ):
            continue
        seen.add(str(address))
        devices.append(
            {
                "name": None,
                "ip": str(address),
                "mac": mac,
                "type": entry_type.lower(),
                "vendor": _vendor_for_mac(mac, vendor_mapping),
                "interface_ip": interface_ip,
            }
        )
    return devices


def _local_context(snapshot: Snapshot):
    adapter_by_alias: dict[str, dict[str, Any]] = {}
    for row in snapshot.section("adapters"):
        alias = str(row.get("InterfaceAlias") or row.get("Name") or "").strip()
        if (
            not alias
            or str(row.get("Status") or "").strip().lower() != "up"
            or _virtual_adapter(row)
        ):
            continue
        adapter_by_alias[alias.lower()] = row

    context: dict[str, Any] = {
        "own_ips": set(),
        "own_macs": set(),
        "interfaces": {},
        "adapters": [],
    }
    networks: dict[str, ipaddress.IPv4Network] = {}
    for row in snapshot.section("ip_addresses"):
        alias = str(row.get("InterfaceAlias") or "").strip().lower()
        adapter = adapter_by_alias.get(alias)
        if adapter is None:
            continue
        address = _usable_private_ipv4(row.get("IPAddress"))
        try:
            prefix = int(row.get("PrefixLength"))
        except (TypeError, ValueError):
            continue
        if address is None or not 0 <= prefix <= 32:
            continue
        network = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
        if (
            network.is_loopback
            or network.is_link_local
            or not network.is_private
            or network.is_multicast
        ):
            continue
        if network.num_addresses > SCAN_MAX_HOSTS + 2:
            network = ipaddress.IPv4Network(f"{address}/24", strict=False)
        networks[str(network)] = network

        current_mac = _normalize_mac(adapter.get("MacAddress"))
        permanent_mac = _normalize_mac(adapter.get("PermanentAddress"))
        if _locally_administered(permanent_mac):
            permanent_mac = None
        context["own_ips"].add(str(address))
        for mac in (current_mac, permanent_mac):
            if mac:
                context["own_macs"].add(mac)
        name = str(adapter.get("Name") or adapter.get("InterfaceAlias") or alias)
        context["interfaces"][str(address)] = {
            "name": name,
            "wireless": _wireless_interface(name),
        }
        context["adapters"].append(
            {
                "name": name,
                "ip": str(address),
                "mac": current_mac,
                "hardware_mac": permanent_mac,
                "wireless": _wireless_interface(name),
            }
        )

    target_networks = sorted(networks.values(), key=lambda network: (int(network.network_address), network.prefixlen))
    targets: list[str] = []
    for network in target_networks:
        for host in network.hosts():
            candidate = str(host)
            if candidate in context["own_ips"]:
                continue
            targets.append(candidate)
            if len(targets) >= SCAN_MAX_HOSTS:
                return targets, target_networks, context
    return targets, target_networks, context


def _classify_connection(
    device: dict[str, Any], context: dict[str, Any], gateway: str | None
) -> tuple[str, str]:
    ip = device.get("ip")
    mac = _normalize_mac(device.get("mac"))
    interface = context["interfaces"].get(device.get("interface_ip"))

    if ip in context["own_ips"] or (mac and mac in context["own_macs"]):
        return "This PC", "Address belongs to a local adapter"
    if gateway and ip == gateway:
        return "Router", "Default gateway of this PC"
    if interface and interface["wireless"]:
        return "Wireless", "Reached through the Wi-Fi adapter"
    if _locally_administered(mac):
        return "Wireless", "Randomized (private) MAC, typical of Wi-Fi devices"
    vendor = str(device.get("vendor") or "").lower()
    if any(hint in vendor for hint in WIRELESS_VENDOR_HINTS):
        return "Wireless", "Mobile or IoT vendor commonly seen on Wi-Fi"
    if interface:
        return "Wired", "Reached through an Ethernet adapter"
    return "Unknown", "Connection type could not be determined"


def _add_local_devices(devices: list[dict[str, Any]], context: dict[str, Any]) -> None:
    by_ip = {device["ip"]: device for device in devices}
    for adapter in context["adapters"]:
        existing = by_ip.get(adapter["ip"])
        if existing is not None:
            existing["hardware_mac"] = adapter["hardware_mac"]
            continue
        mac = adapter["hardware_mac"] or adapter["mac"]
        if not mac:
            continue
        devices.append(
            {
                "name": adapter["name"],
                "ip": adapter["ip"],
                "mac": mac,
                "type": "local",
                "vendor": None,
                "interface_ip": adapter["ip"],
                "hardware_mac": adapter["hardware_mac"],
            }
        )


def _add_mac_notes(devices: list[dict[str, Any]]) -> None:
    for device in devices:
        hardware_mac = _normalize_mac(device.get("hardware_mac"))
        if _locally_administered(hardware_mac):
            hardware_mac = None
        mac = _normalize_mac(device.get("mac"))
        displayed_mac = hardware_mac or mac
        randomized = _locally_administered(displayed_mac)
        device["mac"] = mac
        device["hardware_mac"] = hardware_mac
        device["mac_randomized"] = randomized
        if hardware_mac:
            device["mac_note"] = "Hardware MAC of this PC"
        elif randomized:
            device["mac_note"] = (
                "Hardware MAC hidden: the device uses a randomized MAC"
            )
        else:
            device["mac_note"] = "MAC reported on the local network"


def _netbios_name(output: str, ip: str) -> str | None:
    for line in (output or "").splitlines():
        match = re.match(r"\s*(.+?)\s+<\w+>\s+(?:UNIQUE|GROUP)\b", line, re.I)
        if match:
            name = _clean_name(match.group(1), ip)
            if name:
                return name
    return None


def _nslookup_name(output: str, ip: str) -> str | None:
    match = re.search(r"^\s*Name:\s*(\S+)", output or "", re.I | re.M)
    return _clean_name(match.group(1), ip) if match else None


def _command_error(result: CommandResult, operation: str) -> RuntimeError:
    detail = result.error or result.stderr.strip() or f"exit code {result.returncode}"
    if result.timed_out:
        detail = "command timed out"
    return RuntimeError(f"{operation}: {detail}")


class DeviceDiscovery:
    def __init__(
        self,
        runner: Any,
        ps: Any,
        logger: Any | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.runner = runner
        self.ps = ps
        self.logger = logger
        self.clock = clock
        self.oui_vendors = load_oui_vendors()
        if self.logger is not None:
            self.logger.event(
                "oui_map_loaded",
                prefix_count=len(self.oui_vendors),
            )
        self._scan_lock = threading.Lock()
        self._cached_at: float | None = None
        self._cached_devices: list[dict[str, Any]] | None = None

    def _warm_arp_cache(self, targets: list[str]) -> None:
        if not self.ps:
            raise RuntimeError("PowerShell layer is required to warm the ARP cache")
        safe_targets = [validate_ip(target) for target in targets]
        result = self.ps.run_script_text(
            scripts.ARP_CACHE_WARMING,
            {"Targets": ",".join(safe_targets)},
            timeout=10.0,
        )
        if not result.ok:
            raise _command_error(result, "ARP cache warming failed")

    def _ping_host(self, host: str) -> None:
        if os.name == "nt":
            args = ["ping", "-n", "1", "-w", str(SCAN_PING_TIMEOUT_MS), host]
        else:
            args = ["ping", "-c", "1", "-W", "1", host]
        result = self.runner.run(args, timeout=SCAN_PING_TIMEOUT_SECONDS)
        if result.timed_out or result.error:
            raise _command_error(result, f"ping failed for {host}")

    def _probe_hosts(self, targets: list[str]) -> None:
        if not targets:
            return
        with ThreadPoolExecutor(max_workers=min(SCAN_MAX_WORKERS, len(targets))) as pool:
            list(pool.map(self._ping_host, targets))

    def _read_arp(self) -> str:
        result = self.runner.run(["arp", "-a"], timeout=ARP_TIMEOUT_SECONDS)
        if not result.ok:
            raise _command_error(result, "ARP table read failed")
        return result.stdout

    def _resolve_name(self, device: dict[str, Any], is_windows: bool) -> str | None:
        ip = validate_ip(device["ip"])
        if is_windows:
            result = self.runner.run(
                ["nbtstat", "-A", ip],
                timeout=NAME_RESOLVE_TIMEOUT_SECONDS,
            )
            if result.error or result.timed_out:
                raise _command_error(result, f"NetBIOS lookup failed for {ip}")
            name = _netbios_name(result.stdout, ip)
            if name:
                return name
        result = self.runner.run(
            ["nslookup", "-timeout=1", "-retry=0", ip],
            timeout=NAME_RESOLVE_TIMEOUT_SECONDS,
        )
        if result.error or result.timed_out:
            raise _command_error(result, f"reverse DNS lookup failed for {ip}")
        return _nslookup_name(result.stdout, ip)

    def _resolve_names(self, devices: list[dict[str, Any]], is_windows: bool) -> None:
        pending = [device for device in devices if not device.get("name") and device.get("type") != "local"]
        if not pending:
            return
        with ThreadPoolExecutor(
            max_workers=min(NAME_RESOLVE_MAX_WORKERS, len(pending))
        ) as pool:
            futures = {
                pool.submit(self._resolve_name, device, is_windows): device
                for device in pending
            }
            for future, device in futures.items():
                device["name"] = future.result()

    def discover(
        self,
        snapshot: Snapshot,
        *,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        with self._scan_lock:
            now = self.clock()
            if (
                not force
                and self._cached_devices is not None
                and self._cached_at is not None
                and now - self._cached_at < SCAN_CACHE_SECONDS
            ):
                return copy.deepcopy(self._cached_devices)

            targets, networks, context = _local_context(snapshot)
            if targets:
                self._warm_arp_cache(targets)
                self._probe_hosts(targets)
            entries = _parse_arp(
                self._read_arp(),
                networks,
                self.oui_vendors,
            )
            entries = [
                device
                for device in entries
                if device["ip"] not in context["own_ips"]
            ]
            _add_local_devices(entries, context)
            for device in entries:
                if device.get("type") != "local":
                    device["vendor"] = _vendor_for_mac(
                        device.get("mac"),
                        self.oui_vendors,
                    )
                label, detail = _classify_connection(device, context, snapshot.gateway)
                device["connection"] = label
                device["connection_detail"] = detail
            _add_mac_notes(entries)
            self._resolve_names(entries, snapshot.is_windows)
            entries.sort(
                key=lambda item: tuple(int(part) for part in item["ip"].split("."))
            )

            self._cached_at = now
            self._cached_devices = copy.deepcopy(entries)
            return entries
