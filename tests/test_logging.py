from __future__ import annotations

import json

from core.logging_config import flush_logging, setup_logging


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
