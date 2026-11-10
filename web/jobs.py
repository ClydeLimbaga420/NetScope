"""Background job runner and SSE event streams for long-running operations."""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from flask import Response, stream_with_context
from core.runner import cancellation_scope


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued|running|done|error|cancelled
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    events: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "result": self.result,
                "error": self.error,
                "meta": self.meta,
            }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._active_fix_job: str | None = None

    def create(self, kind: str, meta: dict[str, Any] | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, meta=meta or {})
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def can_start_fix(self) -> bool:
        with self._lock:
            if self._active_fix_job is None:
                return True
            j = self._jobs.get(self._active_fix_job)
            return j is None or j.status in {"done", "error", "cancelled"}

    def mark_fix_started(self, job_id: str) -> None:
        with self._lock:
            self._active_fix_job = job_id

    def try_mark_fix_started(self, job_id: str) -> bool:
        with self._lock:
            active = self._jobs.get(self._active_fix_job or "")
            if active and active.status in {"queued", "running"}:
                return False
            self._active_fix_job = job_id
            return True

    def mark_fix_finished(self, job_id: str) -> None:
        with self._lock:
            if self._active_fix_job == job_id:
                self._active_fix_job = None

    def submit(self, job: Job, fn: Callable[[Job], Any]) -> Job:
        def runner() -> None:
            with job.lock:
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.finished_at = time.time()
                    job.events.put({"type": "status", "status": "cancelled"})
                    job.events.put({"type": "end"})
                    return
                job.status = "running"
                job.started_at = time.time()
            job.events.put({"type": "status", "status": "running"})
            try:
                with cancellation_scope(job.cancel_event):
                    result = fn(job)
                with job.lock:
                    if job.cancel_event.is_set():
                        job.status = "cancelled"
                    else:
                        job.status = "done"
                    job.result = result
                    job.finished_at = time.time()
                job.events.put({"type": "status", "status": job.status})
                job.events.put({"type": "result", "result": result})
            except Exception as exc:  # noqa: BLE001
                with job.lock:
                    job.status = "cancelled" if job.cancel_event.is_set() else "error"
                    job.error = str(exc)
                    job.finished_at = time.time()
                job.events.put({"type": "status", "status": job.status})
                job.events.put({"type": "error", "error": str(exc)})
            finally:
                job.events.put({"type": "end"})

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        job.cancel_event.set()
        with job.lock:
            if job.status in {"done", "error", "cancelled"}:
                return job.status == "cancelled"
            if job.status in {"queued", "running"}:
                job.status = "cancelled"
                job.finished_at = time.time()
        job.events.put({"type": "status", "status": "cancelled"})
        return True

    def stream(self, job: Job) -> Response:
        def generate() -> Iterator[str]:
            yield ": ok\n\n"
            while True:
                try:
                    event = job.events.get(timeout=15)
                except queue.Empty:
                    if job.status in {"done", "error", "cancelled"}:
                        break
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") == "end":
                    break
            # ensure end marker
            yield "data: {\"type\":\"end\"}\n\n"

        resp = Response(stream_with_context(generate()), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Connection"] = "keep-alive"
        return resp
