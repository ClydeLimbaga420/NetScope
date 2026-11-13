from __future__ import annotations

import app as legacy_app


def test_legacy_dashboard_shows_speed_test_button():
    response = legacy_app.app.test_client().get("/")

    assert response.status_code == 200
    assert b'id="run-speed-test"' in response.data
    assert b'id="speed-test-status"' in response.data
    assert b'id="speed-test-results"' in response.data
    assert response.data.index(b'id="packet-loss-card"') < response.data.index(b'id="run-speed-test"') < response.data.index(b'id="traffic"')


def test_legacy_speed_test_endpoint_returns_measurements(monkeypatch):
    expected = {
        "server": "speed.cloudflare.com",
        "latency_ms": 20.0,
        "latency_samples_ms": [19.0, 20.0, 21.0],
        "download_mbps": 75.0,
        "upload_mbps": 15.0,
        "download_bytes": 10 * 1024 * 1024,
        "upload_bytes": 2 * 1024 * 1024,
    }

    class FakeProbe:
        def speed_test(self):
            return expected

    monkeypatch.setattr(legacy_app, "NetworkProbe", FakeProbe)
    response = legacy_app.app.test_client().post("/api/speed-test")

    assert response.status_code == 200
    assert response.get_json() == expected


def test_legacy_speed_test_endpoint_reports_probe_errors(monkeypatch):
    class FailingProbe:
        def speed_test(self):
            raise RuntimeError("service unavailable")

    monkeypatch.setattr(legacy_app, "NetworkProbe", FailingProbe)
    response = legacy_app.app.test_client().post("/api/speed-test")

    assert response.status_code == 502
    assert response.get_json() == {"error": "service unavailable"}
