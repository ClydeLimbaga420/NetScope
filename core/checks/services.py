"""Network dependency service checks (SVC-01 .. SVC-06)."""

from __future__ import annotations

from typing import Any

from core.checks.context import (
    CheckContext,
    is_running,
    service_map,
    skipped,
    start_mode,
    text,
)
from core.models import CheckResult, Layer, Status

LAYER = Layer.SERVICES

_REQUIRED = {
    "svc-01": ("WlanSvc", "SVC-01", "WLAN AutoConfig", Status.WARN),
    "svc-02": ("Dhcp", "SVC-02", "DHCP Client", Status.FAIL),
    "svc-03": ("Dnscache", "SVC-03", "DNS Client", Status.FAIL),
    "svc-04a": ("NlaSvc", "SVC-04", "Network Location Awareness", Status.WARN),
    "svc-04b": ("netprofm", "SVC-04", "Network List Service", Status.WARN),
    "svc-05": ("BFE", "SVC-05", "Base Filtering Engine", Status.WARN),
    "svc-06a": ("LanmanServer", "SVC-06", "Server", Status.WARN),
    "svc-06b": ("LanmanWorkstation", "SVC-06", "Workstation", Status.WARN),
    "svc-06c": ("FDResPub", "SVC-06", "Function Discovery Resource Publication", Status.WARN),
    "svc-06d": ("SSDPSRV", "SVC-06", "SSDP Discovery", Status.WARN),
    "svc-06e": ("upnphost", "SVC-06", "UPnP Device Host", Status.WARN),
}


def _has_wifi_adapter(snapshot: Any) -> bool:
    for row in snapshot.section("adapters"):
        haystack = f"{text(row.get('Name'))} {text(row.get('InterfaceDescription'))}".lower()
        if any(hint in haystack for hint in ("wi-fi", "wifi", "wireless", "wlan", "802.11")):
            return True
    return False


def _evaluate(name: str, row: dict[str, Any] | None, severity: Status) -> tuple[Status, str | None]:
    if row is None:
        return Status.SKIP, f"{name} was not reported by Windows."
    if not is_running(row):
        state = text(row.get("State") or row.get("Status")) or "unknown"
        mode = start_mode(row) or "unknown"
        return severity, f"{name} is {state} (start mode: {mode})."
    if start_mode(row) == "disabled":
        return severity, f"{name} is running but its start mode is Disabled."
    return Status.PASS, None


def run(ctx: CheckContext) -> list[CheckResult]:
    if not ctx.is_windows:
        return [skipped(LAYER, "SVC-01", "Network services", "Windows-only check")]

    services = service_map(ctx.snapshot)
    if not services:
        return [
            skipped(
                LAYER,
                "SVC-01",
                "Network services",
                "Windows did not return service state (PowerShell may be blocked).",
            )
        ]

    wifi_present = _has_wifi_adapter(ctx.snapshot)
    results: list[CheckResult] = []
    share_problems: list[str] = []

    for key, (name, fix_id, label, severity) in _REQUIRED.items():
        row = services.get(name.lower())
        status, message = _evaluate(name, row, severity)

        if name == "WlanSvc" and not wifi_present and status is not Status.PASS:
            status, message = Status.SKIP, "No Wi-Fi adapter present; WlanSvc is not needed."

        if fix_id == "SVC-06":
            if status not in (Status.PASS, Status.SKIP):
                share_problems.append(message or name)
            continue

        results.append(
            CheckResult(
                id=f"{fix_id}-{name}" if fix_id in {"SVC-04", "SVC-01"} else fix_id,
                layer=LAYER,
                status=status,
                title=f"{label} ({name})",
                message=message or f"{label} is running.",
                cause=(
                    "The service networking depends on is not running."
                    if status not in (Status.PASS, Status.SKIP)
                    else None
                ),
                evidence={
                    "service": name,
                    "state": text((row or {}).get("State") or (row or {}).get("Status")),
                    "start_mode": start_mode(row or {}),
                },
                fix_ids=[fix_id] if status not in (Status.PASS, Status.SKIP) else [],
            )
        )

    results.append(
        CheckResult(
            id="SVC-06",
            layer=LAYER,
            status=Status.WARN if share_problems else Status.PASS,
            title="File and printer sharing stack",
            message=(
                "Sharing/discovery services are not running: " + "; ".join(share_problems)
                if share_problems
                else "Sharing and discovery services are running."
            ),
            cause=(
                "LanmanServer/Workstation or discovery services are stopped, so LAN devices and shares are not visible."
                if share_problems
                else None
            ),
            evidence={"problems": share_problems},
            fix_ids=["SVC-06"] if share_problems else [],
        )
    )

    return results
