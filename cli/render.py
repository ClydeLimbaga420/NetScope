"""Human-readable rendering for the CLI."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, TextIO

from cli.colors import CYAN, Colorizer, result_line
from core.models import CheckResult, DiagnosticReport, LAYER_LABELS, Status


def visible_results(report: DiagnosticReport, quiet: bool) -> list[CheckResult]:
    if not quiet:
        return list(report.results)
    return [result for result in report.results if result.status is not Status.PASS]


def render_result(result: CheckResult, color: Colorizer, *, verbose: bool = False) -> list[str]:
    lines = [result_line(result, color)]
    if result.cause and result.status in (Status.WARN, Status.FAIL, Status.ERROR):
        lines.append(color.paint(f"    cause: {result.cause}", CYAN))
    if result.fix_ids and result.status in (Status.WARN, Status.FAIL, Status.ERROR):
        lines.append(f"    fixes: {', '.join(result.fix_ids)}")
    if verbose and result.evidence:
        payload = json.dumps(result.evidence, indent=2, sort_keys=True, default=str)
        lines.extend("    " + line for line in payload.splitlines())
    return lines


def summary_lines(report: DiagnosticReport, color: Colorizer) -> list[str]:
    counts = Counter(result.status for result in report.results)
    parts = [
        f"{counts.get(Status.PASS, 0)} pass",
        f"{counts.get(Status.WARN, 0)} warn",
        f"{counts.get(Status.FAIL, 0)} fail",
        f"{counts.get(Status.SKIP, 0)} skip",
    ]
    if counts.get(Status.ERROR):
        parts.append(f"{counts[Status.ERROR]} error")
    overall = report.overall_status
    lines = [
        "",
        color.paint(f"Overall: {overall.value.upper()}  ({', '.join(parts)})", bold=True),
    ]
    failing = report.first_failing_layer
    if failing is not None:
        lines.append(f"First failing layer: {LAYER_LABELS.get(failing, failing.value)}")
    lines.append(f"Exit code: {report.exit_code}")
    return lines


def write_report(
    report: DiagnosticReport,
    color: Colorizer,
    stream: TextIO,
    *,
    quiet: bool = False,
    verbose: bool = False,
) -> None:
    for result in visible_results(report, quiet):
        for line in render_result(result, color, verbose=verbose):
            print(line, file=stream)
    for line in summary_lines(report, color):
        print(line, file=stream)


def render_unresolved_section(section: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    finding_id = section.get("finding_id")
    finding_title = section.get("finding_title")
    if finding_id:
        label = f"{finding_id}"
        if finding_title:
            label += f" - {finding_title}"
    else:
        label = f"{section.get('fix_id', '')} - {section.get('name', '')}".strip(" -")
    lines.append(f"Still not working? {label}")
    if section.get("reason"):
        lines.append(f"  Reason: {section['reason']}")
    if section.get("wording"):
        lines.append(f"  {section['wording']}")
    answer = section.get("another_device_works")
    if answer is True:
        lines.append("  Another device on the same network works: yes")
    elif answer is False:
        lines.append("  Another device on the same network works: no")
    else:
        lines.append("  Another device on the same network works: unknown/skipped")

    ranked = section.get("ranked") or []
    if ranked:
        lines.append("  Probable or possible causes:")
        for cause in ranked:
            scope = (
                "this device"
                if cause.get("scope") == "this_device"
                else "beyond this device"
            )
            likelihood = cause.get("likelihood") or "possible"
            lines.append(f"    [{likelihood}] {scope}: {cause.get('cause', '')}")
    checks = section.get("next_checks") or []
    if checks:
        lines.append("  Next checks (cheapest first):")
        for index, check in enumerate(checks, start=1):
            lines.append(f"    {index}. {check}")
    evidence = section.get("evidence_to_collect") or []
    if evidence:
        lines.append("  Evidence to collect for a report:")
        for item in evidence:
            lines.append(f"    - {item}")
    return lines


def render_fix_outcome(outcome: dict[str, Any], *, verbose: bool = False) -> list[str]:
    lines: list[str] = []
    for step in outcome.get("steps") or []:
        lines.append(
            f"Step {step.get('index')}: {step.get('name')} [{step.get('status')}]"
        )
        for command in step.get("commands") or []:
            state = "ok" if command.get("ok") else "FAILED"
            detail = f"exit {command.get('returncode')}"
            if command.get("timed_out"):
                detail += ", timed out"
            lines.append(f"  {command.get('label')}: {state} ({detail})")
            if verbose:
                for stream in ("stdout", "stderr"):
                    text = (command.get(stream) or "").rstrip()
                    if text:
                        lines.extend(
                            f"    {stream}: {line}" for line in text.splitlines()
                        )

    verification = outcome.get("verification")
    if verification:
        if verification.get("error"):
            lines.append(f"Verification: {verification['error']}")
        elif verification.get("resolved") is True:
            lines.append("Verification: resolved")
        else:
            lines.append("Verification: still failing")
        for match in verification.get("matches") or []:
            lines.append(
                "  {id}: {status} - {message}".format(
                    id=match.get("id", ""),
                    status=str(match.get("status", "")).upper(),
                    message=match.get("message", ""),
                )
            )

    if outcome.get("snapshot_file"):
        lines.append(f"Pre-fix snapshot: {outcome['snapshot_file']}")
    if outcome.get("rollback_available"):
        lines.append(f"Undo: netscope fix {outcome.get('fix_id')} --rollback")
    if outcome.get("message"):
        lines.append(outcome["message"])
    unresolved = outcome.get("unresolved")
    if unresolved:
        lines.append("")
        lines.extend(render_unresolved_section(unresolved))
    return lines


def render_info(info: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lines.append(f"Host: {info.get('hostname') or 'unknown'}")
    lines.append(f"Captured: {info.get('captured_at') or ''}")
    if "admin" in info:
        lines.append(f"Elevated: {'yes' if info['admin'] else 'no'}")
    if info.get("gateway"):
        lines.append(f"Default gateway: {info['gateway']}")

    adapters = info.get("adapters") or []
    if not adapters:
        lines.append("")
        lines.append("No matching adapters.")
    for adapter in adapters:
        lines.append("")
        title = adapter.get("name") or adapter.get("alias") or "adapter"
        status = adapter.get("status") or "Unknown"
        lines.append(f"[{status}] {title}")
        if adapter.get("description"):
            lines.append(f"  Description: {adapter['description']}")
        if adapter.get("mac"):
            lines.append(f"  MAC: {adapter['mac']}")
        if adapter.get("link_speed"):
            lines.append(f"  Link speed: {adapter['link_speed']}")
        if adapter.get("mtu"):
            lines.append(f"  MTU: {adapter['mtu']}")
        for address in adapter.get("ipv4") or []:
            lines.append(
                "  IPv4: {addr}/{prefix} ({origin}, {state})".format(
                    addr=address.get("address", ""),
                    prefix=address.get("prefix", ""),
                    origin=address.get("origin", ""),
                    state=address.get("state", ""),
                )
            )
        if adapter.get("gateway"):
            lines.append(f"  Gateway: {adapter['gateway']}")
        if adapter.get("dns"):
            lines.append(f"  DNS: {', '.join(adapter['dns'])}")
        if adapter.get("dhcp"):
            lines.append(f"  Address origin: {adapter['dhcp']}")

    wifi = info.get("wifi") or {}
    if wifi:
        lines.append("")
        lines.append("Wi-Fi:")
        for key, label in (
            ("name", "Name"),
            ("description", "Description"),
            ("ssid", "SSID"),
            ("state", "State"),
            ("band", "Band"),
            ("channel", "Channel"),
            ("radio type", "Radio type"),
            ("authentication", "Authentication"),
            ("cipher", "Cipher"),
            ("signal", "Signal"),
            ("rssi", "RSSI"),
            ("profile", "Profile"),
        ):
            if wifi.get(key):
                lines.append(f"  {label}: {wifi[key]}")

    proxy = info.get("proxy") or {}
    if proxy:
        lines.append("")
        lines.append("Proxy:")
        lines.append(f"  WinHTTP: {proxy.get('winhttp') or 'not configured'}")
        lines.append(
            "  User proxy: {enabled}{server}".format(
                enabled="enabled" if proxy.get("user_enabled") else "disabled",
                server=f" ({proxy['user_server']})" if proxy.get("user_server") else "",
            )
        )
        if proxy.get("auto_config_url"):
            lines.append(f"  Auto-config URL: {proxy['auto_config_url']}")

    vpn = info.get("vpn") or []
    lines.append("")
    lines.append(f"VPN connections: {len(vpn)}")
    for row in vpn:
        name = row.get("Name") or row.get("ConnectionName") or "?"
        state = row.get("ConnectionStatus") or row.get("Status") or ""
        lines.append(f"  {name} {state}".rstrip())

    lines.append("")
    lines.append(f"Routes: {len(info.get('routes') or [])}")
    lines.append(f"ARP entries: {len(info.get('arp') or [])}")
    if info.get("dns_servers"):
        lines.append(f"DNS servers: {', '.join(info['dns_servers'])}")
    return lines


def render_report_text(payload: dict[str, Any]) -> str:
    info = payload.get("info") or {}
    diagnostic = payload.get("diagnostic") or {}
    lines = ["NetScope diagnostic report", "=" * 26, ""]
    lines.extend(render_info(info))
    lines.append("")
    lines.append("Checks")
    lines.append("------")
    for raw in diagnostic.get("results") or []:
        result = CheckResult.from_dict(raw)
        lines.append(f"{result.status.value.upper():5} {result.id:10} {result.title} - {result.message}")
        if result.cause:
            lines.append(f"      cause: {result.cause}")
        if result.fix_ids:
            lines.append(f"      fixes: {', '.join(result.fix_ids)}")
    summary = diagnostic.get("summary") or {}
    lines.append("")
    lines.append(
        "Overall: {overall}  (exit code {code})".format(
            overall=str(diagnostic.get("overall_status", "")).upper(),
            code=diagnostic.get("exit_code"),
        )
    )
    if summary:
        lines.append(
            "Counts: " + ", ".join(f"{key}={value}" for key, value in summary.items())
        )
    sections = payload.get("unresolved") or []
    if sections:
        lines.append("")
        lines.append("Unresolved findings - probable causes")
        lines.append("------------------------------------")
        for section in sections:
            lines.extend(render_unresolved_section(section))
            lines.append("")
    lines.append("")
    return "\n".join(lines)
