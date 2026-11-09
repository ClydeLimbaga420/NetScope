"""Native command helpers and defensive parsers.

Only used where no good PowerShell cmdlet exists (ping, netsh, arp, route,
w32tm, netsh wlan). Parsers tolerate localized and malformed output.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any

import config


@dataclass
class PingResult:
    host: str
    online: bool
    latency_ms: float | None = None
    returncode: int | None = None
    error: str | None = None
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "online": self.online,
            "latency_ms": self.latency_ms,
            "returncode": self.returncode,
            "error": self.error,
        }


def ping_args(host: str, timeout_seconds: float = config.PING_TIMEOUT_SECONDS) -> list[str]:
    if __import__("os").name == "nt":
        return ["ping", "-n", "1", "-w", str(int(timeout_seconds * 1000)), host]
    return ["ping", "-c", "1", "-W", str(max(1, int(timeout_seconds))), host]


_LATENCY_PATTERNS = (
    re.compile(r"time[=<]\s*([0-9.]+)\s*ms", re.I),
    re.compile(r"Average\s*=\s*([0-9.]+)\s*ms", re.I),
    re.compile(r"temps[=<]\s*([0-9.]+)\s*ms", re.I),
    re.compile(r"tiempo[=<]\s*([0-9.]+)\s*ms", re.I),
    re.compile(r"Zeit[=<]\s*([0-9.]+)\s*ms", re.I),
)


def parse_ping(host: str, output: str, returncode: int) -> PingResult:
    latency = None
    for pattern in _LATENCY_PATTERNS:
        match = pattern.search(output or "")
        if match:
            try:
                latency = float(match.group(1))
            except ValueError:
                latency = None
            break

    online = returncode == 0
    lowered = (output or "").lower()
    if any(
        marker in lowered
        for marker in (
            "unreachable",
            "inaccessible",
            "timeout",
            "timed out",
            "100% loss",
            "100% verlust",
            "100% perdidos",
        )
    ):
        online = False

    return PingResult(host=host, online=online, latency_ms=latency, returncode=returncode, raw=output or "")


_GATEWAY_PATTERNS = (
    re.compile(r"Default Gateway[ .]*:\s*([0-9.]+)", re.I),
    re.compile(r"Passerelle par d[ée]faut[ .]*:\s*([0-9.]+)", re.I),
    re.compile(r"Standardgateway[ .]*:\s*([0-9.]+)", re.I),
    re.compile(r"Gateway[ .]*:\s*([0-9.]+)", re.I),
)


def parse_default_gateway(ipconfig_output: str) -> str | None:
    for pattern in _GATEWAY_PATTERNS:
        for match in pattern.finditer(ipconfig_output or ""):
            candidate = match.group(1)
            if candidate and candidate != "0.0.0.0":
                return candidate
    return None


_ARP_PATTERNS = (
    re.compile(r"^\s*([0-9.]+)\s+([0-9a-fA-F-]{17})\s+(\w+)", re.M),
    re.compile(r"\((?P<ip>[0-9.]+)\)\s+at\s+(?P<mac>[0-9a-fA-F:]+)", re.M),
)


def parse_arp(output: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    for line in (output or "").splitlines():
        match = None
        entry_kind = "arp"
        for index, pattern in enumerate(_ARP_PATTERNS):
            match = pattern.search(line)
            if match:
                entry_kind = "dynamic" if index == 0 else "arp"
                break
        if not match:
            continue

        if match.groupdict():
            ip = match.group("ip")
            mac = match.group("mac")
            kind = entry_kind
        else:
            ip, mac, kind = match.group(1), match.group(2), match.group(3) or entry_kind

        if ip in seen:
            continue
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (
            address.is_multicast
            or address.is_loopback
            or address.is_unspecified
            or str(address) == "255.255.255.255"
            or ip.endswith(".255")
        ):
            continue
        seen.add(ip)
        entries.append({"ip": ip, "mac": mac.replace("-", ":").lower(), "type": kind})

    return entries


_ROUTE_LINE = re.compile(
    r"^\s*(0\.0\.0\.0)\s+0\.0\.0\.0\s+([0-9.]+)\s+([0-9.]+)\s+(\d+)",
    re.M,
)


def parse_default_routes(route_print_output: str) -> list[dict[str, Any]]:
    routes = []
    for match in _ROUTE_LINE.finditer(route_print_output or ""):
        destination, gateway, interface, metric = match.groups()
        routes.append(
            {
                "destination": destination,
                "netmask": "0.0.0.0",
                "gateway": gateway,
                "interface": interface,
                "metric": int(metric),
            }
        )
    return routes


def parse_netsh_winhttp_proxy(output: str) -> str | None:
    """Return the configured WinHTTP proxy, or None when direct access is used."""

    for line in (output or "").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key in {"proxy server(s)", "proxy server", "serveur proxy", "proxyserver"}:
            if value and value.lower() not in {"(none)", "direct access (no proxy server)."}:
                return value
    if "direct access" in (output or "").lower():
        return None
    return None


_TCP_AUTOTUNING = re.compile(r"Receive Window Auto-Tuning Level\s*:\s*(\S+)", re.I)
_TCP_AUTOTUNING_ALT = re.compile(r"Receive Window AutoTuning Level\s*:\s*(\S+)", re.I)


def parse_tcp_autotuning(output: str) -> str | None:
    for pattern in (_TCP_AUTOTUNING, _TCP_AUTOTUNING_ALT):
        match = pattern.search(output or "")
        if match:
            return match.group(1).strip()
    return None


def parse_wlan_interfaces(output: str) -> dict[str, str]:
    """Parse ``netsh wlan show interfaces`` key/value text."""

    values: dict[str, str] = {}
    for line in (output or "").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if not key or not value:
            continue
        values.setdefault(key, value)
    return values


def parse_winsock_catalog(output: str) -> list[str]:
    """Return third-party layered service provider descriptions.

    Only entries of type "Layered Service Provider" are considered; base
    providers such as MSAFD/Hyper-V/AF_UNIX are Microsoft components.
    """

    vendors: list[str] = []
    entry_type = ""
    for line in (output or "").splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("entry type:"):
            entry_type = stripped.partition(":")[2].strip().lower()
            continue
        if "description" not in lowered and "beschreibung" not in lowered:
            continue
        _, _, value = stripped.partition(":")
        value = value.strip()
        if not value:
            continue
        if "layered service provider" not in entry_type and "lsp" not in entry_type:
            continue
        lowered_value = value.lower()
        if "microsoft" in lowered_value or "windows" in lowered_value:
            continue
        if value not in vendors:
            vendors.append(value)
    return vendors


def parse_w32tm_status(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (output or "").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        values[key.strip().lower()] = value.strip()
    return values


_MTU_LINE = re.compile(r"^\s*(\d+)\s+\d+\s+\d+\s+\d+\s+(.+?)\s*$", re.M)


def parse_mtu(output: str) -> dict[str, int]:
    """Parse ``netsh interface ipv4 show subinterfaces`` into alias → MTU."""

    values: dict[str, int] = {}
    for match in _MTU_LINE.finditer(output or ""):
        mtu_text, alias = match.groups()
        try:
            mtu = int(mtu_text)
        except ValueError:
            continue
        if mtu <= 0 or mtu > 65535:
            continue
        values[alias.strip()] = mtu
    return values


def parse_mtu_probe_reply(output: str, returncode: int) -> tuple[bool, str]:
    """Interpret a don't-fragment ping used for path-MTU probing."""

    lowered = (output or "").lower()
    if returncode != 0:
        return False, lowered
    if any(marker in lowered for marker in ("fragmented", "too big", "packet needs to be fragmented")):
        return False, lowered
    if any(marker in lowered for marker in ("ttl=", "ttl =", "bytes=", "reply from", "antwort von")):
        return True, lowered
    return False, lowered


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
