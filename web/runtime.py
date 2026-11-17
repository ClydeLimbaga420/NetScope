"""Runtime wiring shared by the CLI and the localhost web UI.

Front ends never build commands themselves; they drive the same
``DiagnosticEngine``, ``FixExecutor`` and fix catalog. This module only
assembles those shared objects without any terminal or browser concerns.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

import psutil

from cli.admin import is_admin
from core.engine import DiagnosticEngine
from core.logging_config import NullLogger, setup_logging
from core.models import new_session_id
from core.monitoring import MonitoringService, NetworkCounters
from core.probes import NetworkProbe
from core.runner import CommandRunner, SubprocessRunner
from fixes.catalog import Catalog, CatalogError, load_catalog
from fixes.executor import FixExecutor
from powershell.runner import PowerShellLayer


@dataclass
class AppRuntime:
    """Everything a front end needs from the shared engine side."""

    engine: Any
    catalog: Catalog
    runner: CommandRunner
    ps: PowerShellLayer
    logger: Any
    monitoring: MonitoringService
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


def build_monitoring_service(
    engine: DiagnosticEngine,
    runner: CommandRunner,
    ps: PowerShellLayer,
    logger: Any,
) -> MonitoringService:
    """Build the core monitoring service with machine-wide byte counters."""

    def counter_provider() -> NetworkCounters:
        counters = psutil.net_io_counters()
        if counters is None:
            raise RuntimeError("Network interface counters are unavailable")
        return NetworkCounters(
            bytes_received=counters.bytes_recv,
            bytes_sent=counters.bytes_sent,
        )

    return MonitoringService(
        engine,
        runner,
        ps,
        counter_provider=counter_provider,
        clock=time.monotonic,
        logger=logger,
    )


def build_runtime(
    *,
    logger: Any | None = None,
    verbose: bool = False,
) -> AppRuntime:
    """Build a fresh runtime with its own session id and logging."""

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
    monitoring = build_monitoring_service(engine, runner, ps, logger)
    return AppRuntime(
        engine=engine,
        catalog=catalog,
        runner=runner,
        ps=ps,
        logger=logger,
        monitoring=monitoring,
        session_id=session_id,
    )


def runtime_from_context(ctx: Any) -> AppRuntime:
    """Reuse an existing CLI context (same logger/session) for in-process launch."""

    try:
        catalog = load_catalog()
    except CatalogError as exc:
        ctx.logger.warning("fix_catalog_unavailable", error=str(exc))
        catalog = empty_catalog()
    engine = ctx.engine()
    return AppRuntime(
        engine=engine,
        catalog=catalog,
        runner=ctx.runner,
        ps=ctx.ps,
        logger=ctx.logger,
        monitoring=build_monitoring_service(
            engine,
            ctx.runner,
            ctx.ps,
            ctx.logger,
        ),
        session_id=getattr(ctx.logger, "session_id", "-"),
    )
