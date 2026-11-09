"""Data-driven fix catalog loader and validator.

The catalog is plain JSON. This module turns it into immutable objects and
rejects unsafe or incomplete data before any command can run.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_CATALOG_PATH = Path(__file__).with_name("fixes.json")

RISK_LEVELS = ("low", "medium", "high")
COMMAND_KINDS = ("powershell", "native")
PARAM_SOURCES = {
    "adapter",
    "adapter_alias",
    "adapter_index",
    "instance_id",
    "gateway",
    "profile",
    "vpn",
    "wifi_profile",
    "target",
    "value",
    "found_mtu",
    "original_dns",
    "original_mtu",
    "original_metric",
    "original_service_start",
    "original_autotuning",
    "original_winhttp",
    "original_proxy_server",
    "original_autoconfig_url",
    "original_disabled_components",
    "original_ip",
    "original_prefix",
    "original_gateway",
    "stale_route",
    "stale_next_hop",
    "hosts_backup_path",
    "wifi_backup_path",
    "firewall_backup_path",
}
PARAM_VALIDATORS = {
    "none",
    "host",
    "ip",
    "port",
    "adapter",
    "profile",
    "path",
    "fix_id",
    "dns_list",
}

_VERIFY_IDS = {"IP-08", "LAN-10", "DNS-04", "DNS-05", "NET-06", "NET-08", "NET-11"}
_FIX_ID = re.compile(r"^[A-Z]{2,5}-[0-9]{2}$")
_PARAM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PS_VARIABLE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


class CatalogError(ValueError):
    """Raised when the fix catalog is missing, malformed or unsafe."""


@dataclass(frozen=True)
class CommandSpec:
    kind: str
    label: str
    script: str | None = None
    args: tuple[str, ...] = ()
    native: tuple[str, ...] | None = None
    params: tuple[str, ...] = ()
    timeout: float | None = None
    risk: str | None = None
    requires_second_confirmation: bool = False

    def display_lines(self, values: dict[str, str]) -> list[str]:
        if self.kind == "powershell":
            lines = [f"PowerShell: {self.label}"]
            for line in (self.script or "").splitlines():
                lines.append(f"  {line}")
            if self.params:
                rendered = ", ".join(f"{name}={values.get(name, '')}" for name in self.params)
                lines.append(f"  parameters: {rendered}")
            if self.native:
                lines.append(
                    "  native fallback: "
                    + subprocess.list2cmdline(format_args(self.native, values))
                )
            return lines
        return [subprocess.list2cmdline(format_args(self.args, values))]

    def to_dict(self, values: dict[str, str] | None = None) -> dict[str, Any]:
        payload = {
            "kind": self.kind,
            "label": self.label,
            "script": self.script,
            "args": list(self.args),
            "native": list(self.native) if self.native else None,
            "params": list(self.params),
            "timeout": self.timeout,
            "risk": self.risk,
            "requires_second_confirmation": self.requires_second_confirmation,
        }
        if values is not None:
            payload["display"] = self.display_lines(values)
        return payload


@dataclass(frozen=True)
class FixStep:
    name: str
    description: str
    commands: tuple[CommandSpec, ...]
    risk: str | None = None
    optional: bool = False
    requires_second_confirmation: bool = False


@dataclass(frozen=True)
class Parameter:
    name: str
    source: str
    required: bool = False
    default: str | None = None
    description: str = ""
    validator: str = "none"


@dataclass(frozen=True)
class IfUnresolved:
    this_device: tuple[str, ...]
    beyond_device: tuple[str, ...]
    next_checks: tuple[str, ...]
    evidence_to_collect: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "this_device": list(self.this_device),
            "beyond_device": list(self.beyond_device),
            "next_checks": list(self.next_checks),
            "evidence_to_collect": list(self.evidence_to_collect),
        }


@dataclass(frozen=True)
class FixEntry:
    id: str
    name: str
    symptom: str
    detection: str
    explanation: str
    admin: bool
    risk: str
    reboot: bool
    detection_only: bool
    verify_flag: bool
    verify: tuple[str, ...]
    state_changing: bool
    params: tuple[Parameter, ...]
    snapshot: tuple[CommandSpec, ...]
    rollback: tuple[CommandSpec, ...]
    rollback_notes: str
    ladder: tuple[FixStep, ...]
    if_unresolved: IfUnresolved

    @property
    def parameter_map(self) -> dict[str, Parameter]:
        return {param.name: param for param in self.params}

    @property
    def commands(self) -> list[CommandSpec]:
        return [command for step in self.ladder for command in step.commands]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "symptom": self.symptom,
            "detection": self.detection,
            "explanation": self.explanation,
            "admin": self.admin,
            "risk": self.risk,
            "reboot": self.reboot,
            "detection_only": self.detection_only,
            "verify_flag": self.verify_flag,
            "verify": list(self.verify),
            "state_changing": self.state_changing,
            "params": [
                {
                    "name": param.name,
                    "source": param.source,
                    "required": param.required,
                    "default": param.default,
                    "description": param.description,
                    "validator": param.validator,
                }
                for param in self.params
            ],
            "snapshot": [command.to_dict() for command in self.snapshot],
            "rollback": [command.to_dict() for command in self.rollback],
            "rollback_notes": self.rollback_notes,
            "ladder": [
                {
                    "name": step.name,
                    "description": step.description,
                    "risk": step.risk or self.risk,
                    "optional": step.optional,
                    "requires_second_confirmation": step.requires_second_confirmation,
                    "commands": [command.to_dict() for command in step.commands],
                }
                for step in self.ladder
            ],
            "if_unresolved": self.if_unresolved.to_dict(),
        }


@dataclass(frozen=True)
class Catalog:
    version: int
    entries: tuple[FixEntry, ...]
    source: str = str(DEFAULT_CATALOG_PATH)

    @property
    def by_id(self) -> dict[str, FixEntry]:
        return {entry.id: entry for entry in self.entries}

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(entry.id for entry in self.entries)

    def get(self, fix_id: str) -> FixEntry | None:
        return self.by_id.get(fix_id.strip().upper())

    def require(self, fix_id: str) -> FixEntry:
        entry = self.get(fix_id)
        if entry is None:
            raise CatalogError(f"unknown fix id: {fix_id!r}")
        return entry

    def verify_flagged(self) -> list[str]:
        return [entry.id for entry in self.entries if entry.verify_flag]


def format_args(args: Iterable[str], values: dict[str, str]) -> list[str]:
    """Substitute catalog placeholders in a native argv without a shell."""

    rendered: list[str] = []
    for token in args:
        missing: list[str] = []

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in values:
                missing.append(name)
                return match.group(0)
            return values[name]

        text = _PLACEHOLDER.sub(replace, token)
        if missing:
            raise CatalogError(
                f"native command placeholder(s) have no value: {', '.join(missing)}"
            )
        rendered.append(text)
    return rendered


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise CatalogError(f"{where}: missing required field {key!r}")
    return mapping[key]


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{where}: expected a non-empty string")
    return value.strip()


def _bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogError(f"{where}: expected a boolean")
    return value


def _string_list(value: Any, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CatalogError(f"{where}: expected a list of strings")
    items = tuple(_string(item, where) for item in value)
    if not items and not allow_empty:
        raise CatalogError(f"{where}: must not be empty")
    return items


def _risk(value: Any, where: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if value not in RISK_LEVELS:
        raise CatalogError(f"{where}: risk must be one of {', '.join(RISK_LEVELS)}")
    return value


def _command(raw: Any, where: str, param_names: set[str]) -> CommandSpec:
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: command must be an object")

    kind = raw.get("kind", "powershell")
    if kind not in COMMAND_KINDS:
        raise CatalogError(f"{where}: unsupported command kind {kind!r}")

    label = _string(raw.get("label") or kind, f"{where}.label")
    params = tuple(
        _string(item, f"{where}.params") for item in raw.get("params", [])
    )
    for name in params:
        if name not in param_names:
            raise CatalogError(f"{where}: command references unknown parameter {name!r}")

    timeout = raw.get("timeout")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise CatalogError(f"{where}.timeout: must be a positive number")

    risk = _risk(raw.get("risk"), f"{where}.risk", optional=True)
    second = _bool(
        raw.get("requires_second_confirmation", False),
        f"{where}.requires_second_confirmation",
    )

    native: tuple[str, ...] | None = None
    if raw.get("native") is not None:
        native = _string_list(raw["native"], f"{where}.native")
        for token in native:
            for name in _PLACEHOLDER.findall(token):
                if name not in param_names:
                    raise CatalogError(
                        f"{where}.native: placeholder {name!r} is not a declared parameter"
                    )

    if kind == "powershell":
        script = _string(raw.get("script"), f"{where}.script")
        for name in _PS_VARIABLE.findall(script):
            if name in param_names and name not in params:
                raise CatalogError(
                    f"{where}.script: uses ${name} but does not declare it in params"
                )
        return CommandSpec(
            kind=kind,
            label=label,
            script=script,
            native=native,
            params=params,
            timeout=float(timeout) if timeout is not None else None,
            risk=risk,
            requires_second_confirmation=second,
        )

    args = _string_list(raw.get("args"), f"{where}.args")
    for token in args:
        for name in _PLACEHOLDER.findall(token):
            if name not in param_names:
                raise CatalogError(
                    f"{where}.args: placeholder {name!r} is not a declared parameter"
                )
    return CommandSpec(
        kind=kind,
        label=label,
        args=args,
        params=params,
        timeout=float(timeout) if timeout is not None else None,
        risk=risk,
        requires_second_confirmation=second,
    )


def _step(raw: Any, where: str, param_names: set[str]) -> FixStep:
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: step must be an object")
    commands_raw = raw.get("commands", [])
    if not isinstance(commands_raw, list):
        raise CatalogError(f"{where}.commands: expected a list")
    commands = tuple(
        _command(item, f"{where}.commands[{index}]", param_names)
        for index, item in enumerate(commands_raw)
    )
    return FixStep(
        name=_string(raw.get("name"), f"{where}.name"),
        description=_string(raw.get("description", ""), f"{where}.description"),
        commands=commands,
        risk=_risk(raw.get("risk"), f"{where}.risk", optional=True),
        optional=_bool(raw.get("optional", False), f"{where}.optional"),
        requires_second_confirmation=_bool(
            raw.get("requires_second_confirmation", False),
            f"{where}.requires_second_confirmation",
        ),
    )


def _if_unresolved(raw: Any, where: str) -> IfUnresolved:
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: if_unresolved must be an object")
    return IfUnresolved(
        this_device=_string_list(
            _require(raw, "this_device", where), f"{where}.this_device"
        ),
        beyond_device=_string_list(
            _require(raw, "beyond_device", where), f"{where}.beyond_device"
        ),
        next_checks=_string_list(_require(raw, "next_checks", where), f"{where}.next_checks"),
        evidence_to_collect=_string_list(
            _require(raw, "evidence_to_collect", where), f"{where}.evidence_to_collect"
        ),
    )


def _parameter(raw: Any, where: str) -> Parameter:
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: parameter must be an object")
    name = _string(raw.get("name"), f"{where}.name")
    if not _PARAM_NAME.match(name):
        raise CatalogError(f"{where}.name: invalid parameter name {name!r}")
    source = _string(raw.get("source"), f"{where}.source")
    if source not in PARAM_SOURCES:
        raise CatalogError(f"{where}.source: unknown source {source!r}")
    validator = raw.get("validator", "none")
    if validator not in PARAM_VALIDATORS:
        raise CatalogError(f"{where}.validator: unknown validator {validator!r}")
    default = raw.get("default")
    if default is not None and not isinstance(default, str):
        raise CatalogError(f"{where}.default: expected a string")
    return Parameter(
        name=name,
        source=source,
        required=_bool(raw.get("required", False), f"{where}.required"),
        default=default,
        description=str(raw.get("description", "")),
        validator=validator,
    )


def _entry(raw: Any, index: int) -> FixEntry:
    if not isinstance(raw, dict):
        raise CatalogError(f"entries[{index}]: expected an object")
    fix_id = _string(raw.get("id"), f"entries[{index}].id").upper()
    if not _FIX_ID.match(fix_id):
        raise CatalogError(f"{fix_id}: invalid fix id")
    where = fix_id

    params_raw = raw.get("params", [])
    if not isinstance(params_raw, list):
        raise CatalogError(f"{where}.params: expected a list")
    params = tuple(
        _parameter(item, f"{where}.params[{position}]")
        for position, item in enumerate(params_raw)
    )
    if len({param.name for param in params}) != len(params):
        raise CatalogError(f"{where}.params: duplicate parameter name")
    param_names = {param.name for param in params}

    snapshot_raw = raw.get("snapshot", [])
    rollback_raw = raw.get("rollback", [])
    ladder_raw = raw.get("ladder", [])
    for field_name, value in (
        ("snapshot", snapshot_raw),
        ("rollback", rollback_raw),
        ("ladder", ladder_raw),
    ):
        if not isinstance(value, list):
            raise CatalogError(f"{where}.{field_name}: expected a list")

    snapshot = tuple(
        _command(item, f"{where}.snapshot[{position}]", param_names)
        for position, item in enumerate(snapshot_raw)
    )
    rollback = tuple(
        _command(item, f"{where}.rollback[{position}]", param_names)
        for position, item in enumerate(rollback_raw)
    )
    ladder = tuple(
        _step(item, f"{where}.ladder[{position}]", param_names)
        for position, item in enumerate(ladder_raw)
    )

    admin = _bool(_require(raw, "admin", where), f"{where}.admin")
    risk = _risk(_require(raw, "risk", where), f"{where}.risk")
    reboot = _bool(_require(raw, "reboot", where), f"{where}.reboot")
    detection_only = _bool(
        _require(raw, "detection_only", where), f"{where}.detection_only"
    )
    verify_flag = _bool(raw.get("verify_flag", False), f"{where}.verify_flag")
    verify = _string_list(_require(raw, "verify", where), f"{where}.verify")
    state_changing = _bool(
        raw.get("state_changing", not detection_only), f"{where}.state_changing"
    )
    rollback_notes = str(raw.get("rollback_notes", "")).strip()

    if detection_only:
        if ladder or any(step.commands for step in ladder):
            raise CatalogError(f"{where}: DETECT-ONLY entries must not contain commands")
        if state_changing:
            raise CatalogError(f"{where}: DETECT-ONLY entries cannot change state")
    else:
        if not ladder:
            raise CatalogError(f"{where}: a runnable fix needs a fix ladder")
        if not any(step.commands for step in ladder):
            raise CatalogError(f"{where}: the fix ladder has no commands")

    if state_changing:
        if not snapshot:
            raise CatalogError(f"{where}: state-changing fixes need a pre-fix snapshot")
        if not rollback and not rollback_notes:
            raise CatalogError(
                f"{where}: state-changing fixes need rollback commands or rollback_notes"
            )

    if risk == "high" and not detection_only:
        flagged = any(step.requires_second_confirmation for step in ladder) or any(
            command.requires_second_confirmation for command in snapshot + rollback
        )
        if not flagged:
            raise CatalogError(
                f"{where}: high-risk fixes need a second-confirmation step"
            )

    return FixEntry(
        id=fix_id,
        name=_string(_require(raw, "name", where), f"{where}.name"),
        symptom=_string(_require(raw, "symptom", where), f"{where}.symptom"),
        detection=_string(_require(raw, "detection", where), f"{where}.detection"),
        explanation=_string(
            _require(raw, "explanation", where), f"{where}.explanation"
        ),
        admin=admin,
        risk=risk,
        reboot=reboot,
        detection_only=detection_only,
        verify_flag=verify_flag,
        verify=verify,
        state_changing=state_changing,
        params=params,
        snapshot=snapshot,
        rollback=rollback,
        rollback_notes=rollback_notes,
        ladder=ladder,
        if_unresolved=_if_unresolved(
            _require(raw, "if_unresolved", where), f"{where}.if_unresolved"
        ),
    )


def parse_catalog(raw: Any, *, source: str = "<memory>") -> Catalog:
    """Validate a decoded catalog document and return immutable objects."""

    if not isinstance(raw, dict):
        raise CatalogError("catalog root must be an object")
    version = raw.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise CatalogError("catalog version must be a positive integer")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise CatalogError("catalog entries must be a non-empty list")

    entries = tuple(_entry(item, index) for index, item in enumerate(entries_raw))
    ids = [entry.id for entry in entries]
    duplicates = sorted({fix_id for fix_id in ids if ids.count(fix_id) > 1})
    if duplicates:
        raise CatalogError(f"duplicate fix ids: {', '.join(duplicates)}")

    flagged = {entry.id for entry in entries if entry.verify_flag}
    missing_verify = sorted(_VERIFY_IDS - flagged)
    if missing_verify:
        raise CatalogError(
            "entries must be flagged [VERIFY]: " + ", ".join(missing_verify)
        )

    return Catalog(version=version, entries=entries, source=source)


def load_catalog(path: str | Path | None = None) -> Catalog:
    """Load and validate ``fixes.json`` (or an explicit path)."""

    catalog_path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    try:
        text = catalog_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"could not read fix catalog {catalog_path}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"fix catalog is not valid JSON: {exc}") from exc
    return parse_catalog(raw, source=str(catalog_path))
