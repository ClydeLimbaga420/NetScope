"""Shared monitoring data and service for the localhost UI."""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generic, Literal, TypeVar

import config
from core.device_discovery import DeviceDiscovery
from core.info import build_info
from core.native import parse_ping_stats
from core.snapshot import Snapshot
from core.snapshot_cache import load_with_reason as load_snapshot_cache
from core.snapshot_cache import save as save_snapshot_cache
from powershell.validation import validate_ip

T = TypeVar("T")


@dataclass(frozen=True)
class NetworkCounters:
    bytes_received: int
    bytes_sent: int


@dataclass(frozen=True)
class MonitorTaskResult(Generic[T]):
    state: Literal["pending", "ready", "error"]
    value: T | None = None
    error: str | None = None


@dataclass
class _BackgroundTask(Generic[T]):
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    result: MonitorTaskResult[T] | None = None
    completed_at: float | None = None


def _normalize_mac(value: Any) -> str | None:
    digits = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(digits) != 12:
        return None
    return ":".join(digits[index : index + 2] for index in range(0, 12, 2)).lower()


def _speed_mbps(value: Any) -> int | None:
    match = re.search(r"([\d.]+)\s*(gbps|mbps|kbps)", str(value or ""), re.I)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).lower()
    factor = {"gbps": 1000, "mbps": 1, "kbps": 0.001}[unit]
    return round(amount * factor)


def _diagnose_network(
    gateway: str | None,
    interfaces: list[dict[str, Any]],
    prefixes: dict[str, int],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    up_interfaces = [item for item in interfaces if item["is_up"]]
    candidates = up_interfaces or interfaces
    network_down = not interfaces or not up_interfaces

    if not interfaces:
        issues.append(
            {
                "id": "network-down",
                "severity": "error",
                "message": (
                    "Network is down: no active network adapters with an IPv4 "
                    "address were detected. Check your Ethernet/Wi-Fi connection "
                    "and make sure the adapter is enabled."
                ),
            }
        )
    elif not up_interfaces:
        issues.append(
            {
                "id": "network-down",
                "severity": "error",
                "message": (
                    "Network is down: no network adapter is currently connected. "
                    "Check your Ethernet/Wi-Fi connection or enable the network "
                    "adapter."
                ),
            }
        )

    apipa = [item for item in candidates if item["ipv4"].startswith("169.254.")]
    if apipa:
        sample = apipa[0]["ipv4"]
        issues.append(
            {
                "id": "apipa-address",
                "severity": "error",
                "message": (
                    f"This computer is using an automatic private IP address "
                    f"({sample}). This usually means it could not get an IP "
                    "address from DHCP. Check the network/router or renew the "
                    "DHCP lease."
                ),
            }
        )

    if not gateway:
        issues.append(
            {
                "id": "missing-gateway",
                "severity": "warning",
                "message": (
                    "No default gateway was detected. You may be disconnected, "
                    "or the network adapter is not configured with a gateway."
                ),
            }
        )
        return {
            "gateway": gateway,
            "issues": issues,
            "gateway_in_subnet": None,
            "network_down": network_down,
        }

    comparable = [item for item in candidates if item["ipv4"] in prefixes]
    matches = False
    if comparable:
        try:
            gateway_address = ipaddress.IPv4Address(gateway)
        except ipaddress.AddressValueError:
            gateway_address = None
        matches = gateway_address is not None and any(
            gateway_address
            in ipaddress.IPv4Network(
                f'{item["ipv4"]}/{prefixes[item["ipv4"]]}',
                strict=False,
            )
            for item in comparable
        )
        if not matches:
            sample = comparable[0]
            network = ipaddress.IPv4Network(
                f'{sample["ipv4"]}/{prefixes[sample["ipv4"]]}',
                strict=False,
            )
            issues.append(
                {
                    "id": "wrong-gateway-subnet",
                    "severity": "error",
                    "message": (
                        f"Default gateway {gateway} is not in the same subnet as "
                        f'{sample["ipv4"]} ({network.netmask}) on '
                        f'{sample["name"]}. The default gateway may be configured '
                        "incorrectly."
                    ),
                }
            )

    return {
        "gateway": gateway,
        "issues": issues,
        "gateway_in_subnet": matches if comparable else None,
        "network_down": network_down,
    }


def _network_payload(snapshot: Snapshot, info: dict[str, Any]) -> dict[str, Any]:
    interfaces: list[dict[str, Any]] = []
    prefixes: dict[str, int] = {}
    seen_adapters: set[str] = set()
    for adapter in info.get("adapters", []):
        name = adapter.get("name") or adapter.get("alias") or ""
        alias = str(adapter.get("alias") or name).lower()
        for address in adapter.get("ipv4", []):
            ip = address.get("address")
            try:
                parsed = ipaddress.ip_address(ip)
            except (TypeError, ValueError):
                continue
            if parsed.version != 4 or parsed.is_loopback:
                continue
            if alias in seen_adapters:
                break
            prefix = address.get("prefix")
            if isinstance(prefix, int) and 0 <= prefix <= 32:
                prefixes[str(parsed)] = prefix
            interfaces.append(
                {
                    "name": name,
                    "ipv4": str(parsed),
                    "mac": _normalize_mac(adapter.get("mac")),
                    "is_up": str(adapter.get("status") or "").lower() == "up",
                    "speed_mbps": _speed_mbps(adapter.get("link_speed")),
                    "_alias": alias,
                }
            )
            seen_adapters.add(alias)
            break

    public_interfaces = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in interfaces
    ]
    return {
        "hostname": info.get("hostname"),
        "local_ip": public_interfaces[0]["ipv4"] if public_interfaces else None,
        "gateway": snapshot.gateway,
        "interfaces": public_interfaces,
        "interface_count": len(public_interfaces),
        "diagnosis": _diagnose_network(snapshot.gateway, public_interfaces, prefixes),
    }


def _ping_payload(host: str | None, snapshot: Snapshot) -> dict[str, Any]:
    result = snapshot.pings.get(host) if host else None
    return {
        "host": host,
        "latency_ms": getattr(result, "latency_ms", None),
        "online": bool(getattr(result, "online", False)),
    }


def _status_problems(
    network: dict[str, Any],
    internet_ping: dict[str, Any],
    gateway_ping: dict[str, Any],
) -> list[dict[str, str]]:
    problems = [
        {
            "source": "configuration",
            "severity": issue.get("severity", "warning"),
            "message": issue.get("message"),
        }
        for issue in network["diagnosis"]["issues"]
    ]
    gateway = network["gateway"]
    if gateway and not gateway_ping["online"]:
        problems.append(
            {
                "source": "gateway",
                "severity": "error",
                "message": f"Default gateway {gateway} did not respond.",
            }
        )
    if not internet_ping["online"]:
        if gateway and gateway_ping["online"]:
            message = "The default gateway is reachable, but the internet is not."
        elif gateway:
            message = "Network connection problem: the internet is unreachable."
        else:
            message = (
                "Network is down or disconnected: no default gateway was detected."
            )
        problems.append(
            {"source": "internet", "severity": "error", "message": message}
        )
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for problem in problems:
        message = problem.get("message")
        if message and message not in seen:
            seen.add(message)
            deduped.append(problem)
    return deduped


def _zero_traffic() -> dict[str, float | int]:
    return {
        "download_bytes_sec": 0.0,
        "upload_bytes_sec": 0.0,
        "download_mbps": 0.0,
        "upload_mbps": 0.0,
        "total_received_bytes": 0,
        "total_sent_bytes": 0,
    }


def _pending_ping(host: str | None, reason: str) -> dict[str, Any]:
    return {
        "host": host,
        "latency_ms": None,
        "online": False,
        "packet_loss_percent": None,
        "packets_sent": 0,
        "packets_received": 0,
        "reason": reason,
    }


def _pending_status_ping(host: str | None) -> dict[str, Any]:
    return {"host": host, "latency_ms": None, "online": False}


def _snapshot_age_seconds(captured_at: str | None, now: float) -> float | None:
    if not captured_at:
        return None
    try:
        parsed = datetime.fromisoformat(captured_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round(max(0.0, now - parsed.timestamp()), 1)


class MonitoringService:
    DEVICE_CACHE_SECONDS = 15.0
    PACKET_LOSS_CACHE_SECONDS = 30.0
    SNAPSHOT_CACHE_SECONDS = 15.0

    def __init__(
        self,
        engine: Any,
        runner: Any,
        ps: Any,
        *,
        counter_provider: Callable[[], NetworkCounters],
        clock: Callable[[], float],
        logger: Any | None = None,
        cache_path: Path | None = None,
        wall_clock: Callable[[], float] | None = None,
    ):
        self.engine = engine
        self.runner = runner
        self.ps = ps
        self.counter_provider = counter_provider
        self.clock = clock
        self.wall_clock = wall_clock or time.time
        self.logger = logger
        self.cache_path = Path(cache_path) if cache_path is not None else config.snapshot_cache_path()
        self.device_discovery = DeviceDiscovery(runner, ps, logger, clock=clock)
        self._rates_lock = threading.Lock()
        self._previous_counters: NetworkCounters | None = None
        self._previous_time: float | None = None
        self._devices_task: _BackgroundTask[list[dict[str, Any]]] = _BackgroundTask()
        self._packet_loss_task: _BackgroundTask[dict[str, Any]] = _BackgroundTask()
        self._snapshot_lock = threading.Lock()
        self._snapshot_refresh_lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._snapshot_at: float = 0.0
        self._snapshot_error: str | None = None
        self._snapshot_refreshing = False
        self._snapshot_from_cache = False
        self._snapshot_captured_at: str | None = None
        self._load_cached_snapshot()

    def _log(self, event: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger.event(event, source="cache" if "cache" in event else "refresh", **fields)

    def _load_cached_snapshot(self) -> None:
        started = time.monotonic()
        cached, reason = load_snapshot_cache(self.cache_path)
        duration_seconds = round(time.monotonic() - started, 4)
        if cached is None:
            if self.cache_path.exists():
                self._log(
                    "snapshot_cache_invalid",
                    reason=reason or "unusable",
                    duration_seconds=duration_seconds,
                )
            return
        with self._snapshot_lock:
            self._snapshot = cached
            self._snapshot_at = 0.0
            self._snapshot_error = None
            self._snapshot_from_cache = True
            self._snapshot_captured_at = cached.captured_at
        self._log(
            "snapshot_cache_loaded",
            captured_at=cached.captured_at,
            duration_seconds=duration_seconds,
        )

    def get_snapshot(self) -> Snapshot | None:
        """Return the shared snapshot, refreshing stale data in the background."""
        with self._snapshot_lock:
            snapshot = self._snapshot
            stale = (
                snapshot is None
                or (time.monotonic() - self._snapshot_at) >= self.SNAPSHOT_CACHE_SECONDS
            )
        if stale:
            self._request_snapshot_refresh(delay=0.02 if snapshot is not None else 0.0)
        return snapshot

    def freshness(self) -> dict[str, Any]:
        """Describe how current the shared snapshot is."""
        with self._snapshot_lock:
            snapshot = self._snapshot
            error = self._snapshot_error
            from_cache = self._snapshot_from_cache
            snapshot_at = self._snapshot_at
            captured_at = self._snapshot_captured_at

        if snapshot is None:
            state = "unavailable" if error else "collecting"
        elif from_cache:
            state = "stale"
        elif time.monotonic() - snapshot_at >= self.SNAPSHOT_CACHE_SECONDS:
            state = "stale"
        else:
            state = "fresh"

        return {
            "state": state,
            "captured_at": captured_at,
            "age_seconds": _snapshot_age_seconds(captured_at, self.wall_clock()),
            "error": error if state == "unavailable" else None,
        }

    def prewarm(self) -> None:
        """Start collecting the first snapshot without blocking the caller."""
        self._request_snapshot_refresh()

    def _request_snapshot_refresh(self, *, delay: float = 0.0) -> None:
        with self._snapshot_refresh_lock:
            if self._snapshot_refreshing:
                return
            self._snapshot_refreshing = True
        with self._snapshot_lock:
            self._snapshot_error = None
        if delay:
            timer = threading.Timer(delay, self._refresh_snapshot)
            timer.name = "netscope-snapshot-refresh"
            timer.daemon = True
            timer.start()
        else:
            threading.Thread(
                target=self._refresh_snapshot,
                name="netscope-snapshot-refresh",
                daemon=True,
            ).start()

    def _refresh_snapshot(self) -> None:
        started = time.monotonic()
        self._log("snapshot_refresh_start", duration_seconds=0.0)
        try:
            snapshot = self.engine.collect_snapshot()
            try:
                save_snapshot_cache(snapshot, self.cache_path)
            except OSError as exc:
                self._log(
                    "snapshot_cache_invalid",
                    reason="write_failed",
                    duration_seconds=round(time.monotonic() - started, 4),
                    error=str(exc),
                )
            with self._snapshot_lock:
                self._snapshot = snapshot
                self._snapshot_at = time.monotonic()
                self._snapshot_error = None
                self._snapshot_from_cache = False
                self._snapshot_captured_at = snapshot.captured_at
            self._log(
                "snapshot_refresh_complete",
                duration_seconds=round(time.monotonic() - started, 4),
                captured_at=snapshot.captured_at,
            )
        except Exception as exc:  # noqa: BLE001
            with self._snapshot_lock:
                self._snapshot_error = str(exc)
            self._log(
                "snapshot_refresh_failed",
                duration_seconds=round(time.monotonic() - started, 4),
                error=str(exc),
            )
        finally:
            with self._snapshot_refresh_lock:
                self._snapshot_refreshing = False

    def _traffic(self) -> dict[str, float | int]:
        with self._rates_lock:
            current = self.counter_provider()
            now = self.clock()
            download = 0.0
            upload = 0.0
            if self._previous_counters is not None and self._previous_time is not None:
                elapsed = max(now - self._previous_time, 0.001)
                download = max(
                    current.bytes_received - self._previous_counters.bytes_received,
                    0,
                ) / elapsed
                upload = max(
                    current.bytes_sent - self._previous_counters.bytes_sent,
                    0,
                ) / elapsed
            self._previous_counters = current
            self._previous_time = now

        return {
            "download_bytes_sec": round(download, 1),
            "upload_bytes_sec": round(upload, 1),
            "download_mbps": round(download * 8 / 1_000_000, 3),
            "upload_mbps": round(upload * 8 / 1_000_000, 3),
            "total_received_bytes": current.bytes_received,
            "total_sent_bytes": current.bytes_sent,
        }

    def get_status(self) -> dict[str, Any]:
        snapshot = self.get_snapshot()
        internet_host = config.INTERNET_PING_HOSTS[0]
        if snapshot is None:
            status: dict[str, Any] = {
                "network": {
                    "hostname": None,
                    "local_ip": None,
                    "gateway": None,
                    "interfaces": [],
                    "interface_count": 0,
                    "diagnosis": {
                        "gateway": None,
                        "issues": [],
                        "gateway_in_subnet": None,
                        "network_down": False,
                    },
                },
                "traffic": _zero_traffic(),
                "internet_ping": _pending_status_ping(internet_host),
                "gateway_ping": _pending_status_ping(None),
                "problems": [],
            }
        else:
            info = build_info(snapshot)
            network = _network_payload(snapshot, info)
            internet_ping = _ping_payload(internet_host, snapshot)
            gateway_ping = _ping_payload(snapshot.gateway, snapshot)
            status = {
                "network": network,
                "traffic": self._traffic(),
                "internet_ping": internet_ping,
                "gateway_ping": gateway_ping,
                "problems": _status_problems(network, internet_ping, gateway_ping),
            }
        status["data_freshness"] = self.freshness()
        return status

    def _collect_packet_loss(self, snapshot: Snapshot) -> dict[str, Any]:
        internet_host = validate_ip(config.INTERNET_PING_HOSTS[0])
        gateway = validate_ip(snapshot.gateway) if snapshot.gateway else None
        hosts = {"internet": internet_host}
        if gateway:
            hosts["gateway"] = gateway

        def sample(host: str) -> dict[str, Any]:
            if os.name == "nt":
                args = ["ping", "-n", "10", "-w", "1000", host]
            else:
                args = ["ping", "-c", "10", "-W", "1", host]
            result = self.runner.run(args, timeout=15.0)
            if result.timed_out:
                raise RuntimeError(f"ping command timed out for {host}")
            if result.error:
                raise RuntimeError(f"ping command failed for {host}: {result.error}")
            return parse_ping_stats(
                host,
                f"{result.stdout}\n{result.stderr}",
                result.returncode,
                count=10,
            )

        with ThreadPoolExecutor(max_workers=len(hosts)) as executor:
            futures = {key: executor.submit(sample, host) for key, host in hosts.items()}
            internet = futures["internet"].result()
            gateway_result = (
                futures["gateway"].result()
                if gateway
                else {
                    "host": None,
                    "latency_ms": None,
                    "online": False,
                    "packet_loss_percent": None,
                    "packets_sent": 0,
                    "packets_received": 0,
                    "reason": "No default gateway was detected.",
                }
            )
        return {"count": 10, "internet": internet, "gateway": gateway_result}

    def _run_background_task(
        self,
        task: _BackgroundTask[T],
        work: Callable[[], T],
    ) -> None:
        try:
            result = MonitorTaskResult("ready", value=work())
        except Exception as exc:
            result = MonitorTaskResult("error", error=str(exc))
        with task.lock:
            task.result = result
            task.completed_at = self.clock()
            task.running = False

    def _request_task(
        self,
        task: _BackgroundTask[T],
        work: Callable[[], T],
        *,
        force: bool,
        cache_seconds: float,
        thread_name: str,
    ) -> MonitorTaskResult[T]:
        with task.lock:
            if task.running:
                return MonitorTaskResult("pending")
            now = self.clock()
            if task.result is not None and not force:
                if task.result.state == "error":
                    return task.result
                if (
                    task.completed_at is not None
                    and now - task.completed_at < cache_seconds
                ):
                    return task.result
            task.running = True
            task.result = MonitorTaskResult("pending")
            thread = threading.Thread(
                target=self._run_background_task,
                args=(task, work),
                name=thread_name,
                daemon=True,
            )
            thread.start()
            return MonitorTaskResult("pending")

    def request_devices(
        self, force: bool = False
    ) -> MonitorTaskResult[list[dict[str, Any]]]:
        def discover() -> list[dict[str, Any]]:
            snapshot = self.get_snapshot()
            if snapshot is None:
                return []
            return self.device_discovery.discover(snapshot, force=True)

        return self._request_task(
            self._devices_task,
            discover,
            force=force,
            cache_seconds=self.DEVICE_CACHE_SECONDS,
            thread_name="netscope-device-discovery",
        )

    def request_packet_loss(
        self, force: bool = False
    ) -> MonitorTaskResult[dict[str, Any]]:
        def collect() -> dict[str, Any]:
            snapshot = self.get_snapshot()
            if snapshot is None:
                return {
                    "count": 10,
                    "internet": _pending_ping(
                        config.INTERNET_PING_HOSTS[0], "Waiting for network data."
                    ),
                    "gateway": _pending_ping(None, "Waiting for network data."),
                }
            return self._collect_packet_loss(snapshot)

        return self._request_task(
            self._packet_loss_task,
            collect,
            force=force,
            cache_seconds=self.PACKET_LOSS_CACHE_SECONDS,
            thread_name="netscope-packet-loss",
        )
