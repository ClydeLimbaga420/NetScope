from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request

import config
from web import run
from web.server import _configure_werkzeug


def test_instance_lock_is_exclusive_until_released(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)

    first = run._acquire_instance_lock()
    second = run._acquire_instance_lock()
    assert first is not None
    assert second is None

    run._release_instance_lock(first)
    third = run._acquire_instance_lock()
    assert third is not None
    run._release_instance_lock(third)


def test_lock_cleanup_only_removes_current_owner_record(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    run._write_lock(54321, "boot-secret", 1234)

    run._remove_lock(5678)
    assert json.loads(run._lock_path().read_text(encoding="utf-8"))["pid"] == 1234

    run._remove_lock(1234)
    assert not run._lock_path().exists()


def test_existing_instance_requires_valid_local_health_probe(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            return b"ok"

    class Opener:
        def open(self, url, timeout):
            assert url == "http://127.0.0.1:54321/health"
            assert timeout == 1
            return Response()

    monkeypatch.setattr(run, "_port_open", lambda _port: True)
    monkeypatch.setattr(run.urllib.request, "build_opener", lambda *_handlers: Opener())
    lock = {"port": 54321, "boot_token": "boot-token", "pid": 1234}

    assert run._existing_instance_url(lock) == (
        "http://127.0.0.1:54321/__boot__?token=boot-token"
    )
    assert run._existing_instance_url({"port": True, "boot_token": "x"}) is None


def test_existing_instance_rejects_non_netscope_service(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            return b"other service"

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(run, "_port_open", lambda _port: True)
    monkeypatch.setattr(run.urllib.request, "build_opener", lambda *_handlers: Opener())

    assert run._existing_instance_url({"port": 54321, "boot_token": "token"}) is None


def test_werkzeug_request_logs_route_to_netscope_without_duplicate_handlers():
    class Recorder:
        def __init__(self):
            self.events = []

        def event(self, name, **fields):
            self.events.append((name, fields))

    log = logging.getLogger("werkzeug")
    original_handlers = log.handlers[:]
    original_level = log.level
    original_propagate = log.propagate
    recorder = Recorder()
    try:
        _configure_werkzeug(recorder)
        log.handle(logging.LogRecord(
            "werkzeug", logging.INFO, __file__, 1, '127.0.0.1 "GET /health HTTP/1.1" 200', (), None
        ))
        _configure_werkzeug(recorder)

        assert len(log.handlers) == 1
        assert len(recorder.events) == 1
        name, fields = recorder.events[0]
        assert name == "werkzeug"
        assert fields["source"] == "web"
        assert fields["level"] == "INFO"
        assert "GET /health" in fields["message"]
    finally:
        log.handlers = original_handlers
        log.setLevel(original_level)
        log.propagate = original_propagate


def test_source_cli_starts_local_web_server(tmp_path):
    port = run._find_free_port()
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_path)
    process = subprocess.Popen(
        [sys.executable, "-m", "cli", "gui", "--no-browser", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output: queue.Queue[str] = queue.Queue()

    def read_output():
        if process.stdout is None:
            return
        for line in process.stdout:
            output.put(line)

    threading.Thread(target=read_output, daemon=True).start()
    try:
        boot_url = output.get(timeout=15).strip()
        assert boot_url.startswith(f"http://127.0.0.1:{port}/__boot__?token=")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with opener.open(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                    assert response.status == 200
                    assert response.read(16).strip() == b"ok"
                    break
            except OSError:
                if process.poll() is not None:
                    raise AssertionError("web UI process exited before the health check")
                time.sleep(0.05)
        else:
            raise AssertionError("web UI did not become healthy before the deadline")
        try:
            startup_noise = output.get(timeout=0.1)
        except queue.Empty:
            startup_noise = ""
        assert "Serving Flask app" not in startup_noise
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if process.stdout:
            process.stdout.close()
