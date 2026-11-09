"""Interactive ``netscope>`` shell with history, completion, menu fallback, and live monitor."""

from __future__ import annotations

import shlex
from typing import Callable

from cli.context import CliContext
from cli.exit_codes import describe

try:
    from cli.monitor import run_monitor
except ImportError:
    run_monitor = None

BANNER = """NetScope interactive shell
Type 'help' for commands, 'menu' for numbered choices, 'exit' to leave.
"""

MENU: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Run full diagnostics", "diagnose", ()),
    ("Live monitoring dashboard", "monitor", ()),
    ("Show network information", "info", ()),
    ("Ping a host", "ping", ("host",)),
    ("Trace the route to a host", "trace", ("host",)),
    ("Resolve a DNS name", "dns", ("name",)),
    ("Check TCP ports", "ports", ("host", "ports (for example 80,443)")),
    ("Probe the path MTU", "mtu", ("host",)),
    ("Save a diagnostic report", "report", ()),
    ("Show recent logs", "logs", ()),
    ("Exit", "exit", ()),
)

PROMPTS = {
    "host": "Host: ",
    "name": "Name: ",
    "ports (for example 80,443)": "Ports: ",
}


def _setup_readline() -> None:
    try:
        import readline  # type: ignore
    except Exception:
        return
    try:
        import atexit

        import config

        history = config.data_dir() / "cli_history"
        history.parent.mkdir(parents=True, exist_ok=True)
        try:
            readline.read_history_file(history)
        except OSError:
            pass
        readline.set_history_length(1000)
        atexit.register(lambda: _save_history(readline, history))
    except Exception:
        pass


def _save_history(readline, history) -> None:
    try:
        readline.write_history_file(history)
    except Exception:
        pass


def _setup_completion(readline, parser) -> None:
    commands = sorted(getattr(parser, "_subparsers_action").choices) if hasattr(parser, "_subparsers_action") else []
    extra = ["help", "menu", "exit", "quit"]

    def completer(text, state):
        options = [name for name in [*commands, *extra] if name.startswith(text)]
        return options[state] if state < len(options) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")


def run_shell(
    parser,
    ctx: CliContext,
    *,
    input_func: Callable[[str], str] = input,
    max_iterations: int | None = None,
) -> int:
    from cli.commands import dispatch

    print(BANNER, file=ctx.stdout)
    _setup_readline()
    try:
        import readline  # type: ignore

        _setup_completion(readline, parser)
    except Exception:
        pass

    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        try:
            line = input_func("netscope> ")
        except KeyboardInterrupt:
            print(file=ctx.stdout)
            continue
        except EOFError:
            print(file=ctx.stdout)
            break

        line = (line or "").strip()
        if not line:
            continue
        if line.lower() in {"exit", "quit", "q"}:
            break
        if line.lower() in {"help", "?"}:
            parser.print_help(ctx.stdout)
            continue
        if line.lower() == "menu":
            _run_menu(parser, ctx, input_func)
            continue
        if line.lower() == "monitor":
            if run_monitor is None:
                ctx.err("Monitor mode not available.")
            else:
                run_monitor(ctx)
            continue
        if line.lower().startswith("help "):
            topic = line.split(maxsplit=1)[1].strip()
            _print_topic_help(parser, topic, ctx)
            continue

        try:
            argv = shlex.split(line, posix=True)
        except ValueError as exc:
            ctx.err(f"error: {exc}")
            continue
        _execute(parser, argv, ctx, dispatch)

    return 0


def _execute(parser, argv: list[str], ctx: CliContext, dispatch) -> None:
    if not argv:
        return
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return
    from cli.parser import apply_defaults

    apply_defaults(args)
    if getattr(args, "command", None) is None:
        parser.print_help(ctx.stdout)
        return
    try:
        code = dispatch(args, ctx)
    except KeyboardInterrupt:
        ctx.err("")
        ctx.err("interrupted")
        ctx.logger.event("interrupted", phase="shell", command=args.command)
        return
    if code:
        ctx.err(f"(exit code {code}: {describe(code)})")


def _print_topic_help(parser, topic: str, ctx: CliContext) -> None:
    subparsers = getattr(parser, "_subparsers_action", None)
    if subparsers is not None and topic in subparsers.choices:
        subparsers.choices[topic].print_help(ctx.stdout)
        return
    ctx.err(f"error: unknown command {topic!r}")


def _run_menu(parser, ctx: CliContext, input_func: Callable[[str], str]) -> None:
    from cli.commands import dispatch

    while True:
        print(file=ctx.stdout)
        for index, (label, _command, _fields) in enumerate(MENU, start=1):
            print(f"  {index}. {label}", file=ctx.stdout)
        try:
            choice = input_func("Select a number (Enter to cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=ctx.stdout)
            return
        if not choice:
            return
        try:
            index = int(choice)
        except ValueError:
            ctx.err("error: enter a number")
            continue
        if not 1 <= index <= len(MENU):
            ctx.err("error: choice out of range")
            continue

        label, command, fields = MENU[index - 1]
        if command == "exit":
            return

        argv = [command]
        cancelled = False
        for field in fields:
            try:
                value = input_func(PROMPTS.get(field, f"{field}: ")).strip()
            except (EOFError, KeyboardInterrupt):
                print(file=ctx.stdout)
                cancelled = True
                break
            if not value:
                cancelled = True
                break
            argv.append(value)
        if cancelled:
            continue
        _execute(parser, argv, ctx, dispatch)
