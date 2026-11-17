"""Versioned on-disk cache for the last collected network snapshot."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.native import PingResult
from core.runner import CommandResult
from core.snapshot import Snapshot

CACHE_VERSION = 1


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_sections(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and isinstance(rows, list)
        and all(isinstance(row, dict) for row in rows)
        for key, rows in value.items()
    )


def _valid_errors(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(message, str)
        for key, message in value.items()
    )


def _valid_pings(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for host, raw in value.items():
        if not isinstance(host, str) or not isinstance(raw, dict):
            return False
        if raw.get("host") != host or not _is_bool(raw.get("online")):
            return False
        latency = raw.get("latency_ms")
        if latency is not None and not isinstance(latency, (int, float)):
            return False
        returncode = raw.get("returncode")
        if returncode is not None and not _is_int(returncode):
            return False
        error = raw.get("error")
        if error is not None and not isinstance(error, str):
            return False
    return True


def _valid_native(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for name, raw in value.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            return False
        if not isinstance(raw.get("args"), list) or not all(isinstance(a, str) for a in raw["args"]):
            return False
        if not _is_int(raw.get("returncode")):
            return False
        if not isinstance(raw.get("stdout"), str) or not isinstance(raw.get("stderr"), str):
            return False
        duration = raw.get("duration_seconds")
        if not isinstance(duration, (int, float)):
            return False
        if not _is_bool(raw.get("timed_out")):
            return False
        error = raw.get("error")
        if error is not None and not isinstance(error, str):
            return False
    return True


def _valid_payload(payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
        return False
    return (
        isinstance(payload.get("captured_at"), str)
        and _is_bool(payload.get("is_windows"))
        and isinstance(payload.get("language_mode"), str)
        and _is_bool(payload.get("ps_available"))
        and _is_bool(payload.get("constrained"))
        and (payload.get("gateway") is None or isinstance(payload.get("gateway"), str))
        and _valid_errors(payload.get("errors"))
        and _valid_sections(payload.get("sections"))
        and _valid_pings(payload.get("pings"))
        and _valid_native(payload.get("native"))
    )


def load(path: Path) -> Snapshot | None:
    """Return the cached snapshot, or ``None`` if the file is unusable."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not _valid_payload(payload):
        return None

    pings = {
        host: PingResult(
            host=raw["host"],
            online=raw["online"],
            latency_ms=raw["latency_ms"],
            returncode=raw["returncode"],
            error=raw["error"],
        )
        for host, raw in payload["pings"].items()
    }
    native = {
        name: CommandResult(
            args=tuple(raw["args"]),
            returncode=raw["returncode"],
            stdout=raw["stdout"],
            stderr=raw["stderr"],
            duration_seconds=float(raw["duration_seconds"]),
            timed_out=raw["timed_out"],
            error=raw["error"],
        )
        for name, raw in payload["native"].items()
    }

    return Snapshot(
        is_windows=payload["is_windows"],
        language_mode=payload["language_mode"],
        ps_available=payload["ps_available"],
        constrained=payload["constrained"],
        data=payload["sections"],
        errors=payload["errors"],
        native=native,
        pings=pings,
        gateway=payload["gateway"],
        captured_at=payload["captured_at"],
    )


def save(snapshot: Snapshot, path: Path) -> None:
    """Atomically write ``snapshot`` to ``path``."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": CACHE_VERSION,
        "captured_at": snapshot.captured_at,
        "is_windows": snapshot.is_windows,
        "language_mode": snapshot.language_mode,
        "ps_available": snapshot.ps_available,
        "constrained": snapshot.constrained,
        "gateway": snapshot.gateway,
        "errors": dict(snapshot.errors),
        "sections": {key: value for key, value in snapshot.data.items()},
        "pings": {host: result.to_dict() for host, result in snapshot.pings.items()},
        "native": {
            name: (
                result.to_dict()
                if isinstance(result, CommandResult)
                else {
                    "args": [],
                    "returncode": getattr(result, "returncode", 0),
                    "stdout": getattr(result, "stdout", "") or "",
                    "stderr": getattr(result, "stderr", "") or "",
                    "duration_seconds": getattr(result, "duration_seconds", 0.0) or 0.0,
                    "timed_out": bool(getattr(result, "timed_out", False)),
                    "error": getattr(result, "error", None),
                }
            )
            for name, result in snapshot.native.items()
        },
    }

    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)
