from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
import web.run as run
import web.window as window
from core import disk_space
from core.disk_space import DiskSpace
from core.monitoring import MonitoringService, NetworkCounters
from core.runner import FakeRunner


class Recorder:
    def __init__(self):
        self.events = []

    def event(self, name, **fields):
        self.events.append((name, fields))

    def warning(self, name, **fields):
        self.events.append((name, fields))

    def error(self, name, **fields):
        self.events.append((name, fields))


def _low(*_args, **_kwargs):
    return DiskSpace(path="low", total=1000, used=999, free=1)


def _high(*_args, **_kwargs):
    return DiskSpace(path="high", total=1000, used=100, free=900 * 1024 * 1024)


def test_probe_walks_up_to_existing_ancestor(monkeypatch, tmp_path):
    seen = []

    def fake_usage(path):
        seen.append(path)
        return SimpleNamespace(total=100, used=60, free=40)

    monkeypatch.setattr(disk_space.shutil, "disk_usage", fake_usage)
    target = tmp_path / "missing" / "nested"
    info = disk_space.probe(target)

    assert info is not None
    assert info.path == str(target)
    assert info.free == 40
    assert info.free_mb == 0.0
    assert seen == [tmp_path]


def test_probe_fails_open_when_space_is_unknown(monkeypatch, tmp_path):
    def fail(_path):
        raise OSError(5, "access denied")

    monkeypatch.setattr(disk_space.shutil, "disk_usage", fail)
    assert disk_space.probe(tmp_path) is None
    assert disk_space.free_bytes(tmp_path) is None
    assert disk_space.is_low(tmp_path) is False


def test_is_low_uses_configured_threshold(monkeypatch, tmp_path):
    monkeypatch.setattr(disk_space, "probe", lambda *_a, **_k: DiskSpace("x", 100, 90, 10))
    monkeypatch.setattr(config, "MIN_FREE_DISK_BYTES", 20)
    assert disk_space.is_low(tmp_path) is True
    monkeypatch.setattr(config, "MIN_FREE_DISK_BYTES", 5)
    assert disk_space.is_low(tmp_path) is False


def test_prune_files_enforces_count_and_protection(tmp_path):
    now = time.time()
    paths = []
    for index in range(6):
        path = tmp_path / f"report-{index}.txt"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (now - 100 + index, now - 100 + index))
        paths.append(path)

    result = disk_space.prune_files(tmp_path, max_files=2, protect=[paths[-1]])

    assert result.removed == 3
    assert paths[-1].exists()
    assert paths[-2].exists()
    assert not paths[0].exists()


def test_prune_files_enforces_byte_cap(tmp_path):
    now = time.time()
    paths = []
    for index in range(5):
        path = tmp_path / f"backup-{index}.json"
        path.write_bytes(b"x" * 10)
        os.utime(path, (now - 50 + index, now - 50 + index))
        paths.append(path)

    result = disk_space.prune_files(tmp_path, max_bytes=25)

    assert result.removed == 3
    assert result.bytes_freed == 30
    assert paths[3].exists() and paths[4].exists()


def test_prune_files_removes_aged_entries(tmp_path):
    now = time.time()
    old = tmp_path / "old.txt"
    fresh = tmp_path / "fresh.txt"
    old.write_text("x", encoding="utf-8")
    fresh.write_text("x", encoding="utf-8")
    os.utime(old, (now - 10000, now - 10000))
    os.utime(fresh, (now, now))

    result = disk_space.prune_files(tmp_path, max_age_seconds=5000)

    assert result.removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_prune_files_never_raises_on_unlink_failure(tmp_path, monkeypatch):
    path = tmp_path / "stuck.txt"
    path.write_text("x", encoding="utf-8")

    def fail_unlink(self, *args, **kwargs):
        raise OSError(5, "access denied")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    result = disk_space.prune_files(tmp_path, max_files=0)

    assert result.removed == 0
    assert path.exists()


def test_prepare_report_write_prunes_and_logs_low_disk(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    for index in range(3):
        (reports / f"report-{index}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(config, "REPORT_MAX_FILES", 1)
    monkeypatch.setattr(disk_space, "probe", _low)
    logger = Recorder()

    result = disk_space.prepare_report_write(reports, logger)

    assert result.removed == 2
    event = next(fields for name, fields in logger.events if name == "disk_space_low")
    assert event["kind"] == "reports"
    assert event["free_bytes"] == 1


def test_should_skip_optional_write(monkeypatch, tmp_path):
    logger = Recorder()
    monkeypatch.setattr(disk_space, "probe", _low)
    assert disk_space.should_skip_optional_write(tmp_path, logger, kind="snapshot_cache") is True
    assert logger.events[0][0] == "optional_write_skipped"
    assert logger.events[0][1]["kind"] == "snapshot_cache"

    monkeypatch.setattr(disk_space, "probe", _high)
    assert disk_space.should_skip_optional_write(tmp_path, logger) is False


def test_log_status_emits_structured_space_event(tmp_path, monkeypatch):
    monkeypatch.setattr(
        disk_space,
        "probe",
        lambda *_a, **_k: DiskSpace(path=str(tmp_path), total=1000, used=750, free=250),
    )
    logger = Recorder()
    info = disk_space.log_status(logger, tmp_path)

    assert info is not None
    assert logger.events[0][0] == "disk_space_status"
    assert logger.events[0][1]["free_bytes"] == 250
    assert "low" in logger.events[0][1]


def test_snapshot_refresh_skips_disk_cache_when_low(tmp_path, monkeypatch, snapshot_factory):
    snapshot = snapshot_factory()
    engine = SimpleNamespace(collect_snapshot=lambda: snapshot)
    logger = Recorder()
    service = MonitoringService(
        engine,
        FakeRunner(),
        None,
        counter_provider=lambda: NetworkCounters(0, 0),
        clock=time.monotonic,
        logger=logger,
        cache_path=tmp_path / "snapshot.json",
    )
    saved = []
    monkeypatch.setattr("core.monitoring.save_snapshot_cache", lambda *args: saved.append(args))
    monkeypatch.setattr(disk_space, "probe", _low)

    service._refresh_snapshot()

    assert saved == []
    assert any(name == "snapshot_cache_skipped" for name, _ in logger.events)
    assert service.get_snapshot() is snapshot


def test_web_ui_start_failure_releases_instance_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    recorder = Recorder()

    def failing_state(mode="web"):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(run, "WebState", failing_state)
    monkeypatch.setattr(run, "setup_logging", lambda *args, **kwargs: recorder)
    monkeypatch.setattr(run, "cleanup_processes", lambda *_args: None)
    monkeypatch.setattr(run, "_remove_lock", lambda *_args: None)
    released = []
    monkeypatch.setattr(run, "_release_instance_lock", lambda handle: released.append(handle))

    assert run.run_web_ui(no_browser=True) == 1
    assert len(released) == 1
    assert released[0] is not None
    assert any(name == "web_ui_start_failed" for name, _ in recorder.events)


def test_monitor_survives_transient_tick_error(monkeypatch):
    calls = []

    def tick(state, interval):
        calls.append(interval)
        if len(calls) == 1:
            raise OSError(28, "No space left on device")
        raise SystemExit(0)

    monkeypatch.setattr(run, "_monitor_tick", tick)
    state = SimpleNamespace(shutdown_event=threading.Event(), logger=Recorder())

    with pytest.raises(SystemExit):
        run._monitor(state, interval=0.01)

    assert calls == [0.01, 0.01]
    assert any(name == "monitor_error" for name, _ in state.logger.events)


def test_window_heartbeat_survives_touch_failure(monkeypatch):
    touched = []

    def failing_touch():
        touched.append(1)
        raise OSError(28, "No space left on device")

    state = SimpleNamespace(
        shutdown_event=threading.Event(),
        logger=Recorder(),
        touch=failing_touch,
    )
    srv = SimpleNamespace(serve_forever=lambda: None)

    def fake_window(_url, **_kwargs):
        deadline = time.monotonic() + 1
        while len(touched) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        state.shutdown_event.set()
        return True

    monkeypatch.setattr(run, "run_native_window", fake_window)
    monkeypatch.setattr(run, "WINDOW_HEARTBEAT_INTERVAL_SECONDS", 0.01)

    run._run_window_session(state, srv, "http://127.0.0.1:1/boot", False)

    assert len(touched) >= 2
    assert any(name == "window_heartbeat_failed" for name, _ in state.logger.events)


def test_webview_storage_path_configurable(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "WEBVIEW_STORAGE_ENABLED", True)
    assert window.webview_storage_path() == tmp_path / "webview"
    monkeypatch.setattr(config, "WEBVIEW_STORAGE_ENABLED", False)
    assert window.webview_storage_path() is None


def test_native_window_uses_bounded_storage_path(monkeypatch, tmp_path):
    calls = {}

    def start(gui=None, debug=False, storage_path=None):
        calls["start"] = {"gui": gui, "debug": debug, "storage_path": storage_path}

    fake = SimpleNamespace(
        create_window=lambda *_args, **_kwargs: None,
        start=start,
        destroy_window=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(window, "webview2_available", lambda: True)
    monkeypatch.setattr(window, "_primary_work_area", lambda: (0, 0, 1920, 1080))
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "WEBVIEW_STORAGE_ENABLED", True)

    assert window.run_native_window("http://127.0.0.1:1/boot") is True
    assert calls["start"]["storage_path"] == str(tmp_path / "webview")
    assert (tmp_path / "webview").is_dir()
