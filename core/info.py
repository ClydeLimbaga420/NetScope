"""Build a plain-data network configuration view for ``netscope info``."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

from core.checks.context import configured_dns_servers, text, truthy
from core.native import (
    parse_arp,
    parse_mtu,
    parse_netsh_winhttp_proxy,
    parse_wlan_interfaces,
)
from core.snapshot import Snapshot


def _origin_label(origin: str) -> str:
    lowered = origin.strip().lower()
    labels = {
        "0": "Other",
        "1": "Manual",
        "2": "APIPA",
        "3": "DHCP",
        "4": "Router advertisement",
        "other": "Other",
        "manual": "Manual",
        "wellknown": "APIPA",
        "dhcp": "DHCP",
        "random": "Random",
    }
    return labels.get(lowered, origin or "Unknown")


def _address_state(value: Any) -> str:
    labels = {
        "0": "Invalid",
        "1": "Tentative",
        "2": "Duplicate",
        "3": "Deprecated",
        "4": "Preferred",
    }
    raw = text(value).strip().lower()
    return labels.get(raw, text(value) or "Unknown")


def _as_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    cleaned: list[str] = []
    for item in values:
        candidate = text(item).strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        cleaned.append(candidate)
    return cleaned


def build_info(snapshot: Snapshot, adapter: str | None = None) -> dict[str, Any]:
    """Return adapters, addressing, routing, proxy, VPN and Wi-Fi details."""

    adapters_rows = snapshot.section("adapters")
    ip_rows = snapshot.section("ip_addresses")
    config_rows = snapshot.section("ip_configuration")
    dns_rows = snapshot.section("dns_servers")
    routes = snapshot.section("routes")
    mtu_map = parse_mtu(snapshot.native_text("mtu_interfaces"))

    config_by_alias = {
        text(row.get("InterfaceAlias")).lower(): row for row in config_rows
    }
    dns_by_alias: dict[str, list[str]] = {}
    for row in dns_rows:
        alias = text(row.get("InterfaceAlias")).lower()
        dns_by_alias.setdefault(alias, []).extend(_as_values(row.get("ServerAddresses")))

    aliases: dict[str, dict[str, Any]] = {}
    for row in adapters_rows:
        name = text(row.get("Name"))
        alias = text(row.get("InterfaceAlias")) or name
        key = alias.lower()
        aliases[key] = {
            "name": name or alias,
            "alias": alias,
            "description": text(row.get("InterfaceDescription")),
            "status": text(row.get("Status")),
            "mac": text(row.get("MacAddress")),
            "link_speed": text(row.get("LinkSpeed")),
            "virtual": truthy(row.get("Virtual")),
            "ipv4": [],
            "gateway": None,
            "dns": dns_by_alias.get(key, []),
            "dhcp": None,
            "mtu": mtu_map.get(alias),
        }

    for row in ip_rows:
        alias = text(row.get("InterfaceAlias"))
        key = alias.lower()
        address = text(row.get("IPAddress"))
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if parsed.version != 4 or parsed.is_loopback:
            continue
        entry = aliases.setdefault(
            key,
            {
                "name": alias,
                "alias": alias,
                "description": "",
                "status": "Unknown",
                "mac": "",
                "link_speed": "",
                "virtual": False,
                "ipv4": [],
                "gateway": None,
                "dns": dns_by_alias.get(key, []),
                "dhcp": None,
                "mtu": mtu_map.get(alias),
            },
        )
        origin = text(row.get("PrefixOrigin"))
        entry["ipv4"].append(
            {
                "address": address,
                "prefix": row.get("PrefixLength"),
                "origin": _origin_label(origin),
                "state": _address_state(row.get("AddressState")),
            }
        )
        if entry["dhcp"] is None:
            entry["dhcp"] = _origin_label(origin)

    for entry in aliases.values():
        config = config_by_alias.get(entry["alias"].lower())
        if config:
            gateway = config.get("IPv4Gateway")
            if isinstance(gateway, list):
                gateway = gateway[0] if gateway else None
            entry["gateway"] = text(gateway) or None

    adapter_list = list(aliases.values())
    if adapter:
        needle = adapter.strip().lower()
        adapter_list = [
            entry
            for entry in adapter_list
            if needle in entry["name"].lower()
            or needle in entry["alias"].lower()
            or needle in entry["description"].lower()
        ]
        if not adapter_list:
            raise LookupError(adapter)
        allowed = {entry["alias"].lower() for entry in adapter_list}
        routes = [
            row
            for row in routes
            if text(row.get("InterfaceAlias")).lower() in allowed
        ]

    proxy_rows = snapshot.section("system_proxy")
    proxy_row = proxy_rows[0] if proxy_rows else {}
    wifi = parse_wlan_interfaces(snapshot.native_text("wlan_interfaces"))

    return {
        "hostname": socket.gethostname(),
        "captured_at": snapshot.captured_at,
        "gateway": snapshot.gateway,
        "adapters": sorted(adapter_list, key=lambda item: item["alias"].lower()),
        "routes": routes,
        "arp": parse_arp(snapshot.native_text("arp")),
        "dns_servers": configured_dns_servers(snapshot),
        "proxy": {
            "winhttp": parse_netsh_winhttp_proxy(snapshot.native_text("winhttp_proxy")),
            "user_enabled": truthy(proxy_row.get("ProxyEnable")),
            "user_server": text(proxy_row.get("ProxyServer")),
            "auto_config_url": text(proxy_row.get("AutoConfigURL")),
        },
        "vpn": snapshot.section("vpn_connections"),
        "wifi": wifi,
        "mtu": mtu_map,
    }
