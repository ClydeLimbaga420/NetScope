from __future__ import annotations

import sys
import threading
import time

import pytest
from flask import Flask

from core.runner import CommandCancelled, SubprocessRunner, cancellation_scope
from web.jobs import JobManager


def test_subprocess_runner_stops_when_job_is_cancelled():
    cancel_event = threading.Event()
    started = threading.Event()
    errors: list[BaseException] = []

    def run_command():
        started.set()
        try:
            with cancellation_scope(cancel_event):
                SubprocessRunner(default_timeout=10).run(
                    [sys.executable, "-c", "import time; time.sleep(30)"]
                )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_command)
    thread.start()
    assert started.wait(1)
    time.sleep(0.25)
    cancel_event.set()
    thread.join(3)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], CommandCancelled)


def test_job_cancellation_is_not_overwritten_when_worker_finishes():
    manager = JobManager()
    job = manager.create("test")
    started = threading.Event()
    release = threading.Event()

    manager.submit(job, lambda _job: (started.set(), release.wait(2)))
    assert started.wait(1)
    assert manager.cancel(job.id)
    release.set()

    deadline = time.monotonic() + 2
    while job.finished_at is None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert job.status == "cancelled"
    assert job.cancel_event.is_set()


def test_job_cancelled_before_submit_does_not_run_worker():
    manager = JobManager()
    job = manager.create("test")
    called = threading.Event()

    assert manager.cancel(job.id)
    manager.submit(job, lambda _job: called.set())
    time.sleep(0.05)

    assert job.status == "cancelled"
    assert not called.is_set()


def test_job_manager_allows_only_one_active_fix():
    manager = JobManager()
    first = manager.create("fix")
    second = manager.create("rollback")

    assert manager.try_mark_fix_started(first.id)
    assert not manager.try_mark_fix_started(second.id)
    manager.mark_fix_finished(first.id)
    assert manager.try_mark_fix_started(second.id)


def test_sse_stream_delivers_result_and_end_marker():
    manager = JobManager()
    job = manager.create("test")
    manager.submit(job, lambda _job: {"ok": True})

    deadline = time.monotonic() + 2
    while job.status == "running" or job.status == "queued":
        if time.monotonic() >= deadline:
            pytest.fail("job did not finish")
        time.sleep(0.01)

    app = Flask(__name__)
    with app.test_request_context("/"):
        payload = manager.stream(job).get_data(as_text=True)

    assert '"type": "result"' in payload
    assert '"ok": true' in payload
    assert '"type": "end"' in payload