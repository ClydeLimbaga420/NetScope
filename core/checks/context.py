"""Shared check context and small parsing helpers."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.models import CheckResult, Layer, Status
from core.probes import NetworkProbe
from core.snapshot import Snapshot


@dataclass
class CheckContext:
    snapshot: Snapshot
    probe: NetworkProbe
    logger: Any | None = None
    hosts_path: Path | None = None

    @property
    def is_windows(self) -> bool:
        return self.snapshot.is_windows


def skipped(layer: Layer, check_id: str, title: str, reason: str) -> CheckResult:
    return CheckResult(
        id=check_id,
        layer=layer,
        status=Status.SKIP,
        title=title,
        message=reason,
    )


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "enabled"}


def row_state(row: dict[str, Any]) -> str:
    return text(row.get("State") or row.get("Status")).strip().lower()


def is_running(row: dict[str, Any]) -> bool:
    return row_state(row) == "running"


def start_mode(row: dict[str, Any]) -> str:
    return text(row.get("StartMode") or row.get("StartType")).strip().lower()


def service_map(snapshot: Snapshot) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in snapshot.section("services"):
        name = text(row.get("Name"))
        if name:
            mapping[name.lower()] = row
    return mapping


def parse_speed_mbps(value: Any) -> float | None:
    raw = text(value).strip().lower().replace(",", ".")
    if not raw:
        return None
    import re

    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(gbps|mbps|kbps)", raw)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "gbps":
        return number * 1000
    if unit == "kbps":
        return number / 1000
    return number


def as_network(address: str, prefix: Any) -> Any | None:
    try:
        return ipaddress.ip_network(f"{address}/{int(prefix)}", strict=False)
    except (ValueError, TypeError):
        return None


def interface_ipv4(snapshot: Snapshot) -> list[dict[str, Any]]:
    rows = snapshot.section("ip_addresses")
    usable = []
    for row in rows:
        address = text(row.get("IPAddress"))
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if parsed.version != 4 or parsed.is_loopback:
            continue
        usable.append(row)
    return usable


def configured_dns_servers(snapshot: Snapshot) -> list[str]:
    servers: list[str] = []
    for row in snapshot.section("dns_servers"):
        raw = row.get("ServerAddresses")
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            value = text(value).strip()
            if not value or value == "::1":
                continue
            try:
                ipaddress.ip_address(value)
            except ValueError:
                continue
            if value not in servers:
                servers.append(value)
    return servers
