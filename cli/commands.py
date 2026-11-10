"""CLI command handlers. Rendering is intentionally separate from checks."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import config
from cli import exit_codes
from cli.admin import admin_guidance, is_admin
from cli.context import CliContext
from cli.render import (
    render_fix_outcome,
    render_info,
    render_report_text,
    render_result,
    summary_lines,
)
from cli.utilities import UtilityRunner
from core.info import build_info
from core.logging_config import LOG_FILE_NAME
from core.models import Status
from fixes.catalog import Catalog, CatalogError, FixEntry, load_catalog
from fixes.executor import FixExecutor, FixOutcome, PlanError
from fixes.if_unresolved import build_unresolved_sections
from powershell.validation import (
    ValidationError,
    validate_path,
)

_FINDING_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,64}$")
_PARAM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SERVICE_SUFFIX_RE = re.compile(r"^[A-Za-z]{2,5}-[0-9]{2}-(.+)$")


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


def _stdin_is_tty(ctx: CliContext) -> bool:
    try:
        return bool(ctx.stdin.isatty())
    except Exception:
        return False


def _confirm(ctx: CliContext, prompt: str) -> bool:
    if not _stdin_is_tty(ctx):
        return False
    print(prompt, end="", file=ctx.stdout, flush=True)
    try:
        answer = ctx.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        raise
    if not answer:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _isolation_func(ctx: CliContext, assume_yes: bool):
    def ask() -> bool | None:
        if assume_yes or not _stdin_is_tty(ctx):
            return None
        print(
            "Does another device on the same network work? [y/n/unknown] ",
            end="",
            file=ctx.stdout,
            flush=True,
        )
        try:
            answer = ctx.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            raise
        text = (answer or "").strip().lower()
        if text.startswith("y"):
            return True
        if text.startswith("n"):
            return False
        return None

    return ask


def _normalize_finding(value: str) -> str:
    text = str(value).strip()
    if not _FINDING_RE.fullmatch(text):
        raise ValueError(f"invalid finding or fix id: {value!r}")
    return text.upper()


def _match_result(report: Any, finding: str):
    if report is None:
        return None
    normalized = finding.upper()
    for result in report.results:
        if result.id.upper() == normalized:
            return result
    for result in report.results:
        if result.id.upper().startswith(f"{normalized}-"):
            return result
    for result in report.results:
        if normalized in {fix_id.upper() for fix_id in result.fix_ids}:
            return result
    return None


def _candidate_results(report: Any) -> list[Any]:
    return [
        result
        for result in report.results
        if result.status.severity >= Status.WARN.severity and result.fix_ids
    ]


def _collect_overrides(
    args: Any,
    entry: FixEntry,
    result: Any,
    raw_finding: str,
) -> dict[str, str]:
    overrides: dict[str, str] = {}

    for item in getattr(args, "param", None) or []:
        if "=" not in item:
            raise ValueError("--param expects NAME=VALUE")
        name, value = item.split("=", 1)
        name = name.strip()
        if not _PARAM_RE.fullmatch(name):
            raise ValueError(f"invalid parameter name: {name!r}")
        if name not in entry.parameter_map:
            raise ValueError(f"{entry.id} has no parameter named {name!r}")
        overrides[name] = value

    def assign(sources: set[str], value: str, flag: str) -> None:
        matches = [param for param in entry.params if param.source in sources]
        if not matches:
            raise ValueError(f"{flag} is not used by {entry.id}")
        if len(matches) > 1:
            raise ValueError(f"{flag} is ambiguous for {entry.id}; use --param NAME=VALUE")
        overrides[matches[0].name] = value

    adapter = getattr(args, "adapter", None)
    if adapter:
        assign({"adapter", "adapter_alias"}, adapter, "--adapter")
    target = getattr(args, "target", None)
    if target:
        assign({"target"}, target, "--target")
    value = getattr(args, "value", None)
    if value:
        assign({"value"}, value, "--value")

    if "ServiceName" in entry.parameter_map and "ServiceName" not in overrides:
        service = None
        if result is not None:
            service = (result.evidence or {}).get("service")
        if not service and result is not None:
            suffix = _SERVICE_SUFFIX_RE.match(result.id or "")
            service = suffix.group(1) if suffix else None
        if not service:
            suffix = _SERVICE_SUFFIX_RE.match(raw_finding or "")
            service = suffix.group(1) if suffix else None
        if service:
            overrides["ServiceName"] = str(service)

    return overrides


def _make_executor(ctx: CliContext, catalog: Catalog, engine: Any) -> FixExecutor:
    return FixExecutor(
        ctx.runner,
        ctx.ps,
        ctx.logger,
        engine,
        catalog,
        admin_check=is_admin,
        session_id=getattr(ctx.logger, "session_id", "-"),
    )


def _finish_fix(
    ctx: CliContext,
    args: Any,
    outcome: FixOutcome,
    entry: FixEntry,
    *,
    preview: list[str] | None = None,
) -> int:
    if outcome.status == "needs_admin":
        ctx.err(admin_guidance(["netscope.py", "fix", entry.id]))
    if args.json:
        payload = outcome.to_dict()
        if preview is not None:
            payload["preview"] = preview
        _json_dump(ctx, payload)
    else:
        if preview:
            for line in preview:
                print(line, file=ctx.stdout)
            print(file=ctx.stdout)
        for line in render_fix_outcome(outcome.to_dict(), verbose=args.verbose):
            print(line, file=ctx.stdout)
    return outcome.exit_code


def cmd_fix(args: Any, ctx: CliContext) -> int:
    raw_finding = getattr(args, "finding", None)
    rollback = bool(getattr(args, "rollback", False))
    try:
        catalog = load_catalog()
    except CatalogError as exc:
        ctx.err(f"error: {exc}")
        return exit_codes.FIX_FAILED

    if rollback and not raw_finding:
        return _failure(ctx, "provide a fix id with --rollback, for example: netscope fix IP-01 --rollback")

    report = None
    snapshot = None
    result = None
    engine = None

    if raw_finding:
        try:
            finding = _normalize_finding(raw_finding)
        except ValueError as exc:
            return _failure(ctx, str(exc))
    else:
        finding = ""

    if not rollback:
        engine = ctx.engine()
        if not args.json and not args.quiet:
            ctx.err("Collecting network state...")
        try:
            snapshot = engine.collect_snapshot()
            report = engine.diagnose(snapshot=snapshot, mode="fix")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            ctx.logger.error("fix_diagnose_failed", exc_info=True, error=str(exc))
            return _failure(
                ctx,
                f"could not collect network state: {exc}",
                exit_codes.FAILURES,
            )

        if not finding:
            candidates = _candidate_results(report)
            if not candidates:
                print("No failing findings with a catalog fix were found.", file=ctx.stdout)
                return exit_codes.OK
            if len(candidates) > 1:
                ctx.err("Multiple findings need attention; choose one:")
                for candidate in candidates:
                    ctx.err(
                        f"  {candidate.id}: {candidate.title} -> "
                        f"{', '.join(candidate.fix_ids)}"
                    )
                return exit_codes.USAGE
            result = candidates[0]
            raw_finding = result.id
            finding = _normalize_finding(result.id)
        else:
            result = _match_result(report, finding)

    entry = catalog.get(finding)
    if entry is None:
        if rollback:
            return _failure(ctx, f"unknown fix id: {finding!r}")
        if result is None:
            return _failure(ctx, f"unknown finding or fix id: {finding!r}")
        fix_ids = [fix_id for fix_id in result.fix_ids if catalog.get(fix_id)]
        if not fix_ids:
            return _failure(
                ctx,
                f"{finding} has no automated fix in the catalog; run 'netscope diagnose' for guidance",
            )
        if len(fix_ids) > 1:
            ctx.err(
                f"Using {fix_ids[0]} for {finding}; other catalog fixes: "
                + ", ".join(fix_ids[1:])
            )
        entry = catalog.require(fix_ids[0])

    if engine is None:
        engine = ctx.engine()
    executor = _make_executor(ctx, catalog, engine)

    if rollback:
        outcome = executor.rollback(
            entry,
            assume_yes=args.yes,
            risk_ack=args.yes_i_understand_risk,
            confirm=lambda prompt: _confirm(ctx, prompt),
        )
        return _finish_fix(ctx, args, outcome, entry)

    try:
        overrides = _collect_overrides(args, entry, result, raw_finding)
        plan = executor.prepare(entry, overrides=overrides, snapshot=snapshot)
    except (PlanError, CatalogError, ValidationError, ValueError) as exc:
        return _failure(ctx, str(exc))

    if not args.json:
        for line in plan.preview_lines:
            print(line, file=ctx.stdout)
        print(file=ctx.stdout)

    if not args.dry_run and not args.yes and not _stdin_is_tty(ctx):
        return _failure(
            ctx,
            "confirmation is required; rerun with --yes for non-interactive use",
        )

    outcome = executor.run(
        entry,
        plan=plan,
        assume_yes=args.yes,
        dry_run=args.dry_run,
        risk_ack=args.yes_i_understand_risk,
        confirm=lambda prompt: _confirm(ctx, prompt),
        isolation=_isolation_func(ctx, args.yes),
    )
    return _finish_fix(
        ctx,
        args,
        outcome,
        entry,
        preview=plan.preview_lines if args.dry_run and args.json else None,
    )


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

    unresolved: list[dict[str, Any]] = []
    try:
        unresolved = build_unresolved_sections(report, load_catalog())
    except CatalogError as exc:
        ctx.logger.warning("fix_catalog_unavailable", error=str(exc))

    payload = {
        "info": info,
        "diagnostic": report.to_dict(include_snapshot=False),
        "unresolved": unresolved,
    }
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
    """Launch the local web UI (replaces tkinter front end)."""
    no_browser = bool(getattr(args, "no_browser", False))
    port = getattr(args, "port", None)
    try:
        port_val = int(port) if port is not None else None
    except (TypeError, ValueError):
        return _failure(ctx, "invalid --port value", exit_codes.USAGE)

    try:
        from web.run import run_web_ui
    except Exception as exc:
        return _failure(ctx, f"web interface unavailable: {exc}", exit_codes.FAILURES)

    # --no-browser: start server and print URL (foreground).
    # Otherwise start server and open browser window (blocks this process).
    # When invoked from an interactive terminal without --no-browser, spawn a
    # detached server process so the prompt returns immediately.
    if (not no_browser) and _stdin_is_tty(ctx) and not ctx.json_mode:
        try:
            import os
            import subprocess

            argv = [sys.executable, "-m", "cli", "gui", "--no-browser"]
            if port_val is not None:
                argv += ["--port", str(port_val)]
            env = os.environ.copy()
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=flags,
            )
            try:
                line = proc.stdout.readline().decode("utf-8", errors="replace").strip() if proc.stdout else ""
            except Exception:
                line = ""
            if line:
                ctx.err(line)
            ctx.err("NetScope web UI launched.")
            return exit_codes.OK
        except Exception:
            # fall through to in-process start
            pass

    try:
        return int(run_web_ui(port=port_val, no_browser=no_browser) or 0)
    except KeyboardInterrupt:
        return exit_codes.INTERRUPTED
    except Exception as exc:
        return _failure(ctx, f"could not start web UI: {exc}", exit_codes.FAILURES)


def cmd_install(args: Any, ctx: CliContext) -> int:
    ctx.err("The installer ships in Phase 5.")
    return exit_codes.FIX_FAILED


def cmd_uninstall(args: Any, ctx: CliContext) -> int:
    ctx.err("The uninstaller ships in Phase 5.")
    return exit_codes.FIX_FAILED


def cmd_monitor(args: Any, ctx: CliContext) -> int:
    """Run live monitoring dashboard."""
    from cli.monitor import run_monitor
    return run_monitor(ctx, interval=getattr(args, "interval", 3.0))


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
    "monitor": cmd_monitor,
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
