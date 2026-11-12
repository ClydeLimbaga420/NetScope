"""One-shot collection of machine state used by all checks.

The collector batches PowerShell queries into a single process start, then runs
the few native tools that have no good cmdlet. Checks are pure functions over
this immutable snapshot, which keeps the engine deterministic and testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import config
from core.models import utc_now
from core.native import PingResult, parse_default_gateway, parse_ping, ping_args
from core.runner import CommandRunner
from core.subnets import remote_lan_routes
from powershell import scripts
from powershell.runner import PowerShellLayer, as_list


@dataclass
class Snapshot:
    is_windows: bool
    language_mode: str = "Unknown"
    ps_available: bool = True
    constrained: bool = False
    data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    native: dict[str, Any] = field(default_factory=dict)
    pings: dict[str, PingResult] = field(default_factory=dict)
    gateway: str | None = None
    captured_at: str = field(default_factory=utc_now)

    def section(self, name: str) -> list[dict[str, Any]]:
        return list(self.data.get(name) or [])

    def native_text(self, name: str) -> str:
        result = self.native.get(name)
        if result is None:
            return ""
        return getattr(result, "stdout", "") or ""

    def native_ok(self, name: str) -> bool:
        result = self.native.get(name)
        return bool(result is not None and getattr(result, "ok", False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "is_windows": self.is_windows,
            "language_mode": self.language_mode,
            "ps_available": self.ps_available,
            "constrained": self.constrained,
            "gateway": self.gateway,
            "errors": self.errors,
            "sections": {key: value for key, value in self.data.items()},
            "pings": {host: result.to_dict() for host, result in self.pings.items()},
            "native": {
                name: {
                    "returncode": getattr(result, "returncode", None),
                    "ok": getattr(result, "ok", False),
                    "timed_out": getattr(result, "timed_out", False),
                }
                for name, result in self.native.items()
            },
        }


NATIVE_COMMANDS: dict[str, list[str]] = {
    "ipconfig_all": ["ipconfig", "/all"],
    "arp": ["arp", "-a"],
    "route_print": ["route", "print"],
    "winhttp_proxy": ["netsh", "winhttp", "show", "proxy"],
    "tcp_global": ["netsh", "int", "tcp", "show", "global"],
    "wlan_interfaces": ["netsh", "wlan", "show", "interfaces"],
    "winsock_catalog": ["netsh", "winsock", "show", "catalog"],
    "w32tm_status": ["w32tm", "/query", "/status"],
    "mtu_interfaces": ["netsh", "interface", "ipv4", "show", "subinterfaces"],
}


def _first_gateway(data: dict[str, list[dict[str, Any]]], native: dict[str, Any]) -> str | None:
    for row in data.get("ip_configuration", []):
        candidate = row.get("IPv4Gateway")
        if isinstance(candidate, list):
            candidate = candidate[0] if candidate else None
        if candidate and candidate != "0.0.0.0":
            return str(candidate)

    for row in data.get("routes", []):
        if row.get("DestinationPrefix") == "0.0.0.0/0":
            next_hop = row.get("NextHop")
            if next_hop and next_hop != "0.0.0.0":
                return str(next_hop)

    ipconfig = native.get("ipconfig_all")
    if ipconfig is not None:
        gateway = parse_default_gateway(getattr(ipconfig, "stdout", ""))
        if gateway:
            return gateway
    return None


def _ping(runner: CommandRunner, host: str, timeout: float) -> PingResult:
    result = runner.run(ping_args(host, timeout), timeout=timeout + 2)
    return parse_ping(host, result.stdout + result.stderr, result.returncode)


def collect_snapshot(
    runner: CommandRunner,
    ps: PowerShellLayer | None = None,
    logger: Any | None = None,
    *,
    ping_timeout: float = config.PING_TIMEOUT_SECONDS,
    collect_pings: bool = True,
    native_timeout: float = 8.0,
) -> Snapshot:
    is_windows = os.name == "nt"
    snapshot = Snapshot(is_windows=is_windows)

    if is_windows:
        layer = ps or PowerShellLayer(runner, logger)
        snapshot.language_mode = layer.detect_language_mode()
        snapshot.constrained = snapshot.language_mode.lower() == "constrainedlanguage"
        batch = layer.run_batch()
        snapshot.ps_available = batch.available
        snapshot.language_mode = batch.language_mode or snapshot.language_mode
        snapshot.errors = dict(batch.errors)
        for name in scripts.BATCH_QUERIES:
            if name in batch.data:
                snapshot.data[name] = as_list(batch.data[name])
        if not batch.available and logger is not None:
            logger.warning(
                "powershell_unavailable",
                returncode=getattr(batch.command, "returncode", None),
                error=getattr(batch.command, "error", None),
            )

        for name, argv in NATIVE_COMMANDS.items():
            if name in {"ipconfig_all", "route_print"} and batch.available:
                # Native fallbacks are only needed when the cmdlets failed.
                continue
            result = runner.run(argv, timeout=native_timeout)
            snapshot.native[name] = result

    snapshot.gateway = _first_gateway(snapshot.data, snapshot.native)

    if collect_pings:
        hosts = list(config.INTERNET_PING_HOSTS)
        if snapshot.gateway and snapshot.gateway not in hosts:
            hosts.insert(0, snapshot.gateway)
        for remote in remote_lan_routes(
            snapshot.data.get("ip_addresses", []),
            snapshot.data.get("routes", []),
        )[:8]:
            if remote.next_hop and remote.next_hop not in hosts:
                hosts.append(remote.next_hop)
        for host in hosts:
            snapshot.pings[host] = _ping(runner, host, ping_timeout)

    return snapshot
