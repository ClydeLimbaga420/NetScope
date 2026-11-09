"""Shared data models for the NetScope diagnostic engine.

The engine returns plain data objects only. CLI and GUI front ends render
these; they must never contain diagnostic logic themselves.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class Status(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"

    @property
    def severity(self) -> int:
        return {
            Status.PASS: 0,
            Status.SKIP: 0,
            Status.WARN: 1,
            Status.FAIL: 2,
            Status.ERROR: 2,
        }[self]


class Layer(str, Enum):
    ADAPTER = "adapter"
    SERVICES = "services"
    IP = "ip"
    GATEWAY = "gateway"
    LAN = "lan"
    DNS = "dns"
    INTERNET = "internet"
    STACK = "stack"


LAYER_ORDER: tuple[Layer, ...] = (
    Layer.ADAPTER,
    Layer.SERVICES,
    Layer.IP,
    Layer.GATEWAY,
    Layer.LAN,
    Layer.DNS,
    Layer.INTERNET,
    Layer.STACK,
)

LAYER_LABELS: dict[Layer, str] = {
    Layer.ADAPTER: "Adapter",
    Layer.SERVICES: "Network services",
    Layer.IP: "IP configuration",
    Layer.GATEWAY: "Gateway",
    Layer.LAN: "Local network",
    Layer.DNS: "DNS",
    Layer.INTERNET: "Internet",
    Layer.STACK: "TCP/IP stack",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class CheckResult:
    """One structured result produced by a single diagnostic check."""

    id: str
    layer: Layer
    status: Status
    title: str
    message: str
    cause: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    fix_ids: list[str] = field(default_factory=list)
    detection_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer.value,
            "status": self.status.value,
            "title": self.title,
            "message": self.message,
            "cause": self.cause,
            "evidence": self.evidence,
            "fix_ids": list(self.fix_ids),
            "detection_only": self.detection_only,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckResult":
        return cls(
            id=data["id"],
            layer=Layer(data["layer"]),
            status=Status(data["status"]),
            title=data.get("title", ""),
            message=data.get("message", ""),
            cause=data.get("cause"),
            evidence=dict(data.get("evidence") or {}),
            fix_ids=list(data.get("fix_ids") or []),
            detection_only=bool(data.get("detection_only", False)),
        )


def combine_status(results: Iterable[CheckResult]) -> Status:
    """Return the most severe status across ``results``."""

    worst = Status.PASS
    for result in results:
        if result.status.severity > worst.severity:
            worst = result.status
    return worst


@dataclass
class DiagnosticReport:
    """The complete outcome of one diagnostic run."""

    session_id: str
    started_at: str
    finished_at: str | None = None
    results: list[CheckResult] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)
    mode: str = "cli"

    @classmethod
    def create(cls, session_id: str | None = None, mode: str = "cli") -> "DiagnosticReport":
        return cls(
            session_id=session_id or new_session_id(),
            started_at=utc_now(),
            mode=mode,
        )

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    def finish(self) -> "DiagnosticReport":
        self.finished_at = utc_now()
        return self

    @property
    def overall_status(self) -> Status:
        return combine_status(self.results)

    @property
    def first_failing_layer(self) -> Layer | None:
        """First layer in pipeline order containing a fail/error/warn result."""

        for layer in LAYER_ORDER:
            layer_results = [r for r in self.results if r.layer is layer]
            if any(r.status.severity >= Status.WARN.severity for r in layer_results):
                return layer
        return None

    @property
    def exit_code(self) -> int:
        status = self.overall_status
        if status in (Status.FAIL, Status.ERROR):
            return 2
        if status is Status.WARN:
            return 1
        return 0

    def to_dict(self) -> dict[str, Any]:
        failing = self.first_failing_layer
        return {
            "app": "NetScope",
            "session_id": self.session_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "mode": self.mode,
            "overall_status": self.overall_status.value,
            "first_failing_layer": failing.value if failing else None,
            "exit_code": self.exit_code,
            "results": [result.to_dict() for result in self.results],
            "snapshot": self.snapshot,
        }
