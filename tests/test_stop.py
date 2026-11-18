from __future__ import annotations

import contextlib
import json

import pytest

import cli.stop as stop
import config
from cli import exit_codes
from cli.commands import cmd_stop
from tests.test_cli import make_ctx, parse


class FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, session_token: str = "session-token", shutdown_status: int = 200) -> None:
        self.session_token = session_token
        self.shutdown_status = shutdown_status
        self.calls: list[str] = []

    def open(self, target, timeout=None):
        url = target if isinstance(target, str) else target.full_url
        self.calls.append(url)
        if "/__session__" in url:
            return FakeResponse(body=json.dumps({"token": self.session_token}).encode())
        if "/api/shutdown" in url:
            assert target.get_header("X-netscope-token") == self.session_token
            assert target.get_header("Origin") == "http://127.0.0.1:54321"
            assert target.get_header("Content-type") == "application/json"
            return FakeResponse(status=self.shutdown_status)
        return FakeResponse()


@pytest.fixture
def lock_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    path = tmp_path / "web-ui.json"
    path.write_text(json.dumps({"port": 54321, "boot_token": "boot-token"}), encoding="utf-8")
    return path


@pytest.fixture
def fake_network(monkeypatch):
    opener = FakeOpener()
    monkeypatch.setattr(stop.socket, "create_connection", lambda *_args, **_kwargs: contextlib.nullcontext())
    monkeypatch.setattr(stop.urllib.request, "build_opener", lambda *_args: opener)
    return opener


def test_read_lock_returns_valid_record(lock_file):
    assert stop.read_lock() == {"port": 54321, "boot_token": "boot-token"}


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        "{}",
        '{"port": 0, "boot_token": "t"}',
        '{"port": 70000, "boot_token": "t"}',
        '{"port": true, "boot_token": "t"}',
        '{"port": 54321, "boot_token": ""}',
        '{"port": 54321, "boot_token": "bad token"}',
        '{"port": 54321, "boot_token": "a" * 257}',
    ],
)
def test_read_lock_rejects_invalid_records(lock_file, payload):
    lock_file.write_text(payload, encoding="utf-8")
    assert stop.read_lock() is None


def test_read_lock_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    assert stop.read_lock() is None


def test_stop_running_ui_sends_authenticated_shutdown(lock_file, fake_network):
    assert stop.stop_running_ui() == "stopped"
    assert len(fake_network.calls) == 3
    assert "/__boot__?token=boot-token" in fake_network.calls[0]
    assert fake_network.calls[1] == "http://127.0.0.1:54321/__session__"
    assert fake_network.calls[2] == "http://127.0.0.1:54321/api/shutdown"


def test_stop_running_ui_not_running_without_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    assert stop.stop_running_ui() == "not_running"


def test_stop_running_ui_not_running_on_stale_lock(lock_file, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("closed")

    monkeypatch.setattr(stop.socket, "create_connection", refuse)
    assert stop.stop_running_ui() == "not_running"


def test_stop_running_ui_error_when_session_has_no_token(lock_file, monkeypatch):
    monkeypatch.setattr(stop.socket, "create_connection", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(
        stop.urllib.request,
        "build_opener",
        lambda *_args: FakeOpener(session_token=""),
    )
    assert stop.stop_running_ui() == "error"


def test_stop_running_ui_error_on_shutdown_rejection(lock_file, monkeypatch):
    monkeypatch.setattr(stop.socket, "create_connection", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(
        stop.urllib.request,
        "build_opener",
        lambda *_args: FakeOpener(shutdown_status=403),
    )
    assert stop.stop_running_ui() == "error"


@pytest.mark.parametrize(
    ("result", "expected_code", "message"),
    [
        ("stopped", exit_codes.OK, "NetScope stopped."),
        ("not_running", exit_codes.OK, "NetScope is not running."),
        ("error", exit_codes.FAILURES, "could not stop NetScope"),
    ],
)
def test_cmd_stop_reports_result(monkeypatch, result, expected_code, message):
    monkeypatch.setattr("cli.stop.stop_running_ui", lambda: result)
    ctx = make_ctx()
    args = parse(["stop"])

    assert cmd_stop(args, ctx) == expected_code
    assert message in ctx.stdout.getvalue() or message in ctx.stderr.getvalue()


def test_stop_command_is_registered():
    assert parse(["stop"]).command == "stop"
