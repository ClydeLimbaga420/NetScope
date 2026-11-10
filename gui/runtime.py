"""Runtime wiring for the GUI front end.

The GUI never builds commands itself; it drives the same ``DiagnosticEngine``,
``FixExecutor`` and fix catalog the CLI uses. This module only assembles those
shared objects without any terminal concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from cli.admin import is_admin
from core.engine import DiagnosticEngine
from core.logging_config import NullLogger, setup_logging
from core.models import new_session_id
from core.probes import NetworkProbe
from core.runner import CommandRunner, SubprocessRunner
from fixes.catalog import Catalog, CatalogError, load_catalog
from fixes.executor import FixExecutor
from powershell.runner import PowerShellLayer


@dataclass
class GuiRuntime:
    """Everything the GUI needs from the shared engine side."""

    engine: Any
    catalog: Catalog
    runner: CommandRunner
    ps: PowerShellLayer
    logger: Any
    admin_check: Callable[[], bool] = is_admin
    session_id: str = "-"
    backup_dir: Any = None

    def executor(self) -> FixExecutor:
        return FixExecutor(
            self.runner,
            self.ps,
            self.logger,
            self.engine,
            self.catalog,
            admin_check=self.admin_check,
            backup_dir=self.backup_dir,
            session_id=self.session_id,
        )


def empty_catalog() -> Catalog:
    return Catalog(version=1, entries=(), source="<unavailable>")


def build_runtime(
    *,
    logger: Any | None = None,
    verbose: bool = False,
) -> GuiRuntime:
    """Build a fresh runtime with its own GUI session id and logging."""

    session_id = new_session_id()
    if logger is None:
        try:
            logger = setup_logging("gui", session_id, console=verbose)
        except Exception:
            logger = NullLogger()
    runner = SubprocessRunner(logger)
    ps = PowerShellLayer(runner, logger)
    engine = DiagnosticEngine(runner=runner, ps=ps, logger=logger, probe=NetworkProbe())
    try:
        catalog = load_catalog()
    except CatalogError as exc:
        logger.warning("fix_catalog_unavailable", error=str(exc))
        catalog = empty_catalog()
    return GuiRuntime(
        engine=engine,
        catalog=catalog,
        runner=runner,
        ps=ps,
        logger=logger,
        session_id=session_id,
    )


def runtime_from_context(ctx: Any) -> GuiRuntime:
    """Reuse an existing CLI context (same logger/session) for in-process GUI launch."""

    try:
        catalog = load_catalog()
    except CatalogError as exc:
        ctx.logger.warning("fix_catalog_unavailable", error=str(exc))
        catalog = empty_catalog()
    return GuiRuntime(
        engine=ctx.engine(),
        catalog=catalog,
        runner=ctx.runner,
        ps=ctx.ps,
        logger=ctx.logger,
        session_id=getattr(ctx.logger, "session_id", "-"),
    )
