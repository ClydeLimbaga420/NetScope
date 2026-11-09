"""PowerShell-first execution layer.

Scripts are static catalog text. User-supplied values are validated and passed
as separate ``-ParamName value`` process arguments; they are never concatenated
into script text. Output is JSON whenever cmdlets support it.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import config
from core.runner import CommandResult, CommandRunner
from powershell import scripts
from powershell.validation import ValidationError, validate_param_name


class PowerShellError(RuntimeError):
    """Raised when PowerShell output cannot be used."""


@dataclass
class BatchResult:
    data: dict[str, Any] = field(default_factory=dict)
    command: CommandResult | None = None
    errors: dict[str, str] = field(default_factory=dict)
    language_mode: str = "Unknown"

    @property
    def available(self) -> bool:
        return self.command is not None and not self.command.error

    @property
    def constrained(self) -> bool:
        return self.language_mode.lower() == "constrainedlanguage"

    def get(self, key: str, default: Any = None) -> Any:
        value = self.data.get(key, default)
        return default if value is None else value


_PS_PREAMBLE = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$ProgressPreference = 'SilentlyContinue'; "
    "$ErrorActionPreference = 'Continue'; "
)


def _flatten(value: Any) -> list[Any]:
    """Normalise ConvertTo-Json output to a list."""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_powershell_json(text: str) -> Any:
    """Parse JSON from PowerShell stdout, tolerating BOMs and stray lines."""

    cleaned = (text or "").lstrip("\ufeff").strip()
    if not cleaned:
        return None
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Some hosts print warnings to stdout. Try each line, last first.
    for line in reversed(cleaned.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    # Multi-line JSON with warnings around it: start at whichever opener
    # appears first so an object inside an array is not mistaken for the root.
    openers = [(cleaned.find("{"), "{", "}"), (cleaned.find("["), "[", "]")]
    openers = [item for item in openers if item[0] != -1]
    for start, opener, closer in sorted(openers):
        end = cleaned.rfind(closer)
        if end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise PowerShellError(f"invalid PowerShell JSON: {cleaned[:400]!r}")


class PowerShellLayer:
    """Thin, testable wrapper around ``powershell.exe``."""

    def __init__(
        self,
        runner: CommandRunner,
        logger: Any | None = None,
        *,
        executable: str = config.POWERSHELL_EXE,
        timeout: float = config.POWERSHELL_TIMEOUT_SECONDS,
        temp_root: str | os.PathLike[str] | None = None,
    ):
        self.runner = runner
        self.logger = logger
        self.executable = executable
        self.timeout = timeout
        self.temp_root = Path(temp_root) if temp_root is not None else None
        self._language_mode: str | None = None

    # -- raw execution -------------------------------------------------

    def _argv_for_file(self, path: Path, params: Mapping[str, Any] | None = None) -> list[str]:
        argv = [
            self.executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path),
        ]
        for name, value in (params or {}).items():
            validate_param_name(name)
            if isinstance(value, bool):
                if value:
                    argv.append(f"-{name}")
                continue
            if not isinstance(value, (str, int)):
                raise ValidationError(f"parameter {name} has an unsupported type")
            text = str(value)
            if any(ord(char) < 0x20 for char in text):
                raise ValidationError(f"parameter {name} contains control characters")
            argv.extend([f"-{name}", text])
        return argv

    def run_script_text(
        self,
        script_text: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> CommandResult:
        """Execute static script text from a temp ``.ps1`` file."""

        root = self.temp_root
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="netscope-ps-", dir=root) as tmp:
            path = Path(tmp) / "netscope_script.ps1"
            path.write_text(script_text, encoding="utf-8-sig")
            argv = self._argv_for_file(path, params)
            return self.runner.run(argv, timeout=timeout or self.timeout)

    def run_expression(
        self,
        expression: str,
        *,
        timeout: float | None = None,
        as_json: bool = True,
    ) -> CommandResult:
        if as_json:
            body = f"{_PS_PREAMBLE}$__ns = ({expression}); "
            body += (
                "if ($null -eq $__ns) { 'null' } else { "
                "$__ns | ConvertTo-Json -Depth 8 -Compress }"
            )
        else:
            body = f"{_PS_PREAMBLE}{expression}"
        return self.run_script_text(body, timeout=timeout)

    def run_native(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CommandResult:
        return self.runner.run(list(args), timeout=timeout or config.PING_COMMAND_TIMEOUT_SECONDS)

    # -- language mode -------------------------------------------------

    def detect_language_mode(self, *, force: bool = False) -> str:
        if self._language_mode is not None and not force:
            return self._language_mode

        result = self.run_expression(scripts.LANGUAGE_MODE, as_json=False)
        mode = (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else ""
        if not mode:
            self._language_mode = "Unavailable" if not result.ok else "Unknown"
        else:
            self._language_mode = mode
        if self.logger is not None:
            self.logger.debug("powershell_language_mode", mode=self._language_mode)
        return self._language_mode

    @property
    def constrained(self) -> bool:
        return self.detect_language_mode().lower() == "constrainedlanguage"

    # -- queries -------------------------------------------------------

    def run_json(self, expression: str, *, timeout: float | None = None) -> Any:
        result = self.run_expression(expression, timeout=timeout)
        if not result.ok:
            raise PowerShellError(
                f"PowerShell failed ({result.returncode}): "
                f"{(result.stderr or result.error or '').strip()[:400]}"
            )
        return parse_powershell_json(result.stdout)

    def run_batch(
        self,
        sections: Sequence[str] | None = None,
        *,
        timeout: float | None = None,
    ) -> BatchResult:
        names = list(sections or scripts.BATCH_QUERIES.keys())
        unknown = [name for name in names if name not in scripts.BATCH_QUERIES]
        if unknown:
            raise ValueError(f"unknown PowerShell batch sections: {unknown}")

        chunks = [
            "$__out = [ordered]@{};",
        ]
        for name in names:
            expression = scripts.BATCH_QUERIES[name]
            chunks.append(
                f"try {{ $__out['{name}'] = @({expression}) }} "
                f"catch {{ $__out['{name}'] = @(); "
                f"$__out['{name}__error'] = \"$($_.Exception.Message)\" }}"
            )
        chunks.append("$__out | ConvertTo-Json -Depth 8 -Compress")

        result = self.run_script_text(_PS_PREAMBLE + " ".join(chunks), timeout=timeout)
        mode = self._language_mode or "Unknown"

        batch = BatchResult(command=result, language_mode=mode)
        if not result.ok:
            return batch

        try:
            data = parse_powershell_json(result.stdout)
        except PowerShellError as exc:
            if self.logger is not None:
                self.logger.warning("powershell_batch_parse_failed", error=str(exc))
            return batch

        if isinstance(data, dict):
            batch.data = data
        for name in names:
            error = batch.data.pop(f"{name}__error", None)
            if error:
                batch.errors[name] = str(error)
        return batch


def as_list(value: Any) -> list[dict[str, Any]]:
    """Return a list of dict rows from parsed PowerShell output."""

    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []
