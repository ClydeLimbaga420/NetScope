"""Structured JSON-lines logging for every NetScope front end.

Deliberately lives inside ``core`` rather than a top-level ``logging`` package:
a top-level package named ``logging`` would shadow the Python standard library.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

LOG_FILE_NAME = "netscope.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

_STANDARD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
}

_SENSITIVE_HINTS = ("password", "passwd", "secret", "token", "credential", "key=clear")


def _redact(value: Any, key: str = "") -> Any:
    """Recursively redact obvious secrets before they reach disk."""

    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        lowered = key.lower()
        if any(hint in lowered for hint in _SENSITIVE_HINTS):
            return "<redacted>"
        if "key=clear" in value.lower():
            return "<redacted>"
    return value


class JsonLineFormatter(logging.Formatter):
    """Render one JSON object per line with a stable set of fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "session_id": getattr(record, "session_id", "-"),
            "event": getattr(record, "event", record.getMessage()),
        }

        fields = getattr(record, "fields", None)
        if fields:
            payload["fields"] = _redact(fields)

        message = record.getMessage()
        if message and message != payload["event"]:
            payload["message"] = message

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def _build_file_handler(path: Path, max_bytes: int, backup_count: int) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(JsonLineFormatter())
    return handler


class StructuredLogger:
    """Tiny wrapper adding NetScope's event vocabulary to a std logger."""

    def __init__(self, logger: logging.Logger, session_id: str = "-"):
        self.logger = logger
        self.session_id = session_id

    def _log(self, level: int, event: str, *, exc_info: bool = False, **fields: Any) -> None:
        self.logger.log(
            level,
            event,
            extra={"session_id": self.session_id, "event": event, "fields": fields},
            exc_info=exc_info,
        )

    def event(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, **fields)

    def debug(self, event: str, **fields: Any) -> None:
        self._log(logging.DEBUG, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, exc_info: bool = False, **fields: Any) -> None:
        self._log(logging.ERROR, event, exc_info=exc_info, **fields)

    def command(
        self,
        args: list[str],
        *,
        returncode: int | None = None,
        duration_seconds: float | None = None,
        stdout: str = "",
        stderr: str = "",
        timeout: float | None = None,
        timed_out: bool = False,
    ) -> None:
        self.event(
            "command",
            args=args,
            returncode=returncode,
            duration_seconds=round(duration_seconds, 4) if duration_seconds is not None else None,
            stdout=stdout[-4000:],
            stderr=stderr[-4000:],
            timeout=timeout,
            timed_out=timed_out,
        )

    def check(self, result: Any) -> None:
        fields = result.to_dict() if hasattr(result, "to_dict") else result
        self.event("check", **fields)

    def confirmation(self, action: str, accepted: bool, **fields: Any) -> None:
        self.event("confirmation", action=action, accepted=accepted, **fields)

    def fix_applied(self, fix_id: str, **fields: Any) -> None:
        self.event("fix_applied", fix_id=fix_id, **fields)

    def unresolved(self, finding_id: str, **fields: Any) -> None:
        self.event("unresolved", finding_id=finding_id, **fields)

    def action(self, source: str, action: str, **fields: Any) -> None:
        self.event("action", source=source, action=action, **fields)


def setup_logging(
    mode: str,
    session_id: str = "-",
    *,
    log_dir: Path | None = None,
    level: int = logging.INFO,
    max_bytes: int = MAX_BYTES,
    backup_count: int = BACKUP_COUNT,
    console: bool = False,
) -> StructuredLogger:
    """Configure rotating JSON logging and return a structured logger."""

    directory = Path(log_dir) if log_dir is not None else config.log_dir()
    logger = logging.getLogger("netscope")
    logger.setLevel(level)
    logger.propagate = False

    directory.mkdir(parents=True, exist_ok=True)

    # Avoid duplicate handlers when a front end re-initialises logging.
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()

    handler = _build_file_handler(directory / LOG_FILE_NAME, max_bytes, backup_count)
    logger.addHandler(handler)

    if console or os.environ.get("NETSCOPE_LOG_CONSOLE") == "1":
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(JsonLineFormatter())
        logger.addHandler(console_handler)

    structured = StructuredLogger(logger, session_id)
    structured.event("app_start", mode=mode, pid=os.getpid(), version=config.APP_VERSION)
    return structured


def flush_logging() -> None:
    for logger_name in ("netscope",):
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers:
            try:
                handler.flush()
            except Exception:
                pass
