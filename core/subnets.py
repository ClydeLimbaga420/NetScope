"""Private LAN subnet helpers shared by snapshot collection and checks."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

_VIRTUAL_HINTS = (
    "hyper-v",
    "vethernet",
    "vmware",
    "virtualbox",
    "wsl",
    "vpn",
    "tap",
    "wireguard",
    "tailscale",
    "zerotier",
    "docker",
    "bluetooth",
    "wi-fi direct",
    "local area connection*",
    "npcap",
    "loopback",
)


@dataclass(frozen=True)
class RemoteSubnet:
    network: str
    next_hop: str | None
    interface_alias: str
    metric: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "next_hop": self.next_hop,
            "interface_alias": self.interface_alias,
            "metric": self.metric,
        }


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _network(address: Any, prefix: Any) -> ipaddress.IPv4Network | None:
    try:
        parsed = ipaddress.ip_network(f"{_text(address).strip()}/{int(prefix)}", strict=False)
    except (ValueError, TypeError):
        return None
    return parsed if parsed.version == 4 else None


def _is_virtual_alias(alias: str) -> bool:
    haystack = alias.lower()
    return any(hint in haystack for hint in _VIRTUAL_HINTS)


def local_networks(ip_rows: list[dict[str, Any]]) -> list[ipaddress.IPv4Network]:
    networks: list[ipaddress.IPv4Network] = []
    for row in ip_rows or []:
        network = _network(row.get("IPAddress"), row.get("PrefixLength"))
        if network is None or network.is_loopback or network.is_link_local:
            continue
        if network not in networks:
            networks.append(network)
    return networks


def remote_lan_routes(
    ip_rows: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
) -> list[RemoteSubnet]:
    """Return private subnets that are not local but have a LAN route."""

    locals_ = local_networks(ip_rows)
    best: dict[str, tuple[int, RemoteSubnet]] = {}
    for row in route_rows or []:
        prefix = _text(row.get("DestinationPrefix")).strip()
        if not prefix:
            continue
        try:
            network = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        if network.version != 4 or not network.is_private:
            continue
        if network.is_loopback or network.is_link_local or network.is_unspecified or network.is_multicast:
            continue
        if any(network.overlaps(local) for local in locals_):
            continue
        alias = _text(row.get("InterfaceAlias"))
        if _is_virtual_alias(alias):
            continue
        try:
            metric = int(row.get("InterfaceMetric") or 0) + int(row.get("RouteMetric") or 0)
        except (TypeError, ValueError):
            metric = 9999
        next_hop = _text(row.get("NextHop")).strip() or None
        if next_hop == "0.0.0.0":
            next_hop = None
        candidate = RemoteSubnet(str(network), next_hop, alias, metric)
        key = str(network)
        current = best.get(key)
        if current is None or metric < current[0]:
            best[key] = (metric, candidate)
    return [item for _, item in sorted(best.values(), key=lambda pair: pair[1].network)]
