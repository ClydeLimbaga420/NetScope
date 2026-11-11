"""One-click default-gateway configuration shared by both front ends.

The button path is intentionally narrower than the general fix flow: it only
runs the catalog's ``IP-09`` repair and only when no default route exists. The
executor still takes the pre-fix snapshot, verifies the result and exposes the
same rollback path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.gateway_setup import default_route_gateway


@dataclass
class GatewayConfigResult:
    status: str
    fix_id: str = "IP-09"
    adapter: str | None = None
    gateway: str | None = None
    message: str = ""
    outcome: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fix_id": self.fix_id,
            "adapter": self.adapter,
            "gateway": self.gateway,
            "message": self.message,
            "outcome": self.outcome,
        }


def auto_configure_gateway(runtime: Any, snapshot: Any | None = None) -> GatewayConfigResult:
    """Detect and apply a missing default gateway with no preview step."""

    try:
        snap = snapshot if snapshot is not None else runtime.engine.collect_snapshot()
    except Exception as exc:  # noqa: BLE001
        return GatewayConfigResult("error", message=f"Could not inspect the network: {exc}")

    existing = default_route_gateway(snap)
    if existing:
        return GatewayConfigResult(
            "already_configured",
            gateway=existing,
            message="A default gateway is already configured.",
        )

    try:
        entry = runtime.catalog.require("IP-09")
        executor = runtime.executor()
        plan = executor.prepare(entry, snapshot=snap)
    except Exception as exc:  # noqa: BLE001
        return GatewayConfigResult("error", message=str(exc))

    adapter = plan.values.get("AdapterName")
    gateway = plan.values.get("Gateway")
    try:
        outcome = executor.run(
            entry,
            plan=plan,
            assume_yes=True,
            dry_run=False,
            confirm=lambda _question: True,
        )
    except Exception as exc:  # noqa: BLE001
        return GatewayConfigResult(
            "error",
            adapter=adapter,
            gateway=gateway,
            message=str(exc),
        )

    return GatewayConfigResult(
        outcome.status,
        adapter=adapter,
        gateway=gateway,
        message=outcome.message,
        outcome=outcome.to_dict(),
    )
