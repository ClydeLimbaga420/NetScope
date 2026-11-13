"""Pure-Python network probes.

These avoid starting a process for cheap tests (DNS, TCP connect, HTTP) as the
spec recommends. They are injectable so checks can be tested deterministically.
"""

from __future__ import annotations

import socket
import statistics
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any

import config


@dataclass
class DnsAnswer:
    name: str
    server: str | None
    ok: bool
    addresses: list[str] = field(default_factory=list)
    latency_ms: float | None = None
    rcode: int | None = None
    error: str | None = None


@dataclass
class HttpResult:
    url: str
    ok: bool
    status: int | None = None
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    latency_ms: float | None = None
    error: str | None = None
    date: datetime | None = None


def _encode_qname(name: str) -> bytes:
    parts = [part for part in name.strip(".").split(".") if part]
    if not parts or len(parts) > 127:
        raise ValueError("invalid DNS name")
    encoded = bytearray()
    for part in parts:
        raw = part.encode("idna")
        if len(raw) > 63:
            raise ValueError("DNS label too long")
        encoded.append(len(raw))
        encoded.extend(raw)
    encoded.append(0)
    return bytes(encoded)


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    original = offset
    hops = 0

    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                break
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                original = offset + 2
            jumped = True
            offset = pointer
            hops += 1
            if hops > 20:
                break
            continue
        offset += 1
        labels.append(data[offset : offset + length].decode("ascii", errors="ignore"))
        offset += length

    return ".".join(labels), (original if jumped else offset)


class NetworkProbe:
    """Real network probes with timeouts on everything."""

    SPEED_TEST_HOST = "speed.cloudflare.com"
    SPEED_TEST_DOWNLOAD_BYTES = 10 * 1024 * 1024
    SPEED_TEST_UPLOAD_BYTES = 2 * 1024 * 1024
    SPEED_TEST_TIMEOUT_SECONDS = 15

    def __init__(self, timeout: float = 2.0):
        self.timeout = timeout

    def dns_query(self, name: str, server: str) -> DnsAnswer:
        started = time.monotonic()
        try:
            packet = struct.pack(">HHHHHH", 0x4E53, 0x0100, 1, 0, 0, 0)
            packet += _encode_qname(name)
            packet += struct.pack(">HH", 1, 1)
        except (ValueError, UnicodeError) as exc:
            return DnsAnswer(name=name, server=server, ok=False, error=str(exc))

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(self.timeout)
                sock.sendto(packet, (server, 53))
                data, _ = sock.recvfrom(4096)
        except OSError as exc:
            return DnsAnswer(name=name, server=server, ok=False, error=str(exc))

        latency = (time.monotonic() - started) * 1000
        if len(data) < 12:
            return DnsAnswer(name=name, server=server, ok=False, error="short DNS reply")

        _, flags, qdcount, ancount = struct.unpack(">HHHH", data[:8])
        rcode = flags & 0x000F
        offset = 12
        try:
            for _ in range(qdcount):
                _, offset = _read_name(data, offset)
                offset += 4
            addresses: list[str] = []
            for _ in range(ancount):
                _, offset = _read_name(data, offset)
                if offset + 10 > len(data):
                    break
                rtype, _, _, rdlength = struct.unpack(">HHIH", data[offset : offset + 10])
                offset += 10
                rdata = data[offset : offset + rdlength]
                offset += rdlength
                if rtype == 1 and len(rdata) == 4:
                    addresses.append(socket.inet_ntoa(rdata))
        except (struct.error, IndexError):
            return DnsAnswer(name=name, server=server, ok=False, error="malformed DNS reply")

        return DnsAnswer(
            name=name,
            server=server,
            ok=rcode == 0 and bool(addresses),
            addresses=addresses,
            latency_ms=round(latency, 1),
            rcode=rcode,
        )

    def resolve(self, name: str) -> DnsAnswer:
        started = time.monotonic()
        try:
            infos = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)
        except (socket.gaierror, OSError) as exc:
            return DnsAnswer(name=name, server=None, ok=False, error=str(exc))
        addresses = sorted({info[4][0] for info in infos})
        return DnsAnswer(
            name=name,
            server=None,
            ok=bool(addresses),
            addresses=addresses,
            latency_ms=round((time.monotonic() - started) * 1000, 1),
        )

    def tcp_connect(self, host: str, port: int, timeout: float | None = None) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout or self.timeout):
                return True
        except OSError:
            return False

    def http_get(self, url: str, timeout: float | None = None) -> HttpResult:
        started = time.monotonic()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "NetScope/" + config.APP_VERSION},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                body = response.read(4096).decode("utf-8", errors="replace")
                headers = {key.lower(): value for key, value in response.headers.items()}
                return HttpResult(
                    url=url,
                    ok=200 <= response.status < 400,
                    status=response.status,
                    body=body,
                    headers=headers,
                    latency_ms=round((time.monotonic() - started) * 1000, 1),
                    date=_parse_http_date(headers.get("date")),
                )
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read(4096).decode("utf-8", errors="replace")
            except Exception:
                pass
            headers = {key.lower(): value for key, value in (exc.headers or {}).items()}
            return HttpResult(
                url=url,
                ok=False,
                status=exc.code,
                body=body,
                headers=headers,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc),
                date=_parse_http_date(headers.get("date")),
            )
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return HttpResult(
                url=url,
                ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc),
            )

    def speed_test(self) -> dict[str, Any]:
        """Measure HTTP latency and throughput against Cloudflare's test endpoint."""
        base_url = f"https://{self.SPEED_TEST_HOST}"
        headers = {
            "User-Agent": "NetScope/" + config.APP_VERSION,
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        }

        latencies: list[float] = []
        for _ in range(3):
            request = urllib.request.Request(
                f"{base_url}/__down?bytes=1",
                headers=headers,
            )
            started = time.monotonic()
            self._read_speed_test_response(request, expected_bytes=1)
            latencies.append((time.monotonic() - started) * 1000)

        download_request = urllib.request.Request(
            f"{base_url}/__down?bytes={self.SPEED_TEST_DOWNLOAD_BYTES}",
            headers=headers,
        )
        started = time.monotonic()
        downloaded = self._read_speed_test_response(
            download_request,
            expected_bytes=self.SPEED_TEST_DOWNLOAD_BYTES,
        )
        download_seconds = time.monotonic() - started

        upload_data = b"\0" * self.SPEED_TEST_UPLOAD_BYTES
        upload_request = urllib.request.Request(
            f"{base_url}/__up",
            data=upload_data,
            headers={**headers, "Content-Type": "application/octet-stream"},
            method="POST",
        )
        started = time.monotonic()
        self._read_speed_test_response(upload_request, max_bytes=65536)
        upload_seconds = time.monotonic() - started

        return {
            "server": self.SPEED_TEST_HOST,
            "latency_ms": round(statistics.median(latencies), 1),
            "latency_samples_ms": [round(value, 1) for value in latencies],
            "download_mbps": round(len(downloaded) * 8 / max(download_seconds, 1e-9) / 1_000_000, 2),
            "upload_mbps": round(self.SPEED_TEST_UPLOAD_BYTES * 8 / max(upload_seconds, 1e-9) / 1_000_000, 2),
            "download_bytes": len(downloaded),
            "upload_bytes": self.SPEED_TEST_UPLOAD_BYTES,
        }

    def _read_speed_test_response(
        self,
        request: urllib.request.Request,
        *,
        expected_bytes: int | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        limit = max_bytes if max_bytes is not None else expected_bytes
        if limit is None:
            raise ValueError("a response size limit is required")
        try:
            with urllib.request.urlopen(
                request, timeout=self.SPEED_TEST_TIMEOUT_SECONDS
            ) as response:
                final_url = urllib.parse.urlsplit(response.geturl())
                if (
                    final_url.scheme != "https"
                    or final_url.hostname != self.SPEED_TEST_HOST
                    or final_url.port not in (None, 443)
                ):
                    raise RuntimeError("Speed test endpoint redirected to an unexpected host.")
                if response.status != 200:
                    raise RuntimeError(
                        f"Speed test endpoint returned HTTP {response.status}."
                    )
                body = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Speed test endpoint returned HTTP {exc.code}."
            ) from exc

        if len(body) > limit:
            raise RuntimeError("Speed test endpoint returned more data than requested.")
        if expected_bytes is not None and len(body) != expected_bytes:
            raise RuntimeError(
                f"Speed test received {len(body)} of {expected_bytes} requested bytes."
            )
        return body


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class FakeProbe(NetworkProbe):
    """Deterministic probe used by tests."""

    def __init__(
        self,
        dns: dict[str, DnsAnswer] | None = None,
        http: dict[str, HttpResult] | None = None,
        tcp: dict[tuple[str, int], bool] | None = None,
        default_dns: DnsAnswer | None = None,
        speed_test_result: dict[str, Any] | None = None,
    ):
        super().__init__(timeout=0.01)
        self.dns = dns or {}
        self.http = http or {}
        self.tcp = tcp or {}
        self.default_dns = default_dns
        self.speed_test_result = speed_test_result
        self.calls: list[tuple[Any, ...]] = []

    def dns_query(self, name: str, server: str) -> DnsAnswer:
        self.calls.append(("dns_query", name, server))
        return self.dns.get(f"{name}@{server}") or self.dns.get(server) or self.default_dns or DnsAnswer(
            name=name, server=server, ok=False, error="fake: no answer"
        )

    def resolve(self, name: str) -> DnsAnswer:
        self.calls.append(("resolve", name))
        return self.dns.get(name) or self.default_dns or DnsAnswer(
            name=name, server=None, ok=False, error="fake: no answer"
        )

    def http_get(self, url: str, timeout: float | None = None) -> HttpResult:
        self.calls.append(("http_get", url))
        return self.http.get(url) or HttpResult(url=url, ok=False, error="fake: no response")

    def tcp_connect(self, host: str, port: int, timeout: float | None = None) -> bool:
        self.calls.append(("tcp_connect", host, port))
        return bool(self.tcp.get((host, port)))

    def speed_test(self) -> dict[str, Any]:
        self.calls.append(("speed_test",))
        if self.speed_test_result is None:
            raise RuntimeError("fake: no speed-test result configured")
        return dict(self.speed_test_result)
