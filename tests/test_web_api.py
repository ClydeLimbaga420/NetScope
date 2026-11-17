from __future__ import annotations

import types
import shutil
import threading
import time

import pytest

from core.checks.descriptors import CHECK_DESCRIPTORS
from core.monitoring import MonitorTaskResult, MonitoringService, NetworkCounters
from core.runner import CommandResult, FakeRunner, SubprocessRunner
from fixes.catalog import load_catalog
from fixes.executor import FixExecutor
from web.server import WebState, create_app


class DummyResult:
    def __init__(self, status="pass", layer="adapter", id="ADP-01"):
        self.status = types.SimpleNamespace(value=status)
        self.layer = types.SimpleNamespace(value=layer)
        self.id = id
        self.title = "t"
        self.message = "m"
        self.cause = None
        self.evidence = {}
        self.fix_ids = []

    def to_dict(self):
        return {"id": self.id, "layer": self.layer.value, "status": self.status.value, "title": self.title, "message": self.message, "cause": self.cause, "evidence": self.evidence, "fix_ids": self.fix_ids}


class DummyReport:
    def __init__(self):
        self.results = [DummyResult("fail", "ip", "IP-01"), DummyResult("pass", "adapter", "ADP-01")]
        self.overall_status = types.SimpleNamespace(value="fail")
        self.first_failing_layer = types.SimpleNamespace(value="ip")
        self.exit_code = 2
        self.session_id = "s"
        self.mode = "web"

    def to_dict(self, include_snapshot=False):
        return {"results": [r.to_dict() for r in self.results], "overall_status": self.overall_status.value, "first_failing_layer": self.first_failing_layer.value, "exit_code": self.exit_code, "summary": {"fail":1,"pass":1,"warn":0,"skip":0,"error":0}}


class DummySnap:
    def to_dict(self):
        return {}


class DummyEngine:
    def collect_snapshot(self):
        return DummySnap()

    def diagnose(self, layers=None, snapshot=None, on_check=None, mode="cli", check_ids=None):
        if on_check:
            on_check(DummyResult("fail", "ip", "IP-01"))
        return DummyReport()


class FakeMonitoringService:
    def __init__(
        self, *, status=None, devices=None, packet_loss=None, status_error=None
    ):
        self.status = status
        self.devices = devices or MonitorTaskResult("ready", value=[])
        self.packet_loss = packet_loss or MonitorTaskResult("ready", value={})
        self.calls = []
        self.status_error = status_error

    def get_status(self):
        self.calls.append(("get_status",))
        if self.status_error:
            raise self.status_error
        return self.status

    def request_devices(self, force=False):
        self.calls.append(("request_devices", force))
        return self.devices

    def request_packet_loss(self, force=False):
        self.calls.append(("request_packet_loss", force))
        return self.packet_loss


@pytest.fixture
def web_state(monkeypatch):
    st = WebState.__new__(WebState)
    st.mode = "web"
    st.port = 5000
    from web.security import WebSecurity
    from web.jobs import JobManager
    st.security = WebSecurity()
    st.jobs = JobManager()
    import logging
    class NL:
        session_id = "s1"
        def event(self,*a,**k): pass
        def action(self,*a,**k): pass
        def warning(self,*a,**k): pass
        def __init__(self):
            self.errors = []
        def error(self,*a,**k):
            self.errors.append((a, k))
        def confirmation(self,*a,**k): pass
        def fix_applied(self,*a,**k): pass
        def debug(self,*a,**k): pass
    st.logger = NL()
    st.session_id = "s1"
    st.last_heartbeat = __import__('time').monotonic()
    st.shutdown_event = __import__('threading').Event()
    st.fix_lock = __import__('threading').Lock()
    st.last_snapshot = None
    st.last_report = None
    # runtime
    st.runtime = types.SimpleNamespace(
        engine=DummyEngine(),
        catalog=types.SimpleNamespace(require=lambda x: (_ for _ in ()).throw(Exception("no"))),
        ps=None,
        runner=None,
        executor=lambda: None,
        logger=st.logger,
        monitoring=FakeMonitoringService(
            status={
                "network": {},
                "traffic": {},
                "internet_ping": {},
                "gateway_ping": {},
                "problems": [],
            }
        ),
    )
    return st


@pytest.fixture
def client(web_state):
    app = create_app(web_state)
    app.config["TESTING"] = True
    return app.test_client(), web_state


def test_host_rejected(client):
    c, st = client
    r = c.get('/api/status', headers={'Host': 'evil.example.com'})
    assert r.status_code == 403


def test_api_requires_cookie(client):
    c, st = client
    r = c.get('/api/status', headers={'Host': '127.0.0.1:5000'})
    assert r.status_code == 401


def test_session_and_status(client):
    c, st = client
    # boot -> cookie
    r = c.get(f'/__boot__?token={st.security.boot_token}', headers={'Host': '127.0.0.1:5000'}, follow_redirects=False)
    assert r.status_code in (302, 303)
    r = c.get('/__session__', headers={'Host': '127.0.0.1:5000'})
    assert r.status_code == 200
    token = r.get_json()['token']
    r = c.get('/api/status', headers={'Host': '127.0.0.1:5000'})
    assert r.status_code == 200
    assert r.get_json()['app'] == 'NetScope'
    # POST needs header
    r = c.post('/api/heartbeat', headers={'Host': '127.0.0.1:5000'}, json={})
    assert r.status_code == 403
    r = c.post('/api/heartbeat', headers={'Host': '127.0.0.1:5000', 'Origin': 'http://127.0.0.1:5000', 'X-NetScope-Token': token, 'Content-Type': 'application/json'}, json={})
    assert r.status_code == 200


def test_status_payload_contract(client, monkeypatch):
    import config

    c, st = client
    network = {
        "hostname": "netscope-host",
        "local_ip": "192.168.1.25",
        "gateway": "192.168.1.1",
        "interfaces": [
            {
                "name": "Ethernet",
                "ipv4": "192.168.1.25",
                "mac": "00:11:22:33:44:55",
                "is_up": True,
                "speed_mbps": 1000,
            }
        ],
        "interface_count": 1,
        "diagnosis": {
            "issues": [
                {"severity": "warning", "message": "A configuration warning."}
            ]
        },
    }
    traffic = {
        "download_bytes_sec": 1200.0,
        "upload_bytes_sec": 300.0,
        "download_mbps": 0.01,
        "upload_mbps": 0.002,
        "total_received_bytes": 10000,
        "total_sent_bytes": 2000,
    }
    pings = {
        "1.1.1.1": {"host": "1.1.1.1", "latency_ms": 12.5, "online": True},
        "192.168.1.1": {
            "host": "192.168.1.1",
            "latency_ms": 1.5,
            "online": True,
        },
    }
    monitoring = FakeMonitoringService(
        status={
            "network": network,
            "traffic": traffic,
            "internet_ping": pings["1.1.1.1"],
            "gateway_ping": pings["192.168.1.1"],
            "problems": [
                {
                    "source": "configuration",
                    "severity": "warning",
                    "message": "A configuration warning.",
                }
            ],
        }
    )
    st.runtime.monitoring = monitoring
    monkeypatch.setattr("web.api.is_admin", lambda: True)
    st.runtime.ps = object()
    _boot(c, st)

    response = c.get("/api/status", headers={"Host": "127.0.0.1:5000"})
    payload = response.get_json()

    assert response.status_code == 200
    assert set(payload) == {
        "network",
        "traffic",
        "internet_ping",
        "gateway_ping",
        "problems",
        "app",
        "version",
        "admin",
        "session_id",
        "dry_run_default",
        "powershell",
    }
    assert payload["network"] == network
    assert payload["traffic"] == traffic
    assert payload["internet_ping"] == pings["1.1.1.1"]
    assert payload["gateway_ping"] == pings["192.168.1.1"]
    assert payload["problems"] == [
        {
            "source": "configuration",
            "severity": "warning",
            "message": "A configuration warning.",
        }
    ]
    assert payload["app"] == config.APP_NAME
    assert payload["version"] == config.APP_VERSION
    assert payload["admin"] is True
    assert payload["session_id"] == st.session_id
    assert payload["dry_run_default"] is False
    assert payload["powershell"] == {"available": True}
    assert monitoring.calls == [("get_status",)]


def test_devices_payload_contract(client):
    c, st = client
    devices = [
        {
            "name": "Router",
            "ip": "192.168.1.1",
            "mac": "00:11:22:33:44:55",
            "type": "dynamic",
            "vendor": "Example Networks",
            "interface_ip": "192.168.1.25",
            "hardware_mac": None,
            "mac_randomized": False,
            "mac_note": "MAC reported on the local network",
            "connection": "Router",
            "connection_detail": "Default gateway",
        }
    ]
    monitoring = FakeMonitoringService(
        devices=MonitorTaskResult("ready", value=devices)
    )
    st.runtime.monitoring = monitoring
    _boot(c, st)

    response = c.get("/api/devices", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 200
    assert response.get_json() == {"devices": devices}
    assert set(response.get_json()["devices"][0]) == {
        "name",
        "ip",
        "mac",
        "type",
        "vendor",
        "interface_ip",
        "hardware_mac",
        "mac_randomized",
        "mac_note",
        "connection",
        "connection_detail",
    }
    assert monitoring.calls == [("request_devices", False)]


def test_packet_loss_payload_contract(client):
    c, st = client
    network = {"gateway": "192.168.1.1"}
    ping_stats = {
        "1.1.1.1": {
            "host": "1.1.1.1",
            "latency_ms": 14.0,
            "online": True,
            "packet_loss_percent": 10.0,
            "packets_sent": 10,
            "packets_received": 9,
        },
        "192.168.1.1": {
            "host": "192.168.1.1",
            "latency_ms": 1.0,
            "online": True,
            "packet_loss_percent": 0.0,
            "packets_sent": 10,
            "packets_received": 10,
        },
    }
    monitoring = FakeMonitoringService(
        packet_loss=MonitorTaskResult(
            "ready",
            value={
                "count": 10,
                "internet": ping_stats["1.1.1.1"],
                "gateway": ping_stats["192.168.1.1"],
            },
        )
    )
    st.runtime.monitoring = monitoring
    _boot(c, st)

    response = c.get("/api/packet-loss", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 200
    assert response.get_json() == {
        "count": 10,
        "internet": ping_stats["1.1.1.1"],
        "gateway": ping_stats["192.168.1.1"],
    }
    assert monitoring.calls == [("request_packet_loss", False)]


def test_monitoring_status_collection_failure_is_logged_and_returned(client):
    c, st = client
    monitoring = FakeMonitoringService(status_error=RuntimeError("snapshot failed"))
    st.runtime.monitoring = monitoring
    _boot(c, st)

    response = c.get("/api/status", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 500
    assert response.get_json() == {
        "error": {"code": "status_failed", "message": "snapshot failed"}
    }
    assert st.logger.errors


def test_monitoring_devices_pending_is_not_returned_as_an_empty_success(
    client,
):
    c, st = client
    monitoring = FakeMonitoringService(
        devices=MonitorTaskResult("pending")
    )
    st.runtime.monitoring = monitoring
    _boot(c, st)

    response = c.get("/api/devices", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 202
    assert response.get_json() == {"state": "pending"}


def test_monitoring_devices_failure_is_logged_and_explicit(client):
    c, st = client
    monitoring = FakeMonitoringService(
        devices=MonitorTaskResult("error", error="ARP table unavailable")
    )
    st.runtime.monitoring = monitoring
    _boot(c, st)

    response = c.get("/api/devices", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 500
    assert response.get_json() == {
        "error": {"code": "devices_failed", "message": "ARP table unavailable"}
    }
    assert st.logger.errors


def test_monitoring_packet_loss_pending_is_not_returned_as_an_empty_success(
    client,
):
    c, st = client
    monitoring = FakeMonitoringService(
        packet_loss=MonitorTaskResult("pending")
    )
    st.runtime.monitoring = monitoring
    _boot(c, st)

    response = c.get("/api/packet-loss", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 202
    assert response.get_json() == {"state": "pending"}


def test_monitoring_packet_loss_failure_is_logged_and_explicit(client):
    c, st = client
    monitoring = FakeMonitoringService(
        packet_loss=MonitorTaskResult("error", error="ping command timed out")
    )
    st.runtime.monitoring = monitoring
    _boot(c, st)

    response = c.get("/api/packet-loss", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 500
    assert response.get_json() == {
        "error": {"code": "packet_loss_failed", "message": "ping command timed out"}
    }
    assert st.logger.errors


def test_monitoring_api_status_returns_while_workers_are_blocked(
    client, snapshot_factory
):
    c, st = client
    snapshot = snapshot_factory()
    devices_started = threading.Event()
    release_devices = threading.Event()
    packet_loss_started = threading.Event()
    release_packet_loss = threading.Event()

    class BlockingRunner:
        def __init__(self):
            self.lock = threading.Lock()
            self.ping_calls = 0

        def run(self, args, *, timeout=None, **_kwargs):
            with self.lock:
                self.ping_calls += 1
                if self.ping_calls == 2:
                    packet_loss_started.set()
            release_packet_loss.wait(2)
            output = (
                "Packets: Sent = 10, Received = 10, Lost = 0 (0% loss)\n"
                "Minimum = 1ms, Maximum = 2ms, Average = 1ms"
            )
            return CommandResult(tuple(args), 0, stdout=output)

    runner = BlockingRunner()
    engine = types.SimpleNamespace(collect_snapshot=lambda: snapshot)
    monitoring = MonitoringService(
        engine,
        runner,
        None,
        counter_provider=lambda: NetworkCounters(1000, 1000),
        clock=time.monotonic,
        logger=st.logger,
    )

    def blocked_discovery(_snapshot, *, force=False):
        devices_started.set()
        release_devices.wait(2)
        return []

    monitoring.device_discovery.discover = blocked_discovery
    st.runtime.monitoring = monitoring
    st.runtime.ps = object()
    _boot(c, st)

    try:
        devices = c.get("/api/devices", headers={"Host": "127.0.0.1:5000"})
        packet_loss = c.get(
            "/api/packet-loss", headers={"Host": "127.0.0.1:5000"}
        )
        assert devices.status_code == 202
        assert packet_loss.status_code == 202
        assert devices_started.wait(1)
        assert packet_loss_started.wait(1)

        started = time.monotonic()
        response = c.get("/api/status", headers={"Host": "127.0.0.1:5000"})

        assert response.status_code == 200
        assert time.monotonic() - started < 0.5
    finally:
        release_devices.set()
        release_packet_loss.set()


def test_runtime_construction_owns_monitoring_service(snapshot_factory, monkeypatch):
    import psutil

    from cli.context import create_context
    from core.logging_config import NullLogger
    from web.runtime import build_monitoring_service, build_runtime, runtime_from_context

    runtime = build_runtime()
    assert isinstance(runtime.monitoring, MonitoringService)

    context = create_context("monitoring-test", logger=NullLogger())
    context_runtime = runtime_from_context(context)
    assert isinstance(context_runtime.monitoring, MonitoringService)

    monkeypatch.setattr(
        psutil,
        "net_io_counters",
        lambda: types.SimpleNamespace(bytes_recv=1234, bytes_sent=5678),
    )
    monitoring = build_monitoring_service(
        types.SimpleNamespace(collect_snapshot=snapshot_factory),
        FakeRunner(),
        None,
        NullLogger(),
    )
    traffic = monitoring.get_status()["traffic"]
    assert traffic["total_received_bytes"] == 1234
    assert traffic["total_sent_bytes"] == 5678


def test_checks_endpoint_lists_planned_check_descriptions(client):
    c, st = client
    c.get(f'/__boot__?token={st.security.boot_token}', headers={'Host': '127.0.0.1:5000'})
    r = c.get('/api/checks', headers={'Host': '127.0.0.1:5000'})
    assert r.status_code == 200
    checks = r.get_json()['checks']
    assert len(checks) == len(CHECK_DESCRIPTORS)
    for entry, descriptor in zip(checks, CHECK_DESCRIPTORS):
        assert entry['id'] == descriptor.id
        assert entry['layer'] == descriptor.layer.value
        assert entry['title'] == descriptor.title
        assert entry['description'].strip(), f"{descriptor.id} is missing its plain-language description"


def test_diagnose_job(client):
    c, st = client
    c.get(f'/__boot__?token={st.security.boot_token}', headers={'Host': '127.0.0.1:5000'})
    token = c.get('/__session__', headers={'Host': '127.0.0.1:5000'}).get_json()['token']
    r = c.post('/api/diagnose', headers={'Host': '127.0.0.1:5000', 'Origin': 'http://127.0.0.1:5000', 'X-NetScope-Token': token, 'Content-Type': 'application/json'}, json={})
    assert r.status_code == 200
    job_id = r.get_json()['job_id']
    # wait
    import time
    for _ in range(50):
        j = c.get(f'/api/jobs/{job_id}', headers={'Host': '127.0.0.1:5000'}).get_json()
        if j['status'] in ('done','error'):
            break
        time.sleep(0.05)
    assert j['status'] == 'done'
    assert j['result']['overall_status'] == 'fail'
    expected_report = st.last_report.to_dict(include_snapshot=False)
    assert j["result"] == expected_report
    rf = c.get('/api/findings', headers={'Host': '127.0.0.1:5000'})
    assert rf.status_code == 200
    assert len(rf.get_json()['findings']) == 1
    assert rf.get_json()["report"] == expected_report


def test_report_api_matches_cli_report_payload_contract(client, monkeypatch):
    c, st = client
    st.last_report = DummyReport()
    st.last_snapshot = DummySnap()
    monkeypatch.setattr("web.api.build_info", lambda _snapshot: {"adapters": []})
    monkeypatch.setattr(
        "web.api.build_unresolved_sections",
        lambda _report, _catalog: [{"fix_id": "IP-01"}],
    )
    monkeypatch.setattr("web.api.load_catalog", lambda: object())
    _boot(c, st)

    response = c.get("/api/report?format=json", headers={"Host": "127.0.0.1:5000"})
    payload = response.get_json()

    assert response.status_code == 200
    assert set(payload) == {"info", "diagnostic", "unresolved"}
    assert payload["info"] == {"adapters": []}
    assert payload["diagnostic"] == st.last_report.to_dict(include_snapshot=False)
    assert payload["unresolved"] == [{"fix_id": "IP-01"}]


def test_job_events_endpoint_streams_sse(client):
    c, st = client
    _boot(c, st)
    job = st.jobs.create("test")
    st.jobs.submit(job, lambda _job: {"ok": True})
    import time
    deadline = time.monotonic() + 2
    while job.status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)

    response = c.get(f"/api/jobs/{job.id}/events", headers={"Host": "127.0.0.1:5000"})
    payload = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert '"type": "result"' in payload
    assert '"ok": true' in payload
    assert '"type": "end"' in payload


def test_sse_disconnect_keeps_job_pollable(client):
    c, st = client
    _boot(c, st)
    started = __import__('threading').Event()
    release = __import__('threading').Event()
    job = st.jobs.create("test")

    def work(_job):
        started.set()
        release.wait(2)
        return {"recovered": True}

    st.jobs.submit(job, work)
    assert started.wait(1)
    response = c.get(
        f"/api/jobs/{job.id}/events",
        headers={"Host": "127.0.0.1:5000"},
        buffered=False,
    )
    assert b": ok" in next(response.response)
    response.close()
    assert job.status == "running"

    release.set()
    deadline = __import__('time').monotonic() + 2
    while job.status == "running" and __import__('time').monotonic() < deadline:
        __import__('time').sleep(0.01)
    recovered = c.get(f"/api/jobs/{job.id}", headers={"Host": "127.0.0.1:5000"})

    assert job.status == "done"
    assert recovered.get_json()["result"] == {"recovered": True}


def test_job_cancel_endpoint_marks_job_cancelled(client):
    c, st = client
    token = _boot(c, st)
    started = __import__('threading').Event()
    release = __import__('threading').Event()
    job = st.jobs.create("test")
    st.jobs.submit(job, lambda _job: (started.set(), release.wait(2)))
    assert started.wait(1)

    response = c.post(
        f"/api/jobs/{job.id}/cancel",
        headers=_post_headers(st, token),
        json={},
    )
    assert job.status == "cancelling"
    release.set()
    deadline = __import__('time').monotonic() + 2
    while job.status == "cancelling" and __import__('time').monotonic() < deadline:
        __import__('time').sleep(0.01)

    assert response.status_code == 200
    assert job.status == "cancelled"


@pytest.mark.parametrize(
    ("tool_name", "body"),
    [
        ("ping", {"host": "127.0.0.1; whoami"}),
        ("trace", {"host": "127.0.0.1; whoami"}),
        ("dns", {"name": "example.com; whoami"}),
        ("ports", {"host": "127.0.0.1; whoami", "ports": "80"}),
        ("mtu", {"host": "127.0.0.1; whoami"}),
    ],
)
def test_tool_api_rejects_command_injection_before_runner(client, tool_name, body):
    c, st = client
    token = _boot(c, st)

    class Runner:
        calls = []

        def run(self, args, **_kwargs):
            self.calls.append(args)
            raise AssertionError("invalid host reached the command runner")

    runner = Runner()
    st.runtime.runner = runner
    response = c.post(
        f"/api/tools/{tool_name}",
        headers=_post_headers(st, token),
        json=body,
    )
    job_id = response.get_json()["job_id"]
    import time
    deadline = time.monotonic() + 2
    job = st.jobs.get(job_id)
    while job.status in {"queued", "running", "cancelling"} and time.monotonic() < deadline:
        time.sleep(0.01)

    assert response.status_code == 200
    assert job.status == "error"
    assert runner.calls == []


def test_idle_shutdown_waits_for_cancelling_job(client):
    _client, st = client
    st.last_heartbeat = __import__('time').monotonic() - 121

    assert st.should_shutdown()
    job = st.jobs.create("fix")
    job.status = "cancelling"
    assert not st.should_shutdown()
    job.status = "done"
    assert st.should_shutdown()


def test_fixes_endpoint_returns_catalog_metadata(client):
    c, st = client
    catalog = load_catalog()
    st.runtime.catalog = catalog
    _boot(c, st)

    response = c.get("/api/fixes", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 200
    fixes = response.get_json()["fixes"]
    assert len(fixes) == len(catalog.entries)
    by_id = {fix["id"]: fix for fix in fixes}
    assert set(by_id) == set(catalog.ids)
    assert set(by_id["ADP-01"]) == {
        "id",
        "name",
        "symptom",
        "explanation",
        "admin",
        "risk",
        "reboot",
        "detection_only",
    }
    assert by_id["ADP-01"]["detection_only"] is False


def test_fix_detail_endpoint_returns_procedure(client):
    c, st = client
    catalog = load_catalog()
    st.runtime.catalog = catalog
    _boot(c, st)

    response = c.get("/api/fixes/IP-09", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload["admin"], bool)
    fix = payload["fix"]
    assert fix["id"] == "IP-09"
    assert fix["ladder"], "procedure steps should be present"
    assert fix["ladder"][0]["description"]
    assert fix["ladder"][0]["commands"]
    assert fix["rollback_notes"]
    assert "this_device" in fix["if_unresolved"]

    missing = c.get("/api/fixes/ZZ-99", headers={"Host": "127.0.0.1:5000"})
    assert missing.status_code == 404


def _boot(c, st):
    c.get(f'/__boot__?token={st.security.boot_token}', headers={'Host': '127.0.0.1:5000'})
    token = c.get('/__session__', headers={'Host': '127.0.0.1:5000'}).get_json()['token']
    return token


def _post_headers(st, token, origin="http://127.0.0.1:5000"):
    return {'Host': '127.0.0.1:5000', 'Origin': origin, 'X-NetScope-Token': token, 'Content-Type': 'application/json'}


def test_security_headers_and_origin(client):
    c, st = client
    token = _boot(c, st)
    r = c.get('/api/status', headers={'Host': '127.0.0.1:5000'})
    assert r.status_code == 200
    assert r.headers.get('Content-Security-Policy')
    assert "default-src 'self'" in r.headers.get('Content-Security-Policy', '')
    assert r.headers.get('X-Content-Type-Options') == 'nosniff'
    assert r.headers.get('Referrer-Policy') == 'no-referrer'
    assert 'Access-Control-Allow-Origin' not in r.headers
    # wrong origin
    r = c.post('/api/heartbeat', headers=_post_headers(st, token, origin='http://evil.example'), json={})
    assert r.status_code == 403
    # missing header token
    r = c.post('/api/heartbeat', headers={'Host': '127.0.0.1:5000', 'Origin': 'http://127.0.0.1:5000', 'Content-Type': 'application/json'}, json={})
    assert r.status_code == 403


def test_api_request_and_response_are_logged(client):
    c, st = client

    class Recorder:
        def __init__(self):
            self.events = []

        def event(self, name, **fields):
            self.events.append((name, fields))

    recorder = Recorder()
    st.logger = recorder
    _boot(c, st)
    recorder.events.clear()

    response = c.get("/api/fixes", headers={"Host": "127.0.0.1:5000"})

    assert response.status_code == 200
    assert recorder.events == [
        ("api_request", {"source": "web", "method": "GET", "path": "/api/fixes"}),
        ("api_response", {"source": "web", "method": "GET", "path": "/api/fixes", "status": 200}),
    ]


def test_dashboard_template_uses_shared_shell_and_local_assets(client):
    c, _st = client
    response = c.get("/", headers={"Host": "127.0.0.1:5000"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<aside class="sidebar">' in html
    assert '<main class="main">' in html
    assert '<footer>' in html
    assert 'id="auto-configure-gateway"' in html
    assert 'id="internet-dot"' in html
    assert 'id="gateway-dot"' in html
    assert 'id="internet-status"' in html
    assert 'id="gateway-status"' in html
    assert 'id="run-speed-test"' in html
    assert 'id="speed-test-status"' in html
    assert 'id="speed-test-results"' in html
    assert 'id="speed-test-latency"' in html
    assert 'id="speed-test-download"' in html
    assert 'id="speed-test-upload"' in html
    assert html.index('id="packet-loss-card"') < html.index('id="run-speed-test"') < html.index('id="traffic"')
    assert 'id="layer-status-grid"' in html
    assert html.index('id="view-troubleshoot"') < html.index('id="layer-status-grid"') < html.index('id="troubleshoot"')
    for layer in ("adapter", "services", "ip", "gateway", "lan", "dns", "internet", "stack"):
        assert f'data-layer-status="{layer}"' in html
    assert 'id="run-as-admin"' in html
    assert 'id="repair-library"' in html
    assert 'id="repair-library-list"' in html
    assert 'id="repair-library-detail"' in html
    assert 'data-view="repairs"' in html
    assert "fonts.googleapis.com" not in html
    assert "cdn.jsdelivr.net" not in html

    for path in (
        "/static/css/fonts.css",
        "/static/css/style.css",
        "/static/css/web-overrides.css",
        "/static/js/web-init.js",
        "/static/js/dashboard.js",
        "/static/js/job-stream.js",
        "/static/js/engine-ui.js",
        "/static/vendor/chart.umd.min.js",
        "/static/fonts/Inter-Regular.woff2",
    ):
        assert c.get(path, headers={"Host": "127.0.0.1:5000"}).status_code == 200


class FakeEntry:
    def __init__(self, fix_id='IP-01', risk='low', admin=False):
        self.id = fix_id
        self.name = 'Fix ' + fix_id
        self.risk = risk
        self.admin = admin
        self.reboot = False
        self.rollback = []
        self.rollback_notes = ''
        self.snapshot = []
        self.explanation = 'explain'
        self.detection_only = False


class FakePlan:
    preview_lines = ['cmd1']
    values = {}


class FakeOutcome:
    status = 'resolved'
    def to_dict(self):
        return {'status': 'resolved', 'fix_id': 'IP-01'}


class FakeExecutor:
    def __init__(self):
        self.prepare_calls = 0
        self.run_calls = 0
        self.last_run = None
    def prepare(self, entry, snapshot=None, overrides=None):
        self.prepare_calls += 1
        return FakePlan()
    def run(self, entry, plan=None, assume_yes=True, dry_run=False, confirm=None, isolation=None, progress=None):
        self.run_calls += 1
        self.last_run = {'dry_run': dry_run, 'assume_yes': assume_yes, 'progress': progress}
        if progress:
            progress({'phase': 'step', 'status': 'running', 'index': 1, 'total': 1, 'name': 'Run command'})
        return FakeOutcome()
    def rollback(self, entry, assume_yes=True, confirm=None):
        return FakeOutcome()


def _setup_fix(client, risk='low'):
    c, st = client
    entry = FakeEntry(risk=risk)
    ex = FakeExecutor()
    st.runtime.catalog = types.SimpleNamespace(require=lambda fid: entry if fid == 'IP-01' else (_ for _ in ()).throw(KeyError(fid)))
    st.runtime.executor = lambda: ex
    st.runtime.engine = DummyEngine()
    st.last_snapshot = DummySnap()
    token = _boot(c, st)
    return c, st, token, ex


def test_fix_plan_execute_requires_token(client):
    c, st, token, ex = _setup_fix(client, risk='low')
    r = c.post('/api/fix/plan', headers=_post_headers(st, token), json={'fix_id': 'IP-01'})
    assert r.status_code == 200
    conf = r.get_json()['confirmation_token']
    # execute without token
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={})
    assert r.status_code == 403
    # tampered token
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf + 'x'})
    assert r.status_code == 403
    # valid execute
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf})
    assert r.status_code == 200
    job_id = r.get_json()['job_id']
    import time
    for _ in range(50):
        j = c.get(f'/api/jobs/{job_id}', headers={'Host': '127.0.0.1:5000'}).get_json()
        if j['status'] in ('done','error'):
            break
        time.sleep(0.05)
    assert j['status'] == 'done'
    assert j["result"] == FakeOutcome().to_dict()
    # reused token rejected
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf})
    assert r.status_code == 403


def test_fix_execute_forwards_progress_events(client):
    c, st, token, ex = _setup_fix(client, risk='low')
    r = c.post('/api/fix/plan', headers=_post_headers(st, token), json={'fix_id': 'IP-01'})
    conf = r.get_json()['confirmation_token']

    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf})
    assert r.status_code == 200
    job_id = r.get_json()['job_id']

    import time
    deadline = time.monotonic() + 5
    job = st.jobs.get(job_id)
    while job.status in {'queued', 'running', 'cancelling'} and time.monotonic() < deadline:
        time.sleep(0.02)
        job = st.jobs.get(job_id)

    assert job.status == 'done'
    assert ex.last_run['progress'] is not None
    events = []
    while not job.events.empty():
        events.append(job.events.get_nowait())
    progress = [event for event in events if event.get('type') == 'fix_progress']
    assert progress
    assert progress[0]['phase'] == 'step'
    assert progress[0]['index'] == 1


def test_gateway_configure_runs_auto_fix_job(client, monkeypatch):
    c, st = client
    token = _boot(c, st)
    from fixes.gateway_config import GatewayConfigResult

    def fake_auto_configure(runtime):
        assert runtime is st.runtime
        return GatewayConfigResult(
            "resolved",
            adapter="Ethernet",
            gateway="192.168.1.1",
            message="Gateway configured.",
            outcome={"status": "resolved"},
        )

    monkeypatch.setattr("web.api.auto_configure_gateway", fake_auto_configure)

    response = c.post("/api/gateway/configure", headers=_post_headers(st, token), json={})

    assert response.status_code == 200
    job_id = response.get_json()["job_id"]

    import time
    deadline = time.monotonic() + 5
    job = st.jobs.get(job_id)
    while job.status in {"queued", "running", "cancelling"} and time.monotonic() < deadline:
        time.sleep(0.02)
        job = st.jobs.get(job_id)

    assert job.status == "done"
    assert job.result["status"] == "resolved"
    assert job.result["adapter"] == "Ethernet"
    assert job.result["gateway"] == "192.168.1.1"


def test_elevate_cancelled_keeps_server_running(client, monkeypatch):
    c, st = client
    token = _boot(c, st)
    monkeypatch.setattr("web.api.relaunch_elevated", lambda _argv, **_kwargs: False)

    response = c.post("/api/elevate", headers=_post_headers(st, token), json={})

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "elevate_cancelled"
    assert not st.shutdown_event.is_set()


def test_elevate_requests_restart(client, monkeypatch):
    c, st = client
    token = _boot(c, st)
    calls = []
    st.instance_lock_handle = object()

    def relaunch(argv, *, windowless=False):
        calls.append(("launch", argv, windowless))
        return True

    monkeypatch.setattr("web.api.relaunch_elevated", relaunch)
    monkeypatch.setattr("web.run._remove_lock", lambda _pid: calls.append(("remove", None)))
    monkeypatch.setattr(
        "web.run._release_instance_lock",
        lambda _handle: calls.append(("release", None)),
    )

    response = c.post("/api/elevate", headers=_post_headers(st, token), json={})

    assert response.status_code == 200
    assert calls[0][0] == "remove"
    assert calls[1][0] == "release"
    assert calls[2][0] == "launch"
    assert calls[2][1][0].endswith("netscope.py")
    assert calls[2][2] is True
    assert "--handoff-url" in calls[2][1]
    assert calls[2][1][calls[2][1].index("--handoff-url") + 1] == (
        f"http://127.0.0.1:{st.port}/__elevate_complete__"
    )
    assert "--handoff-token" in calls[2][1]
    assert calls[2][1][calls[2][1].index("--handoff-token") + 1] == (
        st.elevate_handoff["callback_token"]
    )
    assert response.get_json()["handoff"] is True
    assert st.elevate_handoff["active"] is True
    assert st.instance_lock_handle is None
    assert not st.shutdown_event.is_set()


def test_fix_high_risk_requires_second_confirmation(client):
    c, st, token, ex = _setup_fix(client, risk='high')
    r = c.post('/api/fix/plan', headers=_post_headers(st, token), json={'fix_id': 'IP-01'})
    conf = r.get_json()['confirmation_token']
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf})
    assert r.status_code == 403
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf, 'second_confirmation': 'false'})
    assert r.status_code == 403
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf, 'second_confirmation': True})
    assert r.status_code == 200


def test_fix_confirmation_token_expiry(client):
    c, st, token, _executor = _setup_fix(client, risk='low')
    response = c.post('/api/fix/plan', headers=_post_headers(st, token), json={'fix_id': 'IP-01'})
    confirmation_token = response.get_json()['confirmation_token']

    from web import api as web_api
    web_api._FIX_PLANS[confirmation_token]['expires'] = 0
    response = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': confirmation_token})

    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'expired_token'


def test_fix_plan_rejects_injected_parameter_before_command_runner(client, tmp_path):
    c, st = client
    token = _boot(c, st)
    runner = FakeRunner(default=(0, "", ""))
    catalog = load_catalog()
    st.runtime.runner = runner
    st.runtime.catalog = catalog
    st.last_snapshot = DummySnap()
    st.runtime.executor = lambda: FixExecutor(
        runner,
        None,
        st.logger,
        st.runtime.engine,
        catalog,
        backup_dir=tmp_path,
    )

    response = c.post(
        "/api/fix/plan",
        headers=_post_headers(st, token),
        json={
            "fix_id": "ADP-01",
            "params": {"AdapterName": "Ethernet; whoami"},
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "plan_failed"
    assert runner.calls == []


def test_fix_rollback_requires_confirmation_and_runs(client):
    c, st, token, _executor = _setup_fix(client)
    response = c.post('/api/fix/rollback', headers=_post_headers(st, token), json={'fix_id': 'IP-01'})
    assert response.status_code == 403

    response = c.post('/api/fix/rollback', headers=_post_headers(st, token), json={'fix_id': 'IP-01', 'confirmed': True})
    assert response.status_code == 200
    assert response.get_json()['fix_id'] == 'IP-01'


def test_fix_history_returns_only_backup_metadata(client, tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone

    c, st = client
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    (backup_dir / '20260101-IP-01.json').write_text(json.dumps({
        'fix_id': 'IP-01',
        'name': 'Renew address',
        'captured_at': datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        'snapshot': {'private': 'not returned'},
    }), encoding='utf-8')
    monkeypatch.setattr('web.api.config.backup_dir', lambda: backup_dir)
    _boot(c, st)

    response = c.get('/api/fix/history', headers={'Host': '127.0.0.1:5000'})

    assert response.status_code == 200
    assert response.get_json()['history'] == [{
        'fix_id': 'IP-01',
        'name': 'Renew address',
        'captured_at': '2026-01-01T00:00:00+00:00',
        'rollback_available': True,
    }]


@pytest.mark.skipif(shutil.which("ping") is None, reason="ping executable unavailable")
def test_web_utility_command_uses_shared_structured_runner(client):
    c, st = client

    class Recorder:
        def __init__(self):
            self.events = []
            self.commands = []

        def event(self, name, **fields):
            self.events.append((name, fields))

        def action(self, source, name, **fields):
            self.events.append((name, {"source": source, **fields}))

        def command(self, args, **fields):
            self.commands.append((args, fields))

        def error(self, *_args, **_kwargs):
            return None

    recorder = Recorder()
    st.logger = recorder
    st.runtime.logger = recorder
    st.runtime.runner = SubprocessRunner(logger=recorder)
    token = _boot(c, st)
    response = c.post(
        "/api/tools/ping",
        headers=_post_headers(st, token),
        json={"host": "127.0.0.1", "count": 1, "timeout": 0.1},
    )
    job_id = response.get_json()["job_id"]
    import time
    deadline = time.monotonic() + 5
    job = st.jobs.get(job_id)
    while job.status in {"queued", "running", "cancelling"} and time.monotonic() < deadline:
        time.sleep(0.01)

    assert job.status == "done"
    assert set(job.result) == {
        "host",
        "count",
        "returncode",
        "online",
        "latencies_ms",
        "packet_loss_percent",
        "output",
    }
    assert job.result["host"] == "127.0.0.1"
    assert len(recorder.commands) == 1
    assert recorder.commands[0][0][0].lower() == "ping"
    assert {
        "returncode",
        "duration_seconds",
        "stdout",
        "stderr",
        "timeout",
        "timed_out",
    } <= set(recorder.commands[0][1])
    assert any(name == "tool_complete" for name, _fields in recorder.events)


def test_web_speed_test_runs_as_a_tool_job(client):
    c, st = client
    expected = {
        "server": "speed.cloudflare.com",
        "latency_ms": 24.5,
        "latency_samples_ms": [24.5, 23.8, 24.9],
        "download_mbps": 80.0,
        "upload_mbps": 18.0,
        "download_bytes": 10 * 1024 * 1024,
        "upload_bytes": 2 * 1024 * 1024,
    }
    st.runtime.engine.probe = types.SimpleNamespace(speed_test=lambda: expected)
    token = _boot(c, st)
    response = c.post(
        "/api/tools/speedtest",
        headers=_post_headers(st, token),
        json={},
    )

    assert response.status_code == 200
    job = st.jobs.get(response.get_json()["job_id"])
    import time
    deadline = time.monotonic() + 5
    while job.status in {"queued", "running", "cancelling"} and time.monotonic() < deadline:
        time.sleep(0.01)

    assert job.status == "done"
    assert job.result == expected


def test_fix_dry_run_flag_passed(client):
    c, st, token, ex = _setup_fix(client, risk='low')
    r = c.post('/api/fix/plan', headers=_post_headers(st, token), json={'fix_id': 'IP-01'})
    conf = r.get_json()['confirmation_token']
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf, 'dry_run': True})
    assert r.status_code == 200
    job_id = r.get_json()['job_id']
    import time
    for _ in range(50):
        j = c.get(f'/api/jobs/{job_id}', headers={'Host': '127.0.0.1:5000'}).get_json()
        if j['status'] in ('done','error'):
            break
        time.sleep(0.05)
    assert j['status'] == 'done'
    assert ex.last_run and ex.last_run.get('dry_run') is True


def test_fix_execute_dry_run_against_real_executor(client, tmp_path):
    """Regression: the web layer must call FixExecutor.run() with the real
    signature (a stray ``snapshot=`` kwarg used to fail every execution)."""
    c, st = client
    token = _boot(c, st)
    runner = FakeRunner(default=(0, "", ""))
    catalog = load_catalog()
    st.runtime.runner = runner
    st.runtime.catalog = catalog
    st.last_snapshot = DummySnap()
    st.runtime.executor = lambda: FixExecutor(
        runner,
        None,
        st.logger,
        st.runtime.engine,
        catalog,
        backup_dir=tmp_path,
    )

    plan = c.post('/api/fix/plan', headers=_post_headers(st, token), json={'fix_id': 'DNS-01'})
    assert plan.status_code == 200
    conf = plan.get_json()['confirmation_token']
    execute = c.post(
        '/api/fix/execute',
        headers=_post_headers(st, token),
        json={'confirmation_token': conf, 'dry_run': True},
    )
    assert execute.status_code == 200
    job_id = execute.get_json()['job_id']

    import time
    job = st.jobs.get(job_id)
    deadline = time.monotonic() + 5
    while job.status in {'queued', 'running', 'cancelling'} and time.monotonic() < deadline:
        time.sleep(0.01)

    assert job.status == 'done'
    assert job.result['status'] == 'dry_run'
    assert job.result['fix_id'] == 'DNS-01'
    assert runner.calls == []


def test_web_state_falls_back_to_empty_catalog(monkeypatch, tmp_path):
    """If fixes.json cannot be loaded the server must still start and serve
    an empty fix list (the old fallback crashed with a TypeError)."""
    import config
    import web.server as server

    class DummyLogger:
        session_id = "test-session"

        def __getattr__(self, name):
            def _noop(*_args, **_kwargs):
                return None

            return _noop

    monkeypatch.setattr(server, "setup_logging", lambda *args, **kwargs: DummyLogger())
    monkeypatch.setattr(
        server,
        "load_catalog",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("catalog unavailable")),
    )
    monkeypatch.setattr(config, "backup_dir", lambda: tmp_path)

    state = server.WebState(mode="web")
    assert list(state.runtime.catalog.entries) == []
    assert isinstance(state.runtime.monitoring, MonitoringService)

    state.port = 5000
    app = server.create_app(state)
    app.config["TESTING"] = True
    client = app.test_client()
    headers = {"Host": "127.0.0.1:5000"}
    client.get(f"/__boot__?token={state.security.boot_token}", headers=headers)
    response = client.get("/api/fixes", headers=headers)
    assert response.status_code == 200
    assert response.get_json() == {"fixes": []}


def test_template_autoescape_escapes_dynamic_shell_values(client, monkeypatch):
    import config

    c, _st = client
    monkeypatch.setattr(config, "APP_VERSION", "<script>alert(1)</script>")
    response = c.get("/", headers={"Host": "127.0.0.1:5000"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert c.application.jinja_env.autoescape("index.html") is True


def test_reusable_shell_partials_render(client):
    c, _st = client
    html = c.get("/", headers={"Host": "127.0.0.1:5000"}).get_data(as_text=True)
    assert 'id="toast-region"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert '<header class="topbar">' in html
    assert 'id="top-status"' in html
    assert 'id="last-updated"' in html
