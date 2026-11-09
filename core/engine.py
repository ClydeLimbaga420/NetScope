"""The diagnostic engine: collect once, run ordered checks, return plain data."""

from __future__ import annotations

import traceback
from typing import Any, Callable, Sequence

from core.checks import adapter, dns, gateway, internet, ip, lan, services, stack
from core.checks.context import CheckContext
from core.models import (
    LAYER_ORDER,
    CheckResult,
    DiagnosticReport,
    Layer,
    Status,
    new_session_id,
)
from core.probes import NetworkProbe
from core.runner import CommandRunner, SubprocessRunner
from core.snapshot import Snapshot, collect_snapshot
from powershell.runner import PowerShellLayer

CHECK_MODULES = {
    Layer.ADAPTER: (adapter,),
    Layer.SERVICES: (services,),
    Layer.IP: (ip,),
    Layer.GATEWAY: (gateway,),
    Layer.LAN: (lan,),
    Layer.DNS: (dns,),
    Layer.INTERNET: (internet,),
    Layer.STACK: (stack,),
}

ProgressCallback = Callable[[Layer, list[CheckResult]], None]
CheckCallback = Callable[[CheckResult], None]


def resolve_layers(layers: Sequence[str | Layer] | None) -> list[Layer]:
    if not layers:
        return list(LAYER_ORDER)

    resolved: list[Layer] = []
    for item in layers:
        try:
            layer = item if isinstance(item, Layer) else Layer(str(item).lower())
        except ValueError as exc:
            raise ValueError(f"unknown layer: {item}") from exc
        if layer not in resolved:
            resolved.append(layer)
    return [layer for layer in LAYER_ORDER if layer in resolved]


class DiagnosticEngine:
    """Runs the pipeline. Contains no rendering or UI code."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        ps: PowerShellLayer | None = None,
        logger: Any | None = None,
        probe: NetworkProbe | None = None,
        hosts_path: Any | None = None,
    ):
        self.logger = logger
        self.runner = runner or SubprocessRunner(logger)
        self.ps = ps
        self.probe = probe or NetworkProbe()
        self.hosts_path = hosts_path

    def _snapshot(self) -> Snapshot:
        layer = self.ps or PowerShellLayer(self.runner, self.logger)
        return collect_snapshot(self.runner, layer, self.logger)

    def collect_snapshot(self) -> Snapshot:
        """Collect machine state without running any checks."""

        return self._snapshot()

    def diagnose(
        self,
        layers: Sequence[str | Layer] | None = None,
        *,
        snapshot: Snapshot | None = None,
        progress: ProgressCallback | None = None,
        on_check: CheckCallback | None = None,
        mode: str = "cli",
    ) -> DiagnosticReport:
        selected = resolve_layers(layers)
        session_id = getattr(self.logger, "session_id", None) or new_session_id()
        report = DiagnosticReport.create(session_id=session_id, mode=mode)

        try:
            state = snapshot if snapshot is not None else self._snapshot()
        except KeyboardInterrupt:
            if self.logger is not None:
                self.logger.event("interrupted", phase="collect")
            raise
        except Exception as exc:
            if self.logger is not None:
                self.logger.error("snapshot_failed", exc_info=True, error=str(exc))
            raise

        report.snapshot = state.to_dict()
        ctx = CheckContext(
            snapshot=state,
            probe=self.probe,
            logger=self.logger,
            hosts_path=self.hosts_path,
        )

        for layer in selected:
            layer_results: list[CheckResult] = []
            for module in CHECK_MODULES[layer]:
                try:
                    produced = module.run(ctx)
                except KeyboardInterrupt:
                    if self.logger is not None:
                        self.logger.event("interrupted", phase=layer.value)
                    raise
                except Exception as exc:  # a broken check must not kill the run
                    produced = [
                        CheckResult(
                            id=f"{layer.value.upper()}-ERROR",
                            layer=layer,
                            status=Status.ERROR,
                            title="Check failed to run",
                            message=str(exc),
                            cause="Internal error in this check; other checks still ran.",
                            evidence={"traceback": traceback.format_exc()[-2000:]},
                        )
                    ]
                    if self.logger is not None:
                        self.logger.error(
                            "check_failed", exc_info=True, layer=layer.value, error=str(exc)
                        )

                for result in produced or []:
                    report.add(result)
                    layer_results.append(result)
                    if self.logger is not None:
                        self.logger.check(result)
                    if on_check is not None:
                        on_check(result)

            if progress is not None:
                progress(layer, layer_results)

        report.finish()
        if self.logger is not None:
            self.logger.event(
                "diagnose_complete",
                overall_status=report.overall_status.value,
                first_failing_layer=(
                    report.first_failing_layer.value if report.first_failing_layer else None
                ),
                exit_code=report.exit_code,
                result_count=len(report.results),
            )
        return report
