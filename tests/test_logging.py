from __future__ import annotations

import json
import os
import threading
import time

from core.logging_config import (
    clear_logs,
    flush_logging,
    setup_logging,
    start_log_cleanup,
)


def _read_records(directory):
    records = []
    for path in sorted(directory.glob("netscope.log*")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def test_logging_writes_json_lines_with_session(tmp_path):
    logger = setup_logging("test", session_id="sess123", log_dir=tmp_path)
    logger.event("hello", value=1)
    logger.command(["ping", "1.1.1.1"], returncode=0, duration_seconds=0.1, stdout="ok")
    logger.confirmation("fix", accepted=False, fix_id="IP-01")
    flush_logging()

    records = _read_records(tmp_path)
    assert records
    required = {"ts", "level", "logger", "session_id", "event"}
    for record in records:
        assert required.issubset(record)
        assert record["session_id"] == "sess123"

    hello = next(record for record in records if record["event"] == "hello")
    assert hello["fields"]["value"] == 1

    command = next(record for record in records if record["event"] == "command")
    assert command["fields"]["args"] == ["ping", "1.1.1.1"]
    assert command["fields"]["returncode"] == 0


def test_log_records_include_pid(tmp_path):
    logger = setup_logging("test", session_id="s", log_dir=tmp_path)
    logger.event("hello")
    flush_logging()

    record = next(r for r in _read_records(tmp_path) if r["event"] == "hello")
    assert record["pid"] == os.getpid()


def test_command_output_is_bounded(tmp_path):
    logger = setup_logging("test", session_id="s", log_dir=tmp_path)
    logger.command(["ping"], stdout="x" * 5000, stderr="y" * 5000)
    flush_logging()

    record = next(r for r in _read_records(tmp_path) if r["event"] == "command")
    assert record["fields"]["stdout"] == "x" * 1000
    assert record["fields"]["stderr"] == "y" * 1000


def test_logging_redacts_secrets(tmp_path):
    logger = setup_logging("test", session_id="s", log_dir=tmp_path)
    logger.event("credential", password="hunter2", token="abc")
    flush_logging()

    records = _read_records(tmp_path)
    event = next(record for record in records if record["event"] == "credential")
    assert event["fields"]["password"] == "<redacted>"
    assert event["fields"]["token"] == "<redacted>"


def test_logging_rotation(tmp_path):
    logger = setup_logging(
        "test",
        session_id="s",
        log_dir=tmp_path,
        max_bytes=400,
        backup_count=2,
    )
    for index in range(60):
        logger.event("filler", index=index, payload="x" * 40)
    flush_logging()

    files = list(tmp_path.glob("netscope.log*"))
    assert len(files) >= 2
    assert any(path.name.endswith(".1") for path in files)
    # Every file must still contain valid JSON lines.
    assert _read_records(tmp_path)


def test_clear_logs_truncates_active_and_removes_backups(tmp_path):
    logger = setup_logging(
        "test", session_id="s", log_dir=tmp_path, max_bytes=200, backup_count=2
    )
    for index in range(40):
        logger.event("filler", index=index, payload="x" * 30)
    flush_logging()
    assert (tmp_path / "netscope.log").stat().st_size > 0
    assert list(tmp_path.glob("netscope.log.*"))

    assert clear_logs(tmp_path) is True

    assert (tmp_path / "netscope.log").read_text(encoding="utf-8") == ""
    assert not list(tmp_path.glob("netscope.log.*"))

    # The live handler must keep writing valid JSON at the start of the file.
    logger.event("after_clear", value=1)
    flush_logging()
    records = [
        json.loads(line)
        for line in (tmp_path / "netscope.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["event"] for record in records] == ["after_clear"]
    assert records[0]["fields"]["value"] == 1


def test_clear_logs_uses_active_handler_without_explicit_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("core.logging_config.config.log_dir", lambda: tmp_path)
    logger = setup_logging("test", session_id="s", log_dir=tmp_path)
    logger.event("before")
    flush_logging()
    active = tmp_path / "netscope.log"
    assert active.stat().st_size > 0

    assert clear_logs() is True
    assert active.stat().st_size == 0


def test_clear_logs_can_keep_rotated_backups(tmp_path):
    logger = setup_logging(
        "test", session_id="s", log_dir=tmp_path, max_bytes=200, backup_count=2
    )
    for index in range(40):
        logger.event("filler", index=index, payload="x" * 30)
    flush_logging()
    assert list(tmp_path.glob("netscope.log.*"))

    assert clear_logs(tmp_path, include_backups=False) is True

    assert (tmp_path / "netscope.log").stat().st_size == 0
    assert list(tmp_path.glob("netscope.log.*"))


def test_start_log_cleanup_disabled_for_nonpositive_interval():
    stop = threading.Event()
    assert start_log_cleanup(0, stop) is None
    assert start_log_cleanup(-1, stop) is None


def test_start_log_cleanup_clears_on_interval_and_stops(tmp_path):
    logger = setup_logging("test", session_id="s", log_dir=tmp_path)
    logger.event("before")
    flush_logging()
    active = tmp_path / "netscope.log"
    assert active.stat().st_size > 0

    stop = threading.Event()
    thread = start_log_cleanup(0.05, stop, log_dir=tmp_path)
    assert thread is not None
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and active.stat().st_size:
            time.sleep(0.02)
        assert active.stat().st_size == 0
    finally:
        stop.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_reinitialising_logging_does_not_duplicate_handlers(tmp_path):
    first = setup_logging("cli", session_id="a", log_dir=tmp_path)
    first.event("before")
    second = setup_logging("gui", session_id="b", log_dir=tmp_path)
    second.event("after")
    flush_logging()

    records = _read_records(tmp_path)
    after = [record for record in records if record["event"] == "after"]
    assert len(after) == 1
    assert after[0]["session_id"] == "b"
