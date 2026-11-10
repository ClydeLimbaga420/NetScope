"""The single command-runner interface used by every NetScope check and fix.

All system calls funnel through :class:`CommandRunner.run`. Tests mock that one
method. Commands are always argument lists: ``shell=True`` is never used.
"""

from __future__ import annotations

import locale
import os
import subprocess
import time
from contextlib import contextmanager
from contextvars import ContextVar
from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Event
from typing import Any, Iterator, Mapping, Sequence

import config

_CANCEL_EVENT: ContextVar[Event | None] = ContextVar("netscope_cancel_event", default=None)


class CommandCancelled(Exception):
    """Raised when the active background job cancels a running command."""


@contextmanager
def cancellation_scope(event: Event) -> Iterator[None]:
    token = _CANCEL_EVENT.set(event)
    try:
        yield
    finally:
        _CANCEL_EVENT.reset(token)


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None

    @property
    def combined(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "args": list(self.args),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "error": self.error,
        }


class CommandRunner(ABC):
    """Minimal, mockable interface to the operating system."""

    @abstractmethod
    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin_data: str | None = None,
    ) -> CommandResult:
        raise NotImplementedError


def _creation_flags() -> int:
    if os.name == "nt":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _decode(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        for encoding in ("utf-8", locale.getpreferredencoding(False) or "utf-8"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _attach_kill_on_close_job(process: Any) -> tuple[Any, Any] | None:
    if os.name != "nt" or not hasattr(process, "_handle"):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        limits = ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        configured = kernel32.SetInformationJobObject(
            handle,
            9,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        assigned = configured and kernel32.AssignProcessToJobObject(
            handle, wintypes.HANDLE(int(process._handle))
        )
        if not assigned:
            kernel32.CloseHandle(handle)
            return None
        return kernel32, handle
    except Exception:
        return None


def _close_kill_on_close_job(job: tuple[Any, Any] | None) -> None:
    if job is not None:
        try:
            job[0].CloseHandle(job[1])
        except Exception:
            pass


class SubprocessRunner(CommandRunner):
    """Real runner backed by :mod:`subprocess` with strict safety rules."""

    def __init__(self, logger: Any | None = None, default_timeout: float | None = None):
        self.logger = logger
        self.default_timeout = (
            default_timeout
            if default_timeout is not None
            else config.DEFAULT_COMMAND_TIMEOUT_SECONDS
        )

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin_data: str | None = None,
    ) -> CommandResult:
        if isinstance(args, (str, bytes)):
            raise TypeError("args must be a sequence of strings, never a shell string")

        argv = [str(part) for part in args]
        if not argv:
            raise ValueError("args must not be empty")

        effective_timeout = timeout if timeout is not None else self.default_timeout
        started = time.monotonic()
        cancel_event = _CANCEL_EVENT.get()
        if cancel_event is not None and cancel_event.is_set():
            raise CommandCancelled("job cancelled")

        process_env = None
        if env:
            process_env = {**os.environ, **dict(env)}

        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if stdin_data is not None else None,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                env=process_env,
                shell=False,
                creationflags=_creation_flags(),
            )
        except (OSError, ValueError) as exc:
            duration = time.monotonic() - started
            result = CommandResult(
                args=tuple(argv),
                returncode=127,
                duration_seconds=duration,
                error=f"{type(exc).__name__}: {exc}",
            )
            self._log(argv, result, effective_timeout)
            return result

        process_job = _attach_kill_on_close_job(process)
        try:
            if cancel_event is None:
                stdout, stderr = process.communicate(
                    input=stdin_data,
                    timeout=effective_timeout,
                )
            else:
                deadline = (
                    started + effective_timeout if effective_timeout is not None else None
                )
                pending_input = stdin_data
                while True:
                    if cancel_event.is_set():
                        process.kill()
                        _close_kill_on_close_job(process_job)
                        try:
                            process.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                        if self.logger is not None:
                            self.logger.event("command_cancelled", args=argv)
                        raise CommandCancelled("job cancelled")
                    remaining = deadline - time.monotonic() if deadline is not None else 0.1
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(argv, effective_timeout)
                    try:
                        stdout, stderr = process.communicate(
                            input=pending_input,
                            timeout=min(remaining, 0.1),
                        )
                        break
                    except subprocess.TimeoutExpired:
                        pending_input = None
            duration = time.monotonic() - started
            result = CommandResult(
                args=tuple(argv),
                returncode=int(process.returncode),
                stdout=_decode(stdout),
                stderr=_decode(stderr),
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired as exc:
            try:
                process.kill()
            except OSError:
                pass
            _close_kill_on_close_job(process_job)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout, stderr = exc.output or b"", exc.stderr or b""
            duration = time.monotonic() - started
            result = CommandResult(
                args=tuple(argv),
                returncode=124,
                stdout=_decode(stdout),
                stderr=_decode(stderr),
                duration_seconds=duration,
                timed_out=True,
                error=f"timed out after {effective_timeout}s",
            )
        except KeyboardInterrupt:
            try:
                process.kill()
            except OSError:
                pass
            _close_kill_on_close_job(process_job)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            if self.logger is not None:
                self.logger.event("command_interrupted", args=argv)
            raise
        except CommandCancelled:
            raise
        finally:
            _close_kill_on_close_job(process_job)

        self._log(argv, result, effective_timeout)
        return result

    def _log(self, argv: list[str], result: CommandResult, timeout: float | None) -> None:
        if self.logger is not None:
            self.logger.command(
                argv,
                returncode=result.returncode,
                duration_seconds=result.duration_seconds,
                stdout=result.stdout,
                stderr=result.stderr or (result.error or ""),
                timeout=timeout,
                timed_out=result.timed_out,
            )


class FakeRunner(CommandRunner):
    """Deterministic runner used by tests and ``--dry-run`` style previews.

    ``responses`` maps the first argument (or a full ``" ".join(args)`` key) to
    either a :class:`CommandResult`, a ``(returncode, stdout, stderr)`` tuple,
    or an exception instance to raise.
    """

    def __init__(self, responses: Mapping[str, Any] | None = None, default: Any = None):
        self.responses = dict(responses or {})
        self.default = default
        self.calls: list[tuple[str, ...]] = []
        self.logger = None

    def _lookup(self, argv: list[str]) -> Any:
        for key in (" ".join(argv), argv[0]):
            if key in self.responses:
                return self.responses[key]
        return self.default

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin_data: str | None = None,
    ) -> CommandResult:
        argv = [str(part) for part in args]
        self.calls.append(tuple(argv))
        response = self._lookup(argv)

        if isinstance(response, CommandResult):
            return response
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, tuple):
            returncode, stdout, stderr = (list(response) + ["", ""])[:3]
            return CommandResult(
                args=tuple(argv),
                returncode=int(returncode),
                stdout=stdout or "",
                stderr=stderr or "",
            )
        if isinstance(response, str):
            return CommandResult(args=tuple(argv), returncode=0, stdout=response)
        if response is None:
            return CommandResult(args=tuple(argv), returncode=127, error="no fake response")
        raise TypeError(f"unsupported fake response: {response!r}")
