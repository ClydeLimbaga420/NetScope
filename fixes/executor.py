"""Fix planning, confirmation, execution, verification and rollback.

The executor is front-end agnostic. CLI and GUI call the same methods; only
confirmation callbacks differ.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import config
from core.checks.context import configured_dns_servers, text, truthy
from core.models import CheckResult, Status
from core.native import (
    parse_mtu,
    parse_netsh_winhttp_proxy,
    parse_tcp_autotuning,
    parse_wlan_interfaces,
)
from core.runner import CommandResult, CommandRunner
from core.snapshot import Snapshot
from fixes.catalog import (
    Catalog,
    CatalogError,
    CommandSpec,
    FixEntry,
    FixStep,
    format_args,
)
from fixes.if_unresolved import unresolved_section
from powershell.runner import PowerShellLayer, parse_powershell_json
from powershell.validation import (
    ValidationError,
    validate_adapter_name,
    validate_host,
    validate_ip,
    validate_path,
    validate_port,
    validate_profile_name,
)

ConfirmFunc = Callable[[str], bool]
IsolationFunc = Callable[[], bool | None]
AdminFunc = Callable[[], bool]

_VIRTUAL_HINTS = (
    "hyper-v",
    "vethernet",
    "virtual",
    "vmware",
    "virtualbox",
    "wsl",
    "loopback",
    "tap",
    "wireguard",
    "tailscale",
    "zerotier",
    "vpn",
    "docker",
)


class FixError(RuntimeError):
    """Base error for fix planning and execution."""


class PlanError(FixError):
    """Raised when the information needed to run a fix is missing."""


def _default_is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _is_virtual(row: dict[str, Any]) -> bool:
    if truthy(row.get("Virtual")):
        return True
    haystack = f"{text(row.get('Name'))} {text(row.get('InterfaceDescription'))}".lower()
    return any(hint in haystack for hint in _VIRTUAL_HINTS)


def _first_adapter(snapshot: Snapshot) -> dict[str, Any] | None:
    rows = snapshot.section("adapters")
    up = [row for row in rows if text(row.get("Status")).lower() == "up"]
    for row in up:
        if not _is_virtual(row):
            return row
    for row in rows:
        if not _is_virtual(row):
            return row
    return rows[0] if rows else None


def _adapter_name(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return text(row.get("Name")) or text(row.get("InterfaceAlias"))


def _safe_reject(value: str) -> str:
    if not isinstance(value, str):
        raise PlanError("parameter value must be a string")
    if any(ord(char) < 0x20 for char in value) or "\x00" in value:
        raise PlanError("parameter value contains control characters")
    return value


def _validate_value(value: str, validator: str) -> str:
    if not validator or validator == "none":
        return _safe_reject(value)
    try:
        if validator == "host":
            return validate_host(value)
        if validator == "ip":
            return validate_ip(value)
        if validator == "port":
            return str(validate_port(value))
        if validator == "adapter":
            return validate_adapter_name(value)
        if validator == "profile":
            return validate_profile_name(value)
        if validator == "path":
            return validate_path(value)
        if validator == "dns_list":
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return ",".join(validate_ip(part) for part in parts)
    except ValidationError as exc:
        raise PlanError(str(exc)) from exc
    return _safe_reject(value)


@dataclass
class FixPlan:
    entry: FixEntry
    values: dict[str, str]
    snapshot: Snapshot | None
    preview_lines: list[str]


@dataclass
class StepOutcome:
    index: int
    name: str
    description: str
    status: str
    commands: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "commands": self.commands,
            "verification": self.verification,
        }


@dataclass
class FixOutcome:
    fix_id: str
    name: str
    status: str
    message: str
    resolved: bool | None = None
    dry_run: bool = False
    snapshot_file: str | None = None
    steps: list[StepOutcome] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    unresolved: dict[str, Any] | None = None
    error: str | None = None
    risk: str = "low"
    reboot: bool = False
    rollback_available: bool = False

    @property
    def exit_code(self) -> int:
        return {
            "resolved": 0,
            "dry_run": 0,
            "rolled_back": 0,
            "needs_admin": 4,
            "declined": 3,
            "error": 3,
            "detection_only": 2,
            "unresolved": 2,
        }.get(self.status, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fix_id": self.fix_id,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "resolved": self.resolved,
            "exit_code": self.exit_code,
            "dry_run": self.dry_run,
            "snapshot_file": self.snapshot_file,
            "steps": [step.to_dict() for step in self.steps],
            "verification": self.verification,
            "unresolved": self.unresolved,
            "error": self.error,
            "risk": self.risk,
            "reboot": self.reboot,
            "rollback_available": self.rollback_available,
        }


class FixExecutor:
    """Prepare, run, verify and roll back catalog fixes."""

    def __init__(
        self,
        runner: CommandRunner,
        ps: PowerShellLayer | None,
        logger: Any | None,
        engine: Any,
        catalog: Catalog,
        *,
        admin_check: AdminFunc | None = None,
        backup_dir: str | Path | None = None,
        session_id: str = "-",
    ):
        self.runner = runner
        self.ps = ps
        self.logger = logger
        self.engine = engine
        self.catalog = catalog
        self.admin_check = admin_check or _default_is_admin
        self.backup_dir = Path(backup_dir) if backup_dir is not None else config.backup_dir()
        self.session_id = session_id

    def _log(self, method: str, *args: Any, **fields: Any) -> None:
        if self.logger is None:
            return
        handler = getattr(self.logger, method, None)
        if handler is not None:
            handler(*args, **fields)

    def _powershell(self) -> PowerShellLayer:
        if self.ps is None:
            self.ps = PowerShellLayer(self.runner, self.logger)
        return self.ps

    def _snapshot(self) -> Snapshot | None:
        collector = getattr(self.engine, "collect_snapshot", None)
        if collector is None:
            return None
        return collector()

    def prepare(
        self,
        entry: FixEntry,
        *,
        overrides: dict[str, str] | None = None,
        snapshot: Snapshot | None = None,
    ) -> FixPlan:
        overrides = {key: value for key, value in (overrides or {}).items() if value is not None}
        state = snapshot if snapshot is not None else self._snapshot()
        values = self._resolve_values(entry, state, overrides)
        return FixPlan(
            entry=entry,
            values=values,
            snapshot=state,
            preview_lines=self.preview_lines(entry, values),
        )

    def preview_lines(self, entry: FixEntry, values: dict[str, str] | None = None) -> list[str]:
        values = values or {}
        lines = [
            f"{entry.id}  {entry.name}",
            f"Symptom: {entry.symptom}",
            f"Risk: {entry.risk.upper()} | Admin: {'yes' if entry.admin else 'no'} | "
            f"Reboot: {'yes' if entry.reboot else 'no'}",
            f"What it does: {entry.explanation}",
        ]
        if entry.detection_only:
            lines.append("DETECT-ONLY: NetScope will not change any setting for this finding.")
        for index, step in enumerate(entry.ladder, start=1):
            lines.append("")
            lines.append(f"Step {index}: {step.name}")
            if step.description:
                lines.append(f"  {step.description}")
            if not step.commands:
                lines.append("  (no automated command; follow the guidance above)")
            for command in step.commands:
                lines.extend(command.display_lines(values))
        if entry.rollback:
            lines.append("")
            lines.append("Rollback commands:")
            for command in entry.rollback:
                lines.extend(command.display_lines(values))
        elif entry.rollback_notes:
            lines.append("")
            lines.append(f"Rollback: {entry.rollback_notes}")
        return lines

    def _resolve_values(
        self,
        entry: FixEntry,
        snapshot: Snapshot | None,
        overrides: dict[str, str],
    ) -> dict[str, str]:
        values: dict[str, str] = {}
        for param in entry.params:
            if param.name in overrides:
                raw = overrides[param.name]
            else:
                raw = self._resolve_source(param, snapshot, values)
            if raw is None or raw == "":
                if param.required:
                    raise PlanError(
                        f"{entry.id}: value for {param.name} is required "
                        f"({param.description or param.source})"
                    )
                raw = param.default or ""
            values[param.name] = _validate_value(str(raw), param.validator)
        return values

    def _resolve_source(
        self,
        param: Any,
        snapshot: Snapshot | None,
        values: dict[str, str],
    ) -> str | None:
        source = param.source
        adapters = snapshot.section("adapters") if snapshot is not None else []
        adapter = _first_adapter(snapshot) if snapshot is not None else None
        alias = text((adapter or {}).get("InterfaceAlias")) or _adapter_name(adapter)

        if source in {"adapter", "adapter_alias"}:
            return _adapter_name(adapter)
        if source == "adapter_index":
            return text((adapter or {}).get("ifIndex")) or None
        if source == "instance_id":
            for row in snapshot.section("pnp_network_devices") if snapshot is not None else []:
                if text(row.get("Status")).lower() in {"error", "degraded"}:
                    return text(row.get("InstanceId")) or None
            rows = snapshot.section("pnp_network_devices") if snapshot is not None else []
            return text(rows[0].get("InstanceId")) if rows else None
        if source == "gateway":
            return snapshot.gateway if snapshot is not None else None
        if source == "profile":
            rows = snapshot.section("connection_profiles") if snapshot is not None else []
            if not rows:
                return None
            return text(rows[0].get("InterfaceAlias")) or text(rows[0].get("Name")) or None
        if source == "vpn":
            rows = snapshot.section("vpn_connections") if snapshot is not None else []
            return text(rows[0].get("Name")) if rows else None
        if source == "wifi_profile":
            if snapshot is None:
                return None
            wifi = parse_wlan_interfaces(snapshot.native_text("wlan_interfaces"))
            return wifi.get("profile") or wifi.get("ssid") or wifi.get("name") or None
        if source == "original_dns":
            if snapshot is None:
                return None
            return ",".join(configured_dns_servers(snapshot)) or None
        if source == "original_mtu":
            if snapshot is None:
                return "1500"
            mtu_map = parse_mtu(snapshot.native_text("mtu_interfaces"))
            return str(mtu_map.get(alias) or mtu_map.get(_adapter_name(adapter)) or 1500)
        if source == "original_metric":
            if snapshot is None:
                return None
            metrics = []
            for row in snapshot.section("routes"):
                if text(row.get("InterfaceAlias")).lower() != alias.lower():
                    continue
                try:
                    metrics.append(int(row.get("InterfaceMetric") or row.get("RouteMetric")))
                except (TypeError, ValueError):
                    continue
            return str(min(metrics)) if metrics else None
        if source == "original_service_start":
            if snapshot is None:
                return param.default
            service_name = values.get("ServiceName", param.default or "")
            for row in snapshot.section("services"):
                if text(row.get("Name")).lower() == service_name.lower():
                    return text(row.get("StartMode") or row.get("StartType")) or param.default
            return param.default
        if source == "original_autotuning":
            if snapshot is None:
                return param.default
            return (
                parse_tcp_autotuning(snapshot.native_text("tcp_global"))
                or param.default
            )
        if source == "original_winhttp":
            if snapshot is None:
                return None
            return parse_netsh_winhttp_proxy(snapshot.native_text("winhttp_proxy")) or None
        if source == "original_proxy_server":
            if snapshot is None:
                return None
            rows = snapshot.section("system_proxy")
            return text(rows[0].get("ProxyServer")) if rows else None
        if source == "original_autoconfig_url":
            if snapshot is None:
                return None
            rows = snapshot.section("system_proxy")
            return text(rows[0].get("AutoConfigURL")) if rows else None
        if source == "original_disabled_components":
            return "0"
        if source in {"original_ip", "original_prefix", "original_gateway"}:
            if snapshot is None:
                return None
            rows = snapshot.section("ip_addresses")
            row = next(
                (
                    item
                    for item in rows
                    if text(item.get("InterfaceAlias")).lower() == alias.lower()
                    and not text(item.get("IPAddress")).startswith("169.254.")
                ),
                None,
            )
            if source == "original_ip":
                return text((row or {}).get("IPAddress")) or None
            if source == "original_prefix":
                return text((row or {}).get("PrefixLength")) or None
            return snapshot.gateway if snapshot is not None else None
        if source in {"stale_route", "stale_next_hop"}:
            if snapshot is None:
                return None
            prefixes: dict[str, set[str]] = {}
            for row in snapshot.section("routes"):
                prefix = text(row.get("DestinationPrefix"))
                if prefix and prefix != "0.0.0.0/0":
                    prefixes.setdefault(prefix, set()).add(text(row.get("NextHop")))
            duplicate = next(
                (prefix for prefix, hops in prefixes.items() if len(hops) > 1), None
            )
            if duplicate is None:
                return None
            if source == "stale_route":
                return duplicate
            return sorted(prefixes[duplicate])[0]
        if source == "found_mtu":
            return param.default
        if source == "hosts_backup_path":
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            return str(self.backup_dir / f"{stamp}-hosts.bak")
        if source == "wifi_backup_path":
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            return str(self.backup_dir)
        if source == "firewall_backup_path":
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            return str(self.backup_dir / f"{stamp}-firewall.wfw")
        if source in {"target", "value"}:
            return param.default
        raise PlanError(f"{param.name}: unsupported parameter source {source!r}")

    def _run_command(self, command: CommandSpec, values: dict[str, str]) -> CommandResult:
        params = {name: values[name] for name in command.params}
        try:
            if command.kind == "powershell":
                layer = self._powershell()
                result = layer.run_script_text(
                    command.script or "", params, timeout=command.timeout
                )
                if not result.ok and command.native:
                    self._log(
                        "debug",
                        "fix_native_fallback",
                        arguments=format_args(command.native, values),
                    )
                    return self.runner.run(
                        format_args(command.native, values),
                        timeout=command.timeout or config.DEFAULT_COMMAND_TIMEOUT_SECONDS,
                    )
                return result
            return self.runner.run(
                format_args(command.args, values),
                timeout=command.timeout or config.DEFAULT_COMMAND_TIMEOUT_SECONDS,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            return CommandResult(
                args=(command.label,),
                returncode=127,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _take_snapshot(
        self, entry: FixEntry, values: dict[str, str]
    ) -> tuple[str | None, dict[str, Any]]:
        if not entry.snapshot:
            return None, {}
        captured: dict[str, Any] = {}
        for command in entry.snapshot:
            result = self._run_command(command, values)
            parsed: Any = None
            if result.ok:
                try:
                    parsed = parse_powershell_json(result.stdout)
                except Exception:
                    parsed = None
            captured[command.label] = {
                "command": command.to_dict(values),
                "result": result.to_dict(),
                "parsed": parsed,
            }
        payload = {
            "fix_id": entry.id,
            "name": entry.name,
            "session_id": self.session_id,
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "values": values,
            "snapshot": captured,
            "rollback": [command.to_dict(values) for command in entry.rollback],
            "rollback_notes": entry.rollback_notes,
        }
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        safe_fix = re.sub(r"[^A-Za-z0-9_.-]", "_", entry.id)
        path = self.backup_dir / f"{stamp}-{safe_fix}.json"
        try:
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
        except OSError as exc:
            self._log("error", "fix_snapshot_write_failed", fix_id=entry.id, error=str(exc))
            return None, captured
        self._log(
            "event",
            "fix_snapshot",
            fix_id=entry.id,
            path=str(path),
            values=values,
            snapshot=captured,
        )
        return str(path), captured

    def _verify(self, entry: FixEntry) -> dict[str, Any] | None:
        if not entry.verify:
            return None
        diagnose = getattr(self.engine, "diagnose", None)
        if diagnose is None:
            return {"resolved": None, "matches": [], "error": "diagnostic engine unavailable"}
        try:
            report = diagnose(mode="fix-verify")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            self._log("error", "fix_verify_failed", fix_id=entry.id, error=str(exc))
            return {"resolved": None, "matches": [], "error": str(exc)}

        matches: list[CheckResult] = []
        for result in report.results:
            if any(
                result.id == check_id
                or result.id.startswith(f"{check_id}-")
                or check_id in result.fix_ids
                for check_id in entry.verify
            ):
                matches.append(result)

        if not matches:
            return {
                "resolved": None,
                "matches": [],
                "error": "no matching verification check ran",
            }

        resolved = all(
            result.status in (Status.PASS, Status.SKIP) for result in matches
        )
        evidence: dict[str, Any] = {}
        for result in matches:
            evidence[result.id] = result.evidence
        return {
            "resolved": resolved,
            "matches": [result.to_dict() for result in matches],
            "evidence": evidence,
        }

    def _ask_isolation(self, isolation: IsolationFunc | None) -> bool | None:
        if isolation is None:
            return None
        try:
            answer = isolation()
        except (EOFError, KeyboardInterrupt):
            raise
        except Exception:
            return None
        if answer is True or answer is False:
            return answer
        return None

    def run(
        self,
        entry: FixEntry,
        *,
        plan: FixPlan | None = None,
        assume_yes: bool = False,
        dry_run: bool = False,
        risk_ack: bool = False,
        confirm: ConfirmFunc | None = None,
        isolation: IsolationFunc | None = None,
    ) -> FixOutcome:
        plan = plan or self.prepare(entry)
        outcome = FixOutcome(
            fix_id=entry.id,
            name=entry.name,
            status="pending",
            message="",
            risk=entry.risk,
            reboot=entry.reboot,
            rollback_available=bool(entry.rollback),
        )

        if dry_run:
            outcome.status = "dry_run"
            outcome.resolved = None
            outcome.message = "Dry run: no changes were made."
            return outcome

        if entry.detection_only:
            outcome.status = "detection_only"
            outcome.resolved = False
            outcome.message = (
                "This finding is DETECT-ONLY. No setting on this PC can fix it; "
                "see the probable causes and next checks."
            )
            outcome.unresolved = unresolved_section(
                entry, reason=outcome.message, another_device_works=self._ask_isolation(isolation)
            )
            self._log(
                "unresolved",
                entry.id,
                causes=outcome.unresolved,
                reason=outcome.message,
            )
            return outcome

        if entry.admin and not self.admin_check():
            outcome.status = "needs_admin"
            outcome.message = "This fix needs an elevated (administrator) session."
            return outcome

        snapshot_file: str | None = None
        verification: dict[str, Any] | None = None
        evidence: dict[str, Any] = {}
        executed_any = False

        for index, step in enumerate(entry.ladder, start=1):
            step_outcome = StepOutcome(
                index=index,
                name=step.name,
                description=step.description,
                status="skipped",
            )
            outcome.steps.append(step_outcome)

            if not step.commands:
                step_outcome.status = "guidance"
                break

            step_risk = step.risk or entry.risk
            high_risk = step_risk == "high" or step.requires_second_confirmation
            if high_risk and not risk_ack:
                accepted = bool(
                    confirm
                    and confirm(
                        "This step is HIGH RISK. Type 'yes' to acknowledge and continue: "
                    )
                )
                self._log(
                    "confirmation",
                    action=f"risk_high:{entry.id}:{step.name}",
                    accepted=accepted,
                )
                if not accepted:
                    step_outcome.status = "declined"
                    outcome.status = "declined"
                    outcome.message = "High-risk step was not confirmed."
                    return outcome

            if not assume_yes:
                accepted = bool(
                    confirm
                    and confirm(f"Run step {index} '{step.name}'? [y/N] ")
                )
                self._log(
                    "confirmation",
                    action=f"fix_step:{entry.id}:{step.name}",
                    accepted=accepted,
                )
                if not accepted:
                    step_outcome.status = "declined"
                    outcome.status = "declined"
                    outcome.message = "Fix was not confirmed."
                    return outcome
            else:
                self._log(
                    "confirmation",
                    action=f"fix_step:{entry.id}:{step.name}",
                    accepted=True,
                    source="--yes",
                )

            if not executed_any:
                snapshot_file, _ = self._take_snapshot(entry, plan.values)
                outcome.snapshot_file = snapshot_file
                executed_any = True

            step_outcome.status = "ran"
            for command in step.commands:
                result = self._run_command(command, plan.values)
                rendered = command.display_lines(plan.values)
                step_outcome.commands.append(
                    {
                        "label": command.label,
                        "display": rendered,
                        "returncode": result.returncode,
                        "ok": result.ok,
                        "timed_out": result.timed_out,
                        "error": result.error,
                        "stdout": result.stdout[-4000:],
                        "stderr": result.stderr[-4000:],
                    }
                )
                if result.ok:
                    self._log(
                        "fix_applied",
                        entry.id,
                        step=step.name,
                        command=command.label,
                        display=rendered,
                        returncode=result.returncode,
                    )
                else:
                    self._log(
                        "error",
                        "fix_command_failed",
                        fix_id=entry.id,
                        step=step.name,
                        command=command.label,
                        returncode=result.returncode,
                        timed_out=result.timed_out,
                        error=result.error,
                        stderr=result.stderr[-2000:],
                    )
                    step_outcome.status = "failed"
                    break

            verification = self._verify(entry)
            step_outcome.verification = verification
            if verification:
                evidence.update(verification.get("evidence") or {})
            if verification and verification.get("resolved") is True:
                outcome.status = "resolved"
                outcome.resolved = True
                outcome.verification = verification
                outcome.snapshot_file = snapshot_file
                outcome.message = f"Re-check passed: {', '.join(entry.verify)}."
                return outcome

        isolation_answer = self._ask_isolation(isolation)
        outcome.status = "unresolved"
        outcome.resolved = False
        outcome.verification = verification
        outcome.snapshot_file = snapshot_file
        outcome.message = "The fix ladder is exhausted and the re-check still fails."
        outcome.unresolved = unresolved_section(
            entry,
            evidence=evidence,
            another_device_works=isolation_answer,
            reason=outcome.message,
        )
        self._log(
            "unresolved",
            entry.id,
            causes=outcome.unresolved,
            another_device_works=isolation_answer,
            evidence=evidence,
        )
        return outcome

    def _latest_backup(self, fix_id: str) -> Path | None:
        if not self.backup_dir.exists():
            return None
        candidates = sorted(
            self.backup_dir.glob(f"*-{fix_id}.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def rollback(
        self,
        entry: FixEntry,
        *,
        backup_file: str | Path | None = None,
        assume_yes: bool = False,
        risk_ack: bool = False,
        confirm: ConfirmFunc | None = None,
    ) -> FixOutcome:
        outcome = FixOutcome(
            fix_id=entry.id,
            name=entry.name,
            status="pending",
            message="",
            risk=entry.risk,
            reboot=entry.reboot,
        )
        if entry.admin and not self.admin_check():
            outcome.status = "needs_admin"
            outcome.message = "Rollback needs an elevated (administrator) session."
            return outcome

        path = Path(backup_file) if backup_file is not None else self._latest_backup(entry.id)
        if path is None or not path.exists():
            outcome.status = "error"
            outcome.error = (
                "No pre-fix snapshot exists for this fix. Rollback needs the saved state."
            )
            outcome.message = outcome.error
            return outcome

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            outcome.status = "error"
            outcome.error = f"Could not read snapshot: {exc}"
            outcome.message = outcome.error
            return outcome

        if not entry.rollback:
            outcome.status = "error"
            outcome.error = (
                entry.rollback_notes
                or "This fix has no automated rollback; restore the saved state manually."
            )
            outcome.message = outcome.error
            return outcome

        values = {str(key): str(value) for key, value in (payload.get("values") or {}).items()}
        if not assume_yes:
            accepted = bool(
                confirm and confirm(f"Roll back {entry.id} using {path.name}? [y/N] ")
            )
            self._log(
                "confirmation",
                action=f"rollback:{entry.id}",
                accepted=accepted,
                snapshot=str(path),
            )
            if not accepted:
                outcome.status = "declined"
                outcome.message = "Rollback was not confirmed."
                return outcome

        step = StepOutcome(index=1, name="Rollback", description=entry.rollback_notes, status="ran")
        for command in entry.rollback:
            result = self._run_command(command, values)
            step.commands.append(
                {
                    "label": command.label,
                    "display": command.display_lines(values),
                    "returncode": result.returncode,
                    "ok": result.ok,
                    "timed_out": result.timed_out,
                    "error": result.error,
                    "stdout": result.stdout[-4000:],
                    "stderr": result.stderr[-4000:],
                }
            )
            if not result.ok:
                step.status = "failed"
                break
        outcome.steps = [step]
        outcome.snapshot_file = str(path)
        if step.status == "ran":
            outcome.status = "rolled_back"
            outcome.message = f"Rollback commands from {path.name} completed."
        else:
            outcome.status = "error"
            outcome.error = "One or more rollback commands failed."
            outcome.message = outcome.error
        self._log(
            "event",
            "fix_rollback",
            fix_id=entry.id,
            snapshot=str(path),
            status=outcome.status,
            steps=[step.to_dict()],
        )
        return outcome

    def find_fix(self, finding_id: str) -> FixEntry:
        entry = self.catalog.get(finding_id)
        if entry is None:
            raise CatalogError(f"unknown fix or finding id: {finding_id!r}")
        return entry
