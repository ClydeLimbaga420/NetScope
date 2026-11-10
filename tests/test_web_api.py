from __future__ import annotations

import types

import pytest

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

    def diagnose(self, layers=None, snapshot=None, on_check=None, mode="cli"):
        if on_check:
            on_check(DummyResult("fail", "ip", "IP-01"))
        return DummyReport()


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
        def error(self,*a,**k): pass
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
    rf = c.get('/api/findings', headers={'Host': '127.0.0.1:5000'})
    assert rf.status_code == 200
    assert len(rf.get_json()['findings']) == 1



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
    def run(self, entry, plan=None, assume_yes=True, dry_run=False, confirm=None, isolation=None, snapshot=None):
        self.run_calls += 1
        self.last_run = {'dry_run': dry_run, 'assume_yes': assume_yes}
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
    # reused token rejected
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf})
    assert r.status_code == 403


def test_fix_high_risk_requires_second_confirmation(client):
    c, st, token, ex = _setup_fix(client, risk='high')
    r = c.post('/api/fix/plan', headers=_post_headers(st, token), json={'fix_id': 'IP-01'})
    conf = r.get_json()['confirmation_token']
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf})
    assert r.status_code == 403
    r = c.post('/api/fix/execute', headers=_post_headers(st, token), json={'confirmation_token': conf, 'second_confirmation': True})
    assert r.status_code == 200


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
