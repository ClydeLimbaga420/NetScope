"""Suggest a default gateway from the adapter's own network.

Detection is read-only. The actual change is the catalog fix ``IP-09`` and runs
through :class:`fixes.executor.FixExecutor`, so it keeps the same preview,
confirmation, snapshot and rollback path as every other repair.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any

from core.checks.context import text, truthy
from core.native import parse_ping, ping_args
from core.snapshot import Snapshot

_VIRTUAL_HINTS = (
    "hyper-v",
    "vethernet",
    "virtual",
    "vmware",
    "virtualbox",
    "wsl",
    "loopback",
    "tap",
    "wireguard",
    "tailscale",
    "zerotier",
    "vpn",
    "docker",
    "bluetooth",
    "wi-fi direct",
    "local area connection*",
    "npcap",
)

_DHCP_QUERY = (
    "Get-CimInstance -ClassName Win32_NetworkAdapterConfiguration "
    "-ErrorAction SilentlyContinue | "
    "Select-Object InterfaceIndex,DHCPEnabled,DHCPServer,DefaultIPGateway,IPAddress"
)

_ARP_STATES = {"reachable", "permanent"}


@dataclass
class GatewayCandidate:
    host: str
    source: str
    reason: str = ""
    priority: int = 0
    reachable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "source": self.source,
            "reason": self.reason,
            "priority": self.priority,
            "reachable": self.reachable,
        }


@dataclass
class GatewaySuggestion:
    adapter: str = ""
    address: str | None = None
    prefix: int | None = None
    network: str | None = None
    gateway: str | None = None
    source: str | None = None
    reachable: bool = False
    note: str = ""
    candidates: list[GatewayCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "address": self.address,
            "prefix": self.prefix,
            "network": self.network,
            "gateway": self.gateway,
            "source": self.source,
            "reachable": self.reachable,
            "note": self.note,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _is_virtual(row: dict[str, Any]) -> bool:
    if truthy(row.get("Virtual")):
        return True
    haystack = f"{text(row.get('Name'))} {text(row.get('InterfaceDescription'))}".lower()
    return any(hint in haystack for hint in _VIRTUAL_HINTS)


def default_route_gateway(snapshot: Snapshot) -> str | None:
    """Return the next hop of any usable IPv4 default route, if one exists."""

    for row in snapshot.section("routes"):
        if text(row.get("DestinationPrefix")).strip() != "0.0.0.0/0":
            continue
        next_hop = text(row.get("NextHop")).strip()
        if next_hop and next_hop != "0.0.0.0":
            return next_hop
    return None


def has_default_route(snapshot: Snapshot) -> bool:
    return default_route_gateway(snapshot) is not None


def _has_gateway(snapshot: Snapshot, alias: str) -> bool:
    needle = alias.strip().lower()
    for row in snapshot.section("ip_configuration"):
        if text(row.get("InterfaceAlias")).strip().lower() != needle:
            continue
        gateway = row.get("IPv4Gateway")
        if isinstance(gateway, list):
            gateway = gateway[0] if gateway else None
        value = text(gateway).strip()
        if value and value != "0.0.0.0":
            return True
    for row in snapshot.section("routes"):
        if text(row.get("InterfaceAlias")).strip().lower() != needle:
            continue
        if text(row.get("DestinationPrefix")).strip() != "0.0.0.0/0":
            continue
        if text(row.get("NextHop")).strip() not in {"", "0.0.0.0"}:
            return True
    return False


def active_target(snapshot: Snapshot, preferred: str | None = None) -> dict[str, Any] | None:
    """Return the adapter/address pair to configure.

    A wired or wireless adapter that is up, has a usable IPv4 address and no
    default gateway is preferred. An explicit ``preferred`` adapter name wins.
    """

    adapters: dict[str, dict[str, Any]] = {}
    for row in snapshot.section("adapters"):
        for key in (
            text(row.get("Name")),
            text(row.get("InterfaceAlias")),
        ):
            if key:
                adapters.setdefault(key.strip().lower(), row)

    addresses: dict[str, dict[str, Any]] = {}
    for row in snapshot.section("ip_addresses"):
        address = text(row.get("IPAddress")).strip()
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if parsed.version != 4 or parsed.is_loopback or address.startswith("169.254."):
            continue
        if text(row.get("AddressState")).strip().lower() == "duplicate":
            continue
        alias = text(row.get("InterfaceAlias")).strip()
        if not alias:
            continue
        adapter = adapters.get(alias.lower())
        if adapter is None:
            continue
        if text(adapter.get("Status")).strip().lower() != "up":
            continue
        if _is_virtual(adapter):
            continue
        addresses.setdefault(alias.lower(), row)

    entries: list[dict[str, Any]] = []
    for key, address_row in addresses.items():
        adapter = adapters[key]
        alias = text(address_row.get("InterfaceAlias")) or text(adapter.get("Name"))
        entries.append({"adapter": adapter, "address": address_row, "alias": alias})

    if preferred:
        needle = preferred.strip().lower()
        for entry in entries:
            if needle in {
                text(entry["adapter"].get("Name")).strip().lower(),
                text(entry["adapter"].get("InterfaceAlias")).strip().lower(),
                entry["alias"].strip().lower(),
            }:
                return entry
        return None

    for entry in entries:
        if not _has_gateway(snapshot, entry["alias"]):
            return entry
    return entries[0] if entries else None


def _dhcp_info(
    snapshot: Snapshot,
    ps: Any | None,
    interface_index: Any,
    address: str,
) -> tuple[str | None, list[str]]:
    if ps is None or not snapshot.ps_available or snapshot.constrained:
        return None, []
    try:
        data = ps.run_json(_DHCP_QUERY)
    except Exception:
        return None, []

    rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    match: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if interface_index is not None and str(row.get("InterfaceIndex")) == str(interface_index):
            match = row
            break
        values = row.get("IPAddress")
        values = values if isinstance(values, list) else ([values] if values else [])
        if address and address in {text(item).strip() for item in values}:
            match = row
            break
    if match is None and len(rows) == 1 and isinstance(rows[0], dict):
        match = rows[0]
    if match is None:
        return None, []

    server = match.get("DHCPServer")
    if isinstance(server, list):
        server = server[0] if server else None
    server_text = text(server).strip() or None

    gateways = match.get("DefaultIPGateway")
    gateways = gateways if isinstance(gateways, list) else ([gateways] if gateways else [])
    return server_text, [text(item).strip() for item in gateways if text(item).strip()]


def _add_candidate(
    candidates: dict[str, GatewayCandidate],
    host: Any,
    source: str,
    reason: str,
    priority: int,
    network: ipaddress.IPv4Network,
    own_address: str,
) -> None:
    value = text(host).strip()
    if not value:
        return
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return
    if parsed.version != 4 or parsed not in network:
        return
    if value == own_address or parsed in {network.network_address, network.broadcast_address}:
        return
    existing = candidates.get(value)
    if existing is not None:
        if priority > existing.priority:
            existing.source = source
            existing.reason = reason
            existing.priority = priority
        return
    candidates[value] = GatewayCandidate(host=value, source=source, reason=reason, priority=priority)


def _neighbor_states(snapshot: Snapshot) -> dict[str, str]:
    states: dict[str, str] = {}
    for row in snapshot.section("neighbors"):
        address = text(row.get("IPAddress")).strip()
        state = text(row.get("State")).strip().lower()
        mac = text(row.get("LinkLayerAddress")).strip()
        if address and state and mac and mac not in {"00-00-00-00-00-00", "00:00:00:00:00:00"}:
            states[address] = state
    return states


def detect_gateway(
    snapshot: Snapshot,
    adapter_name: str | None = None,
    runner: Any | None = None,
    ps: Any | None = None,
    *,
    ping_timeout: float = 1.0,
    max_candidates: int = 4,
) -> GatewaySuggestion:
    """Suggest the most likely gateway for the target adapter's subnet."""

    target = active_target(snapshot, adapter_name)
    if target is None:
        return GatewaySuggestion(
            adapter=adapter_name or "",
            note="No active wired or wireless adapter with a usable IPv4 address was found.",
        )

    alias = target["alias"]
    address_row = target["address"]
    address = text(address_row.get("IPAddress")).strip()
    try:
        prefix = int(address_row.get("PrefixLength"))
        network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
    except (TypeError, ValueError):
        prefix = None
        network = None

    result = GatewaySuggestion(adapter=alias, address=address, prefix=prefix)
    if network is None:
        result.note = "The adapter's IPv4 subnet could not be determined."
        return result
    result.network = str(network)

    candidates: dict[str, GatewayCandidate] = {}
    if_index = address_row.get("InterfaceIndex")

    dhcp_server, dhcp_gateways = _dhcp_info(snapshot, ps, if_index, address)
    if dhcp_server:
        _add_candidate(
            candidates,
            dhcp_server,
            "DHCP server",
            "Reported by the DHCP client for this adapter",
            6,
            network,
            address,
        )
    for gateway in dhcp_gateways:
        _add_candidate(
            candidates,
            gateway,
            "DHCP lease",
            "Gateway supplied in the DHCP lease",
            6,
            network,
            address,
        )

    for row in snapshot.section("ip_configuration"):
        gateway = row.get("IPv4Gateway")
        if isinstance(gateway, list):
            gateway = gateway[0] if gateway else None
        _add_candidate(
            candidates,
            gateway,
            "existing configuration",
            "Another adapter already uses this gateway",
            5,
            network,
            address,
        )

    for row in snapshot.section("routes"):
        if text(row.get("DestinationPrefix")).strip() != "0.0.0.0/0":
            continue
        _add_candidate(
            candidates,
            row.get("NextHop"),
            "default route",
            "Next hop already present in the route table",
            5,
            network,
            address,
        )

    first = network.network_address + 1
    last = network.broadcast_address - 1
    _add_candidate(
        candidates,
        str(first),
        "first address in subnet",
        "Most home and office routers use the first usable address",
        3,
        network,
        address,
    )
    _add_candidate(
        candidates,
        str(last),
        "last address in subnet",
        "Some routers use the last usable address",
        2,
        network,
        address,
    )
    octets = address.split(".")
    if len(octets) == 4:
        _add_candidate(
            candidates,
            f"{octets[0]}.{octets[1]}.{octets[2]}.1",
            "common router address",
            "Common router address on this /24",
            3,
            network,
            address,
        )
        _add_candidate(
            candidates,
            f"{octets[0]}.{octets[1]}.{octets[2]}.254",
            "common router address",
            "Common router address on this /24",
            2,
            network,
            address,
        )

    ordered = sorted(
        candidates.values(),
        key=lambda item: (-item.priority, ipaddress.ip_address(item.host)),
    )[:max_candidates]

    if runner is not None:
        for candidate in ordered:
            try:
                command = runner.run(
                    ping_args(candidate.host, ping_timeout),
                    timeout=ping_timeout + 2,
                )
                ping = parse_ping(
                    candidate.host,
                    (command.stdout or "") + (command.stderr or ""),
                    command.returncode,
                )
                candidate.reachable = ping.online
            except Exception:
                candidate.reachable = False

    states = _neighbor_states(snapshot)
    for candidate in ordered:
        if not candidate.reachable and states.get(candidate.host) in _ARP_STATES:
            candidate.reachable = True

    result.candidates = ordered
    reachable = [candidate for candidate in ordered if candidate.reachable]
    chosen = reachable[0] if reachable else (ordered[0] if ordered else None)
    if chosen is None:
        result.note = (
            "Could not derive a gateway from this adapter's address and subnet. "
            "Enter the router address manually."
        )
        return result

    result.gateway = chosen.host
    result.source = chosen.source
    result.reachable = chosen.reachable
    if chosen.reachable:
        result.note = f"Detected {chosen.host} from the {chosen.source}; it answered on the network."
    else:
        result.note = (
            f"No candidate answered a ping. {chosen.host} is the most likely gateway "
            f"({chosen.source}); verify it before applying."
        )
    return result
