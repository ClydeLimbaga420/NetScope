"""The "if not resolved" engine: rank probable causes and build report data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from core.models import DiagnosticReport, Status
from fixes.catalog import Catalog, FixEntry, IfUnresolved


@dataclass(frozen=True)
class RankedCause:
    cause: str
    likelihood: str
    score: int
    scope: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause,
            "likelihood": self.likelihood,
            "scope": self.scope,
        }


def _evidence_text(evidence: dict[str, Any]) -> str:
    try:
        return repr(evidence).lower()
    except Exception:
        return ""


def _scope_scores(
    block: IfUnresolved,
    evidence: dict[str, Any],
    another_device_works: bool | None,
) -> tuple[int, int]:
    this_score = 1
    beyond_score = 1
    if another_device_works is True:
        beyond_score += 3
    elif another_device_works is False:
        this_score += 3

    haystack = _evidence_text(evidence)
    if any(
        hint in haystack
        for hint in (
            "incomplete",
            "unreachable",
            "no default route",
            "gateway",
            "link down",
            "media disconnected",
        )
    ):
        beyond_score += 2
    if any(
        hint in haystack
        for hint in (
            "error",
            "degraded",
            "problem",
            "discard",
            "proxy",
            "apipa",
            "duplicate",
            "hosts file",
            "firewall",
        )
    ):
        this_score += 2
    if any(hint in haystack for hint in ("dns", "resolve", "port 53")):
        beyond_score += 1
    return this_score, beyond_score


def _likelihood(score: int, other: int) -> str:
    if score >= other + 2:
        return "probable"
    return "possible"


def rank_causes(
    block: IfUnresolved,
    evidence: dict[str, Any] | None = None,
    another_device_works: bool | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Rank this-device vs beyond-device causes using evidence and isolation."""

    evidence = evidence or {}
    this_score, beyond_score = _scope_scores(block, evidence, another_device_works)

    this_causes = [
        RankedCause(
            cause=cause,
            likelihood=_likelihood(this_score, beyond_score),
            score=this_score,
            scope="this_device",
        )
        for cause in block.this_device
    ]
    beyond_causes = [
        RankedCause(
            cause=cause,
            likelihood=_likelihood(beyond_score, this_score),
            score=beyond_score,
            scope="beyond_device",
        )
        for cause in block.beyond_device
    ]

    this_causes.sort(key=lambda item: (-item.score, item.cause.lower()))
    beyond_causes.sort(key=lambda item: (-item.score, item.cause.lower()))

    ranked = [*this_causes, *beyond_causes]
    ranked.sort(key=lambda item: (-item.score, item.scope != "this_device", item.cause.lower()))
    return {
        "ranked": [item.to_dict() for item in ranked],
        "this_device": [item.to_dict() for item in this_causes],
        "beyond_device": [item.to_dict() for item in beyond_causes],
        "another_device_works": another_device_works,
        "next_checks": list(block.next_checks),
        "evidence_to_collect": list(block.evidence_to_collect),
    }


def unresolved_section(
    entry: FixEntry,
    *,
    evidence: dict[str, Any] | None = None,
    another_device_works: bool | None = None,
    reason: str = "The re-check still reports this problem.",
) -> dict[str, Any]:
    ranking = rank_causes(entry.if_unresolved, evidence, another_device_works)
    return {
        "fix_id": entry.id,
        "name": entry.name,
        "reason": reason,
        "wording": (
            "These are probable or possible causes, not a confirmed diagnosis. "
            "NetScope has not proven a hardware fault."
        ),
        **ranking,
    }


def _result_is_failing(result: Any) -> bool:
    return result.status.severity >= Status.WARN.severity


def build_unresolved_sections(
    report: DiagnosticReport,
    catalog: Catalog,
    *,
    another_device_works: bool | None = None,
    include_fixable: bool = False,
) -> list[dict[str, Any]]:
    """Build report sections for findings that cannot be fixed automatically.

    By default only DETECT-ONLY findings are included, because a fixable
    finding is not "unresolved" until its ladder has run and the re-check has
    failed. The fix executor calls :func:`unresolved_section` directly at that
    point. Set ``include_fixable`` when a front end explicitly wants every
    failing finding.
    """

    sections: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for result in report.results:
        if not _result_is_failing(result):
            continue
        entries = [
            entry
            for entry in (catalog.get(fix_id) for fix_id in result.fix_ids)
            if entry is not None
        ]
        if not entries:
            continue
        if not include_fixable and not (
            result.detection_only or all(entry.detection_only for entry in entries)
        ):
            continue
        for entry in entries:
            key = (result.id, entry.id)
            if key in seen:
                continue
            seen.add(key)
            section = unresolved_section(
                entry,
                evidence=result.evidence,
                another_device_works=another_device_works,
                reason=result.message,
            )
            section["finding_id"] = result.id
            section["finding_title"] = result.title
            section["cause"] = result.cause
            sections.append(section)
    return sections


def unresolved_for_results(
    entries: Iterable[FixEntry],
    evidence: dict[str, Any] | None = None,
    another_device_works: bool | None = None,
) -> list[dict[str, Any]]:
    return [
        unresolved_section(
            entry, evidence=evidence, another_device_works=another_device_works
        )
        for entry in entries
    ]
