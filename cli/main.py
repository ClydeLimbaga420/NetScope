"""CLI entry point. Keeps terminal concerns out of the diagnostic engine."""

from __future__ import annotations

import sys
from typing import Sequence

from cli import exit_codes
from cli.admin import is_admin
from cli.context import create_context
from cli.parser import apply_defaults, build_parser
from cli.shell import run_shell
from core.logging_config import flush_logging
from core.models import new_session_id
from gui.launch import GUI_INTERNAL, detach_console, launch_detached_gui, owns_console


def main(argv: Sequence[str] | None = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    if args_in and args_in[0] == GUI_INTERNAL:
        return _run_gui_process()
    parser = build_parser()
    try:
        args = parser.parse_args(args_in)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    apply_defaults(args)

    if getattr(args, "command", None) is None:
        if owns_console():
            return _open_gui_from_owned_console()
        if not _stdin_is_tty():
            parser.print_help(sys.stderr)
            return exit_codes.USAGE
        interactive = True
    else:
        interactive = False

    mode = "shell" if interactive else "cli"
    session_id = new_session_id()
    ctx = create_context(
        mode,
        session_id=session_id,
        verbose=args.verbose,
        no_color=args.no_color,
        json_mode=args.json,
        quiet=args.quiet,
    )

    code = exit_codes.OK
    try:
        ctx.logger.event("admin_status", is_admin=is_admin())
        if interactive:
            ctx.logger.event("cli_start", mode=mode, argv=args_in)
            code = run_shell(parser, ctx)
        else:
            ctx.logger.event("cli_start", mode=mode, argv=args_in, command=args.command)
            from cli.commands import dispatch

            code = dispatch(args, ctx)
    except KeyboardInterrupt:
        ctx.err("")
        ctx.err("interrupted")
        ctx.logger.event("interrupted", phase="cli")
        code = exit_codes.INTERRUPTED
    except Exception as exc:  # last-resort guard so the console never shows a traceback
        ctx.logger.error("cli_crashed", exc_info=True, error=str(exc))
        ctx.err(f"error: {exc}")
        code = exit_codes.FAILURES
    finally:
        ctx.logger.event("app_stop", exit_code=code)
        ctx.color.reset()
        if ctx.color.enabled:
            try:
                ctx.stderr.write("\x1b[0m")
                ctx.stderr.flush()
            except Exception:
                pass
        flush_logging()

    return code


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except Exception:
        return False


def _open_gui_from_owned_console() -> int:
    """Own the console and no command given (double-click): hide it, open the GUI."""

    try:
        import tkinter  # noqa: F401
    except Exception as exc:
        print(f"error: graphical interface unavailable: {exc}", file=sys.stderr)
        return exit_codes.FAILURES
    detach_console()
    return exit_codes.OK if launch_detached_gui() else exit_codes.FAILURES


def _run_gui_process() -> int:
    """Internal entry for the GUI process itself (hidden ``__gui__`` token)."""

    from gui.runtime import build_runtime

    runtime = build_runtime()
    try:
        from gui.app import run_gui

        return run_gui(runtime)
    except KeyboardInterrupt:
        runtime.logger.event("interrupted", phase="gui")
        return exit_codes.INTERRUPTED
    except Exception as exc:
        runtime.logger.error("gui_crashed", exc_info=True, error=str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return exit_codes.FAILURES


if __name__ == "__main__":
    raise SystemExit(main())
