"""Shared CLI execution context."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, TextIO

from cli.colors import Colorizer
from core.engine import DiagnosticEngine
from core.logging_config import NullLogger, setup_logging
from core.probes import NetworkProbe
from core.runner import CommandRunner, SubprocessRunner
from powershell.runner import PowerShellLayer


@dataclass
class CliContext:
    logger: Any
    runner: CommandRunner
    ps: PowerShellLayer
    probe: NetworkProbe
    color: Colorizer
    stdin: TextIO = field(default_factory=lambda: sys.stdin)
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)

    def engine(self) -> DiagnosticEngine:
        return DiagnosticEngine(
            runner=self.runner,
            ps=self.ps,
            logger=self.logger,
            probe=self.probe,
        )

    def out(self, text: str = "") -> None:
        print(text, file=self.stdout)

    def err(self, text: str = "") -> None:
        print(text, file=self.stderr)


def create_context(
    mode: str,
    *,
    session_id: str | None = None,
    verbose: bool = False,
    no_color: bool = False,
    json_mode: bool = False,
    quiet: bool = False,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    logger: Any | None = None,
) -> CliContext:
    import logging

    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout or sys.stdout
    err_stream = stderr or sys.stderr

    if logger is None:
        try:
            logger = setup_logging(
                mode,
                session_id or "-",
                console=verbose,
                level=logging.DEBUG if verbose else logging.INFO,
            )
        except Exception:
            logger = NullLogger()

    from cli.colors import color_supported

    color = Colorizer(
        enabled=color_supported(out_stream, no_color=no_color, json_mode=json_mode or quiet),
        stream=out_stream,
    )
    runner = SubprocessRunner(logger)
    layer = PowerShellLayer(runner, logger)
    return CliContext(
        logger=logger,
        runner=runner,
        ps=layer,
        probe=NetworkProbe(),
        color=color,
        stdin=in_stream,
        stdout=out_stream,
        stderr=err_stream,
    )
