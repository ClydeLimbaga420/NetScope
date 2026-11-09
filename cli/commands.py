"""CLI command handlers. Rendering is intentionally separate from checks."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import config
from cli import exit_codes
from cli.admin import admin_guidance, is_admin
from cli.context import CliContext
from cli.render import (
    render_info,
    render_report_text,
    render_result,
    summary_lines,
)
from cli.utilities import UtilityRunner
from core.info import build_info
from core.logging_config import LOG_FILE_NAME
from powershell.validation import (
    ValidationError,
    validate_fix_id,
    validate_path,
)


def _failure(ctx: CliContext, message: str, code: int = exit_codes.USAGE) -> int:
    ctx.err(f"error: {message}")
    return code


def _json_dump(ctx: CliContext, payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str), file=ctx.stdout)


def cmd_diagnose(args: Any, ctx: CliContext) -> int:
    engine = ctx.engine()

    if not args.json and not args.quiet:
        ctx.err("Collecting network state...")

    def on_check(result) -> None:
        if args.json:
            return
        if args.quiet and result.status.value == "pass":
            return
        for line in render_result(result, ctx.color, verbose=args.verbose):
            print(line, file=ctx.stdout)
            ctx.stdout.flush()

    report = engine.diagnose(
        layers=args.layer,
        on_check=on_check,
        mode="cli",
    )

    if args.json:
        _json_dump(ctx, report.to_dict(include_snapshot=False))
    else:
        for line in summary_lines(report, ctx.color):
            print(line, file=ctx.stdout)
    return report.exit_code


def cmd_fix(args: Any, ctx: CliContext) -> int:
    finding = getattr(args, "finding", None)
    if not finding:
        return _failure(
            ctx,
            "provide a finding id, for example: netscope fix IP-01",
        )
    try:
        finding = validate_fix_id(finding.upper())
    except ValidationError as exc:
        return _failure(ctx, str(exc))
    if not is_admin():
        ctx.err(admin_guidance(["netscope.py", "fix", finding]))
    ctx.logger.unresolved(finding, reason="catalog unavailable")
    ctx.err(
        f"fix catalog not available in this build (requested {finding}); "
        "automatic fixes arrive in Phase 3."
    )
    return exit_codes.FIX_FAILED


def cmd_info(args: Any, ctx: CliContext) -> int:
    try:
        snapshot = ctx.engine().collect_snapshot()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        ctx.logger.error("info_failed", exc_info=True, error=str(exc))
        return _failure(ctx, f"could not collect network information: {exc}", exit_codes.FAILURES)

    try:
        info = build_info(snapshot, getattr(args, "adapter", None))
    except LookupError:
        return _failure(ctx, f"no adapter matched {args.adapter!r}")

    info["admin"] = is_admin()
    if args.json:
        _json_dump(ctx, info)
        return exit_codes.OK

    for line in render_info(info):
        print(line, file=ctx.stdout)
    return exit_codes.OK


def _utility_failure(ctx: CliContext, exc: Exception) -> int:
    return _failure(ctx, str(exc))


def cmd_ping(args: Any, ctx: CliContext) -> int:
    try:
        payload = UtilityRunner(ctx).ping(args.host, args.count, args.timeout)
    except (ValidationError, ValueError) as exc:
        return _utility_failure(ctx, exc)

    if args.json:
        _json_dump(ctx, payload)
        return exit_codes.OK if payload["online"] else exit_codes.FAILURES

    if payload["latencies_ms"]:
        print(
            f"Reply from {payload['host']}: "
            + ", ".join(f"{value}ms" for value in payload["latencies_ms"]),
            file=ctx.stdout,
        )
    else:
        print(f"No reply from {payload['host']}", file=ctx.stdout)
    if payload["packet_loss_percent"] is not None:
        print(f"Packet loss: {payload['packet_loss_percent']}%", file=ctx.stdout)
    if args.verbose:
        print(payload["output"], file=ctx.stdout)
    return exit_codes.OK if payload["online"] else exit_codes.FAILURES


def cmd_trace(args: Any, ctx: CliContext) -> int:
    try:
        payload = UtilityRunner(ctx).trace(args.host, args.max_hops, args.timeout)
    except (ValidationError, ValueError) as exc:
        return _utility_failure(ctx, exc)
    if args.json:
        _json_dump(ctx, payload)
    else:
        print(payload["output"], file=ctx.stdout)
    return exit_codes.OK if payload["returncode"] == 0 else exit_codes.FAILURES


def cmd_dns(args: Any, ctx: CliContext) -> int:
    try:
        payload = UtilityRunner(ctx).dns(args.name, args.server)
    except (ValidationError, ValueError) as exc:
        return _utility_failure(ctx, exc)
    if args.json:
        _json_dump(ctx, payload)
        return exit_codes.OK if payload["ok"] else exit_codes.FAILURES

    if payload["ok"]:
        for address in payload["addresses"]:
            print(address, file=ctx.stdout)
        if payload["latency_ms"] is not None:
            print(f"({payload['latency_ms']} ms)", file=ctx.stdout)
        return exit_codes.OK
    print(f"DNS lookup failed: {payload['error'] or 'no answer'}", file=ctx.stdout)
    return exit_codes.FAILURES


def cmd_arp(args: Any, ctx: CliContext) -> int:
    payload = UtilityRunner(ctx).arp()
    if args.json:
        _json_dump(ctx, payload)
        return exit_codes.OK if payload["returncode"] == 0 else exit_codes.FAILURES
    print(f"{'IP address':<16} {'MAC address':<20} Type", file=ctx.stdout)
    for entry in payload["entries"]:
        print(
            f"{entry['ip']:<16} {entry['mac']:<20} {entry['type']}",
            file=ctx.stdout,
        )
    return exit_codes.OK if payload["returncode"] == 0 else exit_codes.FAILURES


def cmd_routes(args: Any, ctx: CliContext) -> int:
    payload = UtilityRunner(ctx).routes()
    if args.json:
        _json_dump(ctx, payload)
        return exit_codes.OK if payload["returncode"] == 0 else exit_codes.FAILURES
    print(payload["output"] or "no route output", file=ctx.stdout)
    return exit_codes.OK if payload["returncode"] == 0 else exit_codes.FAILURES


def cmd_ports(args: Any, ctx: CliContext) -> int:
    try:
        payload = UtilityRunner(ctx).ports(args.host, args.ports)
    except (ValidationError, ValueError) as exc:
        return _utility_failure(ctx, exc)

    if args.json:
        _json_dump(ctx, payload)
        return exit_codes.OK

    results = payload["results"]
    for item in results:
        if not item["open"] and len(results) > 64 and not args.verbose:
            continue
        label = "open" if item["open"] else "closed"
        print(f"{item['port']:>5} {label}", file=ctx.stdout)
    print(
        f"{len(payload['open'])} open, {len(payload['closed'])} closed "
        f"out of {len(results)} checked on {payload['host']}",
        file=ctx.stdout,
    )
    return exit_codes.OK


def cmd_mtu(args: Any, ctx: CliContext) -> int:
    try:
        payload = UtilityRunner(ctx).mtu(args.host)
    except (ValidationError, ValueError) as exc:
        return _utility_failure(ctx, exc)
    if args.json:
        _json_dump(ctx, payload)
        return exit_codes.OK
    if payload["path_mtu"] is None:
        print(f"Could not determine a working MTU to {payload['host']}.", file=ctx.stdout)
        return exit_codes.FAILURES
    print(f"Path MTU to {payload['host']}: {payload['path_mtu']}", file=ctx.stdout)
    return exit_codes.OK


def cmd_logs(args: Any, ctx: CliContext) -> int:
    log_path = config.log_dir() / LOG_FILE_NAME
    lines: list[str] = []
    if log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    tail = max(0, int(getattr(args, "tail", 50) or 0))
    selected = lines[-tail:] if tail else []

    exported: str | None = None
    if getattr(args, "export", None):
        try:
            destination = Path(validate_path(args.export))
        except ValidationError as exc:
            return _failure(ctx, str(exc))
        if not destination.parent.exists():
            return _failure(ctx, f"destination directory does not exist: {destination.parent}")
        try:
            shutil.copy2(log_path, destination)
        except OSError as exc:
            return _failure(ctx, f"could not export logs: {exc}", exit_codes.FAILURES)
        exported = str(destination)

    opened = False
    if getattr(args, "open_log", False):
        opened = _open_path(log_path)

    if args.json:
        _json_dump(
            ctx,
            {
                "log_file": str(log_path),
                "exists": log_path.exists(),
                "tail": [line.rstrip("\n") for line in selected],
                "exported": exported,
                "opened": opened,
            },
        )
        return exit_codes.OK

    print(f"Log file: {log_path}", file=ctx.stdout)
    if not log_path.exists():
        print("No log file has been written yet.", file=ctx.stdout)
        return exit_codes.OK
    for line in selected:
        print(line.rstrip("\n"), file=ctx.stdout)
    if exported:
        print(f"Exported logs to {exported}", file=ctx.stdout)
    if opened:
        print("Opened the log file.", file=ctx.stdout)
    return exit_codes.OK


def _open_path(path: Path) -> bool:
    try:
        if os.name == "nt" and hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        import webbrowser

        return bool(webbrowser.open(path.resolve().as_uri()))
    except Exception:
        return False


def cmd_report(args: Any, ctx: CliContext) -> int:
    engine = ctx.engine()
    try:
        snapshot = engine.collect_snapshot()
        report = engine.diagnose(snapshot=snapshot, mode="report")
        info = build_info(snapshot)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        ctx.logger.error("report_failed", exc_info=True, error=str(exc))
        return _failure(ctx, f"could not build report: {exc}", exit_codes.FAILURES)

    payload = {"info": info, "diagnostic": report.to_dict(include_snapshot=False)}
    if args.report_format == "json":
        content = json.dumps(payload, indent=2, sort_keys=True, default=str)
        extension = "json"
    else:
        content = render_report_text(payload)
        extension = "txt"

    output = getattr(args, "output", None)
    if output == "-":
        print(content, file=ctx.stdout)
        return exit_codes.OK

    if output:
        try:
            destination = Path(validate_path(output))
        except ValidationError as exc:
            return _failure(ctx, str(exc))
    else:
        directory = config.report_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = directory / f"netscope-report-{stamp}.{extension}"

    if not destination.parent.exists():
        return _failure(ctx, f"destination directory does not exist: {destination.parent}")
    try:
        destination.write_text(content, encoding="utf-8")
    except OSError as exc:
        return _failure(ctx, f"could not write report: {exc}", exit_codes.FAILURES)

    if args.json:
        _json_dump(
            ctx,
            {
                "report_file": str(destination),
                "format": args.report_format,
                "exit_code": report.exit_code,
                "overall_status": report.overall_status.value,
            },
        )
    else:
        print(f"Report written to {destination}", file=ctx.stdout)
        print(f"Diagnostic exit code: {report.exit_code}", file=ctx.stdout)
    return exit_codes.OK


def cmd_gui(args: Any, ctx: CliContext) -> int:
    ctx.err("The graphical interface ships in Phase 4; run 'netscope diagnose' for now.")
    return exit_codes.FIX_FAILED


def cmd_install(args: Any, ctx: CliContext) -> int:
    ctx.err("The installer ships in Phase 5.")
    return exit_codes.FIX_FAILED


def cmd_uninstall(args: Any, ctx: CliContext) -> int:
    ctx.err("The uninstaller ships in Phase 5.")
    return exit_codes.FIX_FAILED


HANDLERS: dict[str, Callable[[Any, CliContext], int]] = {
    "diagnose": cmd_diagnose,
    "fix": cmd_fix,
    "info": cmd_info,
    "ping": cmd_ping,
    "trace": cmd_trace,
    "dns": cmd_dns,
    "arp": cmd_arp,
    "routes": cmd_routes,
    "ports": cmd_ports,
    "mtu": cmd_mtu,
    "logs": cmd_logs,
    "report": cmd_report,
    "gui": cmd_gui,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
}


def dispatch(args: Any, ctx: CliContext) -> int:
    command = getattr(args, "command", None)
    handler = HANDLERS.get(command)
    if handler is None:
        ctx.err(f"error: unknown command {command!r}")
        return exit_codes.USAGE

    ctx.logger.action("cli", command, args=_public_args(args))
    try:
        return handler(args, ctx)
    except ValidationError as exc:
        return _failure(ctx, str(exc))
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        ctx.logger.error("command_failed", exc_info=True, command=command, error=str(exc))
        return _failure(ctx, f"{command} failed: {exc}", exit_codes.FAILURES)


def _public_args(args: Any) -> dict[str, Any]:
    return {
        key: value
        for key, value in vars(args).items()
        if key not in {"handler"} and not key.startswith("_")
    }
