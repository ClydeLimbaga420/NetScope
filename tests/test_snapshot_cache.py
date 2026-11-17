from __future__ import annotations

import json

import pytest

from core.runner import CommandResult
from core.snapshot_cache import CACHE_VERSION, load, save


def test_snapshot_cache_round_trip_preserves_native_and_pings(snapshot_factory, tmp_path):
    winsock = CommandResult(("netsh", "winsock"), 0, stdout="MSAFD")
    snapshot = snapshot_factory(native={"winsock_catalog": winsock})
    path = tmp_path / "snapshot.json"

    save(snapshot, path)
    loaded = load(path)

    assert loaded is not None
    assert loaded.gateway == snapshot.gateway
    assert loaded.data == snapshot.data
    assert loaded.native["winsock_catalog"].stdout == "MSAFD"
    assert loaded.pings["1.1.1.1"].latency_ms == 12.0


def test_snapshot_cache_rejects_bad_version_and_malformed_json(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text('{"version": 99}', encoding="utf-8")
    assert load(path) is None

    path.write_text("{not json", encoding="utf-8")
    assert load(path) is None
    assert load(tmp_path / "missing.json") is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(is_windows=1),
        lambda p: p["sections"].update(adapters="not-a-list"),
        lambda p: p["sections"].update(adapters=[1]),
        lambda p: p["errors"].update(dns=1),
        lambda p: p["pings"].update(host=1),
        lambda p: p["pings"].update(
            host={
                "host": "host",
                "online": True,
                "latency_ms": "12",
                "returncode": 0,
                "error": None,
            }
        ),
        lambda p: p["native"].update(
            winsock={
                "args": [],
                "returncode": 0,
                "duration_seconds": 0.1,
                "timed_out": 1,
                "error": None,
            }
        ),
        lambda p: p["native"].update(
            winsock={
                "args": [1],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "duration_seconds": 0.1,
                "timed_out": False,
                "error": None,
            }
        ),
    ],
)
def test_snapshot_cache_rejects_malformed_fields(tmp_path, mutation):
    path = tmp_path / "snapshot.json"
    payload = {
        "version": CACHE_VERSION,
        "captured_at": "2026-01-01T00:00:00+00:00",
        "is_windows": True,
        "language_mode": "FullLanguage",
        "ps_available": True,
        "constrained": False,
        "gateway": None,
        "errors": {},
        "sections": {},
        "pings": {},
        "native": {},
    }
    mutation(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load(path) is None


def test_snapshot_cache_write_is_atomic(tmp_path, snapshot_factory):
    path = tmp_path / "snapshot.json"

    save(snapshot_factory(), path)

    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
