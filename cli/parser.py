from __future__ import annotations

import argparse
import sys

import config
from cli.exit_codes import HELP_TEXT, USAGE
from core.models import LAYER_ORDER


class CliArgumentParser(argparse.ArgumentParser):
    """argparse variant that reports usage errors with NetScope exit code 64."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(USAGE, f"{self.prog}: error: {message}\n")


def _global_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="emit machine-readable JSON on stdout",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS,
        help="disable ANSI colour",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show warnings/failures only",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show diagnostic detail and mirror logs to stderr",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        default=argparse.SUPPRESS,
        help="assume yes for confirmations",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="preview changes without applying them",
    )
    parser.add_argument(
        "--yes-i-understand-risk",
        action="store_true",
        default=argparse.SUPPRESS,
        help="acknowledge a high-risk action (second confirmation)",
    )


def build_parser() -> argparse.ArgumentParser:
    common = CliArgumentParser(add_help=False)
    _global_flags(common)

    parser = CliArgumentParser(
        prog="netscope",
        description=(
            "NetScope - Windows network troubleshooting from the adapter to the internet."
        ),
        epilog=HELP_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"NetScope {config.APP_VERSION}",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    parser._subparsers_action = sub

    diagnose = sub.add_parser(
        "diagnose",
        parents=[common],
        help="run the layered diagnostic pipeline",
        description="Run every diagnostic layer (or the ones selected with --layer).",
    )
    diagnose.add_argument(
        "--layer",
        action="append",
        choices=[layer.value for layer in LAYER_ORDER],
        metavar="LAYER",
        help="run only this layer (repeatable): " + ", ".join(layer.value for layer in LAYER_ORDER),
    )

    fix = sub.add_parser(
        "fix",
        parents=[common],
        help="apply a preset fix by finding or fix id",
        description=(
            "Show a catalog fix, confirm it, apply its ladder and re-run the "
            "verification check. Use --rollback to restore a saved pre-fix snapshot."
        ),
    )
    fix.add_argument("finding", nargs="?", help="finding/check id or fix id (for example GW-02 or IP-01)")
    fix.add_argument("--rollback", action="store_true", default=argparse.SUPPRESS, help="restore the latest saved snapshot for this fix")
    fix.add_argument("--adapter", metavar="NAME", help="override the adapter parameter for this fix")
    fix.add_argument("--target", metavar="VALUE", help="override the target parameter (host, name or path)")
    fix.add_argument("--value", metavar="VALUE", help="override the value parameter when the fix has exactly one")
    fix.add_argument("--param", action="append", default=argparse.SUPPRESS, metavar="NAME=VALUE", help="override a named catalog parameter (repeatable)")

    info = sub.add_parser("info", parents=[common], help="show adapters, addressing, routes, proxy, VPN and Wi-Fi")
    info.add_argument("--adapter", metavar="NAME", help="only show adapters matching NAME")

    ping = sub.add_parser("ping", parents=[common], help="ping a host")
    ping.add_argument("host")
    ping.add_argument("--count", type=int, default=4, metavar="N")
    ping.add_argument("--timeout", type=float, default=1.0, metavar="SECONDS")

    trace = sub.add_parser("trace", parents=[common], help="trace the route to a host")
    trace.add_argument("host")
    trace.add_argument("--max-hops", type=int, default=30, metavar="N")
    trace.add_argument("--timeout", type=float, default=60.0, metavar="SECONDS")

    dns = sub.add_parser("dns", parents=[common], help="resolve a name")
    dns.add_argument("name")
    dns.add_argument("--server", metavar="IP", help="query this DNS server directly")

    sub.add_parser("arp", parents=[common], help="show the ARP table")
    sub.add_parser("routes", parents=[common], help="show the IPv4 route table")

    ports = sub.add_parser("ports", parents=[common], help="check TCP port reachability")
    ports.add_argument("host")
    ports.add_argument("ports", metavar="PORTS", help="port list/range, for example 80,443,8000-8100")

    mtu = sub.add_parser("mtu", parents=[common], help="probe the path MTU to a host")
    mtu.add_argument("host")

    monitor = sub.add_parser(
        "monitor",
        parents=[common],
        help="live network status dashboard (press q to quit)",
        description="Continuously run diagnostics and display a live updating dashboard.",
    )
    monitor.add_argument("--interval", type=float, default=3.0, metavar="SECONDS", help="update interval in seconds (default: 3.0)")

    logs = sub.add_parser("logs", parents=[common], help="view, open or export logs")
    logs.add_argument("--tail", type=int, default=50, metavar="N")
    logs.add_argument("--open", action="store_true", dest="open_log", help="open the log")
    logs.add_argument("--export", metavar="FILE", help="copy logs to FILE")

    report = sub.add_parser("report", parents=[common], help="save a diagnostic report")
    report.add_argument("--output", metavar="FILE", help="write here ('-' for stdout)")
    report.add_argument("--format", choices=("txt", "json"), default="txt", dest="report_format")

    gui = sub.add_parser("gui", parents=[common], help="launch the graphical/web interface")
    gui.add_argument("--no-browser", action="store_true", default=argparse.SUPPRESS, help="start server and print URL only")
    gui.add_argument("--port", type=int, default=argparse.SUPPRESS, metavar="N", help="bind web UI to this local port")

    sub.add_parser("install", parents=[common], help="install NetScope (Phase 5)")
    sub.add_parser("uninstall", parents=[common], help="uninstall NetScope (Phase 5)")

    return parser


def apply_defaults(args: argparse.Namespace) -> argparse.Namespace:
    for name in (
        "json",
        "no_color",
        "quiet",
        "verbose",
        "yes",
        "dry_run",
        "yes_i_understand_risk",
        "no_browser",
    ):
        if not hasattr(args, name):
            setattr(args, name, False)
    for name in ("command", "port"):
        if not hasattr(args, name):
            setattr(args, name, None)
    return args
