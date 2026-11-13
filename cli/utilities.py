"""Small network utilities exposed by the CLI."""

from __future__ import annotations

import os
import re
from typing import Any

from cli.context import CliContext
from core.native import (
    parse_arp,
    parse_default_routes,
    parse_mtu_probe_reply,
)
from powershell.validation import validate_host, validate_ip, validate_port_spec


def parse_ping_latencies(output: str) -> list[int]:
    values: list[int] = []
    markers = ("ttl=", "ttl =", "bytes=", "reply from", "antwort", "réponse", "respuesta")
    for line in (output or "").splitlines():
        if not any(marker in line.lower() for marker in markers):
            continue
        match = re.search(r"([0-9]+)\s*ms", line, re.IGNORECASE)
        if match:
            try:
                values.append(int(match.group(1)))
            except ValueError:
                continue
    return values


def parse_packet_loss(output: str) -> int | None:
    for pattern in (r"([0-9]+)%\s*(?:loss|paketverlust|perte)", r"([0-9]+)%"):
        match = re.search(pattern, output or "", re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def expand_ports(spec: str, cap: int = 1024) -> list[int]:
    ports: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, _, end = part.partition("-")
            first, last = int(start), int(end)
            ports.extend(range(first, last + 1))
        else:
            ports.append(int(part))
        if len(ports) > cap:
            raise ValueError(f"port specification expands past {cap} ports")
    seen: set[int] = set()
    ordered: list[int] = []
    for port in ports:
        if port not in seen:
            seen.add(port)
            ordered.append(port)
    return ordered


class UtilityRunner:
    def __init__(self, ctx: CliContext):
        self.ctx = ctx

    def _run(self, argv: list[str], timeout: float):
        return self.ctx.runner.run(argv, timeout=timeout)

    def ping(self, host: str, count: int = 4, timeout: float = 1.0) -> dict[str, Any]:
        host = validate_host(host)
        count = max(1, min(int(count), 100))
        timeout = max(0.1, min(float(timeout), 30.0))
        if os.name == "nt":
            argv = [
                "ping",
                "-n",
                str(count),
                "-w",
                str(int(timeout * 1000)),
                host,
            ]
        else:
            argv = ["ping", "-c", str(count), "-W", str(max(1, int(timeout))), host]
        result = self._run(argv, timeout * count + 5)
        output = result.stdout + result.stderr
        latencies = parse_ping_latencies(output)
        loss = parse_packet_loss(output)
        return {
            "host": host,
            "count": count,
            "returncode": result.returncode,
            "online": result.returncode == 0 or bool(latencies),
            "latencies_ms": latencies,
            "packet_loss_percent": loss,
            "output": output.strip(),
        }

    def trace(self, host: str, max_hops: int = 30, timeout: float = 60.0) -> dict[str, Any]:
        host = validate_host(host)
        max_hops = max(1, min(int(max_hops), 64))
        timeout = max(1.0, min(float(timeout), 300.0))
        if os.name == "nt":
            argv = ["tracert", "-d", "-h", str(max_hops), "-w", "1000", host]
        else:
            argv = ["traceroute", "-n", "-m", str(max_hops), host]
        result = self._run(argv, timeout)
        return {
            "host": host,
            "max_hops": max_hops,
            "returncode": result.returncode,
            "output": (result.stdout + result.stderr).strip(),
        }

    def dns(self, name: str, server: str | None = None) -> dict[str, Any]:
        name = validate_host(name)
        if server:
            server = validate_ip(server)
            answer = self.ctx.probe.dns_query(name, server)
        else:
            answer = self.ctx.probe.resolve(name)
        return {
            "name": name,
            "server": answer.server,
            "ok": answer.ok,
            "addresses": list(answer.addresses),
            "latency_ms": answer.latency_ms,
            "rcode": answer.rcode,
            "error": answer.error,
        }

    def arp(self) -> dict[str, Any]:
        result = self._run(["arp", "-a"], 8)
        return {
            "returncode": result.returncode,
            "entries": parse_arp(result.stdout + result.stderr),
            "output": (result.stdout + result.stderr).strip(),
        }

    def routes(self) -> dict[str, Any]:
        command = ["route", "print"] if os.name == "nt" else ["ip", "route"]
        result = self._run(command, 8)
        return {
            "returncode": result.returncode,
            "default_routes": parse_default_routes(result.stdout + result.stderr),
            "output": (result.stdout + result.stderr).strip(),
        }

    def ports(self, host: str, spec: str, timeout: float = 1.0) -> dict[str, Any]:
        host = validate_host(host)
        spec = validate_port_spec(spec)
        try:
            ports = expand_ports(spec)
        except ValueError:
            raise
        results = [
            {"port": port, "open": self.ctx.probe.tcp_connect(host, port, timeout)}
            for port in ports
        ]
        return {
            "host": host,
            "spec": spec,
            "results": results,
            "open": [item["port"] for item in results if item["open"]],
            "closed": [item["port"] for item in results if not item["open"]],
        }

    def mtu(self, host: str, timeout: float = 1.5) -> dict[str, Any]:
        host = validate_host(host)
        timeout_ms = int(max(0.2, min(timeout, 5.0)) * 1000)
        low, high = 548, 1472
        best: int | None = None
        tested: list[dict[str, Any]] = []

        while low <= high:
            size = (low + high) // 2
            if os.name == "nt":
                argv = [
                    "ping",
                    "-f",
                    "-l",
                    str(size),
                    "-n",
                    "1",
                    "-w",
                    str(timeout_ms),
                    host,
                ]
            else:
                argv = ["ping", "-M", "do", "-s", str(size), "-c", "1", host]
            result = self._run(argv, timeout + 2)
            ok, _ = parse_mtu_probe_reply(result.stdout + result.stderr, result.returncode)
            tested.append({"payload": size, "ok": ok})
            if ok:
                best = size
                low = size + 1
            else:
                high = size - 1

        return {
            "host": host,
            "path_mtu": best + 28 if best is not None else None,
            "payload": best,
            "tested": tested,
        }

    def speed_test(self) -> dict[str, Any]:
        return self.ctx.probe.speed_test()
