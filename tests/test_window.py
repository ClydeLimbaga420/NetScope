from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import web.window as window
import web.run as run


def test_webview2_available_positive(monkeypatch):
    monkeypatch.setattr(window, "_webview2_version", lambda: "120.0.2210.91")
    assert window.webview2_available() is True


def test_webview2_available_missing_or_zero(monkeypatch):
    monkeypatch.setattr(window, "_webview2_version", lambda: None)
    assert window.webview2_available() is False
    monkeypatch.setattr(window, "_webview2_version", lambda: "0.0.0.0")
    assert window.webview2_available() is False


def test_run_native_window_skips_without_runtime(monkeypatch):
    monkeypatch.setattr(window, "webview2_available", lambda: False)
    assert window.run_native_window("http://127.0.0.1:1/__boot__") is False


def test_window_geometry_centers_capped_window_in_large_work_area():
    assert window._window_geometry((100, 50, 2020, 1130)) == (
        420,
        160,
        1280,
        860,
        (900, 600),
    )


def test_window_geometry_clamps_dimensions_to_small_work_area():
    assert window._window_geometry((0, 0, 800, 550)) == (
        24,
        24,
        752,
        502,
        (752, 502),
    )


def test_run_native_window_configures_edgechromium(monkeypatch):
    url = "http://127.0.0.1:54321/__boot__?token=t"
    calls = {}
    fake = SimpleNamespace(
        create_window=lambda *args, **kwargs: calls.setdefault("window", (args, kwargs)),
        start=lambda **kwargs: calls.setdefault("start", kwargs),
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(window, "webview2_available", lambda: True)
    monkeypatch.setattr(
        window, "_primary_work_area", lambda: (100, 50, 2020, 1130), raising=False
    )

    assert window.run_native_window(url) is True
    args, kwargs = calls["window"]
    assert args == ("NetScope", url)
    assert kwargs == {
        "x": 420,
        "y": 160,
        "width": 1280,
        "height": 860,
        "min_size": (900, 600),
    }
    assert calls["start"] == {"gui": "edgechromium", "debug": False}


def test_run_native_window_falls_back_when_work_area_query_fails(monkeypatch):
    def fail_to_get_work_area():
        raise OSError("work area unavailable")

    fake = SimpleNamespace(
        create_window=lambda *_args, **_kwargs: None,
        start=lambda **_kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(window, "webview2_available", lambda: True)
    monkeypatch.setattr(
        window,
        "_primary_work_area",
        fail_to_get_work_area,
        raising=False,
    )

    assert window.run_native_window("http://127.0.0.1:1/__boot__") is False


class WindowLogger:
    def __init__(self):
        self.events = []

    def warning(self, event, **fields):
        self.events.append((event, fields))

    def event(self, event, **fields):
        self.events.append((event, fields))

    def error(self, event, **fields):
        self.events.append((event, fields))


def test_launch_mode_precedence():
    assert run._launch_mode(True, True) == "headless"
    assert run._launch_mode(False, True) == "browser"
    assert run._launch_mode(False, False) == "window"


def test_show_existing_window_uses_native(monkeypatch):
    calls = []
    state = SimpleNamespace(logger=WindowLogger())
    monkeypatch.setattr(run, "run_native_window", lambda url: calls.append(url) or True)
    assert run._show_existing("http://127.0.0.1:1/boot", "window", state) is True
    assert calls == ["http://127.0.0.1:1/boot"]


def test_show_existing_browser_uses_open_url(monkeypatch):
    calls = []
    state = SimpleNamespace(logger=WindowLogger())
    monkeypatch.setattr(run, "_open_url", lambda url: calls.append(url) or True)
    assert run._show_existing("http://127.0.0.1:1/boot", "browser", state) is True
    assert calls == ["http://127.0.0.1:1/boot"]


def test_show_existing_headless_prints(monkeypatch, capsys):
    state = SimpleNamespace(logger=WindowLogger())
    assert run._show_existing("http://127.0.0.1:1/boot", "headless", state) is True
    assert capsys.readouterr().out.strip() == "http://127.0.0.1:1/boot"


def test_window_session_falls_back_to_browser(monkeypatch):
    state = SimpleNamespace(shutdown_event=threading.Event(), logger=WindowLogger())
    srv = SimpleNamespace(serve_forever=lambda: None)
    calls = []

    def unavailable(_url):
        state.shutdown_event.set()
        return False

    monkeypatch.setattr(run, "run_native_window", unavailable)
    monkeypatch.setattr(run, "_open_url", lambda url: calls.append(url) or True)
    run._run_window_session(state, srv, "http://127.0.0.1:1/boot", False)
    assert calls == ["http://127.0.0.1:1/boot"]
    assert any(event == "webview_unavailable" for event, _ in state.logger.events)


def test_window_close_does_not_stop_shared_server(monkeypatch):
    class RecordingEvent:
        def __init__(self):
            self.waited = False
            self.stopped = False

        def wait(self):
            self.waited = True

        def set(self):
            self.stopped = True

    event = RecordingEvent()
    state = SimpleNamespace(shutdown_event=event, logger=WindowLogger())
    srv = SimpleNamespace(serve_forever=lambda: None)
    monkeypatch.setattr(run, "run_native_window", lambda _url: True)

    run._run_window_session(state, srv, "http://127.0.0.1:1/boot", False)

    assert event.waited is True
    assert event.stopped is False


def test_replace_waits_for_lock(monkeypatch):
    token = object()
    attempts = iter([None, None, token])
    times = iter([0.0, 0.0, 0.2, 0.4, 0.6])
    monkeypatch.setattr(run, "_acquire_instance_lock", lambda: next(attempts))
    monkeypatch.setattr(run.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: None)
    assert run._acquire_lock_with_wait(10.0) is token
