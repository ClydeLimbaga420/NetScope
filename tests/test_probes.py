from __future__ import annotations

import itertools
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

from core.probes import FakeProbe, NetworkProbe


class FakeResponse:
    status = 200

    def __init__(self, body: bytes, url: str = "https://speed.cloudflare.com/test"):
        self.body = body
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return self.url

    def read(self, size: int):
        return self.body[:size]


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


def test_fake_probe_speed_test_is_deterministic():
    expected = {"server": "test", "download_mbps": 10.0}
    probe = FakeProbe(speed_test_result=expected)

    assert probe.speed_test() == expected
    assert probe.calls == [("speed_test",)]
