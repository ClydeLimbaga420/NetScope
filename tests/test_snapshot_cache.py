from __future__ import annotations

from core.runner import CommandResult
from core.snapshot_cache import load, save


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


def test_snapshot_cache_write_is_atomic(tmp_path, snapshot_factory):
    path = tmp_path / "snapshot.json"

    save(snapshot_factory(), path)

    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
