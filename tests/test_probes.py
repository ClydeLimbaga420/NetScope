from __future__ import annotations

import io
import itertools
import socket
import struct
import urllib.error
import urllib.request
from email.message import Message
from urllib.parse import parse_qs, urlsplit

import pytest

from core.probes import FakeProbe, NetworkProbe, _parse_http_date


class FakeResponse:
    status = 200

    def __init__(
        self,
        body: bytes,
        url: str = "https://speed.cloudflare.com/test",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.body = body
        self.url = url
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return self.url

    def read(self, size: int):
        return self.body[:size]


class FakeSocket:
    def __init__(self, reply: bytes = b"", error: OSError | None = None):
        self.reply = reply
        self.error = error
        self.timeout: float | None = None
        self.sent: tuple[bytes, tuple[str, int]] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendto(self, data: bytes, address: tuple[str, int]) -> None:
        if self.error:
            raise self.error
        self.sent = (data, address)

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        if self.error:
            raise self.error
        return self.reply, ("192.0.2.53", 53)


def _dns_reply(addresses: list[str], rcode: int = 0) -> bytes:
    question = b"\x07example\x03com\x00\x00\x01\x00\x01"
    header = struct.pack(
        ">HHHHHH", 0x4E53, 0x8180 | rcode, 1, len(addresses), 0, 0
    )
    answers = b""
    for address in addresses:
        answers += (
            b"\xc0\x0c"
            + struct.pack(">HHIH", 1, 1, 60, 4)
            + socket.inet_aton(address)
        )
    return header + question + answers


def test_speed_test_measures_bounded_cloudflare_transfers(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        parsed = urlsplit(request.full_url)
        if parsed.path.endswith("/__up"):
            return FakeResponse(b"ok")
        requested_bytes = int(parse_qs(parsed.query)["bytes"][0])
        return FakeResponse(b"x" * requested_bytes)

    monkeypatch.setattr("core.probes.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("core.probes.time.monotonic", itertools.count().__next__)

    result = NetworkProbe().speed_test()

    assert result["server"] == "speed.cloudflare.com"
    assert result["latency_ms"] == 1000.0
    assert result["latency_samples_ms"] == [1000.0, 1000.0, 1000.0]
    assert result["download_bytes"] == 10 * 1024 * 1024
    assert result["upload_bytes"] == 2 * 1024 * 1024
    assert result["download_mbps"] == 83.89
    assert result["upload_mbps"] == 16.78
    assert len(requests) == 5
    assert all(timeout == NetworkProbe.SPEED_TEST_TIMEOUT_SECONDS for _, timeout in requests)
    assert len(requests[-1][0].data) == NetworkProbe.SPEED_TEST_UPLOAD_BYTES


def test_speed_test_rejects_redirects_to_other_hosts(monkeypatch):
    monkeypatch.setattr(
        "core.probes.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"x", "https://example.com/"),
    )

    with pytest.raises(RuntimeError, match="unexpected host"):
        NetworkProbe()._read_speed_test_response(
            urllib.request.Request(
                "https://speed.cloudflare.com/__down?bytes=1"
            ),
            expected_bytes=1,
        )


def test_speed_test_rejects_incomplete_downloads(monkeypatch):
    monkeypatch.setattr(
        "core.probes.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b""),
    )

    with pytest.raises(RuntimeError, match="received 0 of 1"):
        NetworkProbe()._read_speed_test_response(
            urllib.request.Request(
                "https://speed.cloudflare.com/__down?bytes=1"
            ),
            expected_bytes=1,
        )


def test_speed_test_rejects_oversized_and_error_responses(monkeypatch):
    probe = NetworkProbe()
    request = urllib.request.Request("https://speed.cloudflare.com/__down?bytes=1")

    monkeypatch.setattr(
        "core.probes.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"xx"),
    )
    with pytest.raises(RuntimeError, match="more data"):
        probe._read_speed_test_response(request, expected_bytes=1)

    monkeypatch.setattr(
        "core.probes.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"x", status=503),
    )
    with pytest.raises(RuntimeError, match="HTTP 503"):
        probe._read_speed_test_response(request, expected_bytes=1)

    headers = Message()
    def raise_http_error(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            request.full_url, 429, "slow down", headers, io.BytesIO(b"")
        )

    monkeypatch.setattr("core.probes.urllib.request.urlopen", raise_http_error)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        probe._read_speed_test_response(request, expected_bytes=1)

    with pytest.raises(ValueError, match="size limit"):
        probe._read_speed_test_response(request)


def test_http_get_parses_success_and_dates(monkeypatch):
    monkeypatch.setattr(
        "core.probes.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            b"hello",
            headers={"Date": "Wed, 21 Oct 2015 07:28:00 GMT", "Server": "test"},
        ),
    )

    result = NetworkProbe().http_get("https://example.com/")

    assert result.ok is True
    assert result.status == 200
    assert result.body == "hello"
    assert result.headers["server"] == "test"
    assert result.date is not None and result.date.year == 2015


def test_http_get_reports_http_errors(monkeypatch):
    headers = Message()
    headers["Date"] = "Wed, 21 Oct 2015 07:28:00 GMT"

    def raise_http_error(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://example.com/", 503, "busy", headers, io.BytesIO(b"unavailable")
        )

    monkeypatch.setattr("core.probes.urllib.request.urlopen", raise_http_error)
    result = NetworkProbe().http_get("https://example.com/")

    assert result.ok is False
    assert result.status == 503
    assert result.body == "unavailable"
    assert "503" in (result.error or "")
    assert result.date is not None


def test_http_get_reports_connection_errors(monkeypatch):
    def raise_url_error(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("core.probes.urllib.request.urlopen", raise_url_error)
    result = NetworkProbe().http_get("https://example.com/")

    assert result.ok is False
    assert result.status is None
    assert "offline" in (result.error or "")


def test_dns_query_parses_a_records(monkeypatch):
    sock = FakeSocket(reply=_dns_reply(["93.184.216.34", "93.184.216.35"]))
    monkeypatch.setattr("core.probes.socket.socket", lambda *_args: sock)

    answer = NetworkProbe(timeout=0.5).dns_query("example.com", "192.0.2.53")

    assert answer.ok is True
    assert answer.addresses == ["93.184.216.34", "93.184.216.35"]
    assert answer.rcode == 0
    assert answer.latency_ms is not None
    assert sock.timeout == 0.5
    assert sock.sent is not None and sock.sent[1] == ("192.0.2.53", 53)


def test_dns_query_handles_bad_names_and_short_replies(monkeypatch):
    probe = NetworkProbe()

    bad = probe.dns_query("x" * 64, "192.0.2.53")
    assert bad.ok is False and "too long" in (bad.error or "")

    empty = probe.dns_query(".", "192.0.2.53")
    assert empty.ok is False and "invalid DNS name" in (empty.error or "")

    monkeypatch.setattr(
        "core.probes.socket.socket", lambda *_args: FakeSocket(reply=b"\x00" * 8)
    )
    short = probe.dns_query("example.com", "192.0.2.53")
    assert short.ok is False and "short DNS reply" in (short.error or "")


def test_dns_query_reports_socket_errors_and_malformed_answers(monkeypatch):
    monkeypatch.setattr(
        "core.probes.socket.socket",
        lambda *_args: FakeSocket(error=OSError("network unreachable")),
    )
    failed = NetworkProbe().dns_query("example.com", "192.0.2.53")
    assert failed.ok is False and "network unreachable" in (failed.error or "")

    truncated = struct.pack(">HHHHHH", 0x4E53, 0x8180, 1, 1, 0, 0) + (
        b"\x07example\x03com\x00\x00\x01\x00\x01"
    )
    monkeypatch.setattr(
        "core.probes.socket.socket", lambda *_args: FakeSocket(reply=truncated)
    )
    broken = NetworkProbe().dns_query("example.com", "192.0.2.53")
    assert broken.ok is False and broken.error is None


def test_dns_query_returns_rcode_failure(monkeypatch):
    monkeypatch.setattr(
        "core.probes.socket.socket",
        lambda *_args: FakeSocket(reply=_dns_reply([], rcode=3)),
    )
    answer = NetworkProbe().dns_query("example.com", "192.0.2.53")
    assert answer.ok is False
    assert answer.rcode == 3
    assert answer.addresses == []


def test_resolve_uses_system_lookup(monkeypatch):
    monkeypatch.setattr(
        "core.probes.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.9", 0)),
        ],
    )
    answer = NetworkProbe().resolve("example.com")
    assert answer.ok is True
    assert answer.addresses == ["192.0.2.10", "192.0.2.9"]
    assert answer.latency_ms is not None


def test_resolve_reports_lookup_failures(monkeypatch):
    monkeypatch.setattr(
        "core.probes.socket.getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.gaierror("no name")),
    )
    answer = NetworkProbe().resolve("missing.invalid")
    assert answer.ok is False
    assert "no name" in (answer.error or "")


def test_tcp_connect_reports_success_and_failure(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        "core.probes.socket.create_connection", lambda *_args, **_kwargs: Connection()
    )
    assert NetworkProbe().tcp_connect("example.com", 443) is True

    monkeypatch.setattr(
        "core.probes.socket.create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("refused")),
    )
    assert NetworkProbe().tcp_connect("example.com", 443) is False


def test_parse_http_date_handles_invalid_and_naive_values():
    assert _parse_http_date(None) is None
    assert _parse_http_date("not a date") is None
    parsed = _parse_http_date("Wed, 21 Oct 2015 07:28:00")
    assert parsed is not None and parsed.tzinfo is not None


def test_fake_probe_speed_test_is_deterministic():
    expected = {"server": "test", "download_mbps": 10.0}
    probe = FakeProbe(speed_test_result=expected)

    assert probe.speed_test() == expected
    assert probe.calls == [("speed_test",)]

    with pytest.raises(RuntimeError, match="no speed-test result"):
        FakeProbe().speed_test()
