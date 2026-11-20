"""Free-space awareness and bounded cleanup for NetScope's local artifacts.

Every helper here is defensive: a full or momentarily unreadable disk must
never raise into a worker thread or take down the web UI. When free space
cannot be determined the helpers fail open, because the existing OSError
guards around each individual write still apply.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import config


@dataclass(frozen=True)
class DiskSpace:
    path: str
    total: int
    used: int
    free: int

    @property
    def free_mb(self) -> float:
        return round(self.free / (1024 * 1024), 1)

    @property
    def low(self) -> bool:
        return self.free < config.MIN_FREE_DISK_BYTES


@dataclass(frozen=True)
class PruneResult:
    removed: int = 0
    bytes_freed: int = 0
    kept: int = 0


def _existing_target(path: Path) -> Path:
    candidate = path.expanduser()
    while True:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            pass
        parent = candidate.parent
        if parent == candidate:
            return candidate
        candidate = parent


def probe(path: Path | str | None = None) -> DiskSpace | None:
    """Return free-space information for the volume holding *path*."""

    target = Path(path) if path is not None else config.data_dir()
    try:
        usage = shutil.disk_usage(_existing_target(target))
    except (OSError, ValueError):
        return None
    return DiskSpace(path=str(target), total=usage.total, used=usage.used, free=usage.free)


def free_bytes(path: Path | str | None = None) -> int | None:
    info = probe(path)
    return info.free if info is not None else None


def is_low(path: Path | str | None = None) -> bool:
    info = probe(path)
    return bool(info is not None and info.low)


def log_status(
    logger: Any | None,
    path: Path | str | None = None,
    event: str = "disk_space_status",
) -> DiskSpace | None:
    """Emit one structured record describing the current disk headroom."""

    info = probe(path)
    if logger is None:
        return info
    try:
        if info is None:
            logger.warning("disk_space_unavailable", source="disk")
        else:
            logger.event(
                event,
                source="disk",
                path=info.path,
                free_bytes=info.free,
                total_bytes=info.total,
                low=info.low,
            )
    except Exception:
        pass
    return info


def prune_files(
    directory: Path | str,
    *,
    pattern: str = "*",
    max_files: int | None = None,
    max_age_seconds: float | None = None,
    max_bytes: int | None = None,
    protect: Iterable[Path | str] = (),
) -> PruneResult:
    """Delete the oldest matching files until every configured cap is met.

    Individual stat/unlink failures are ignored so cleanup can never break the
    write that follows it. Paths in *protect* are compared by file name and are
    never removed; this keeps the newest rollback snapshot for each fix.
    """

    directory = Path(directory)
    protected = {Path(item).name for item in protect}
    try:
        if not directory.is_dir():
            return PruneResult()
        entries = list(directory.glob(pattern))
    except OSError:
        return PruneResult()

    now = time.time()
    candidates: list[tuple[Path, int, float]] = []
    for path in entries:
        if path.name in protected:
            continue
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            continue
        candidates.append((path, stat.st_size, stat.st_mtime))
    candidates.sort(key=lambda item: item[2])

    if max_age_seconds is not None:
        victims = [item for item in candidates if now - item[2] > max_age_seconds]
        victim_names = {item[0].name for item in victims}
        kept = [item for item in candidates if item[0].name not in victim_names]
    else:
        victims = []
        kept = list(candidates)

    total = sum(item[1] for item in kept)
    while kept and (
        (max_files is not None and len(kept) > max_files)
        or (max_bytes is not None and total > max_bytes)
    ):
        victim = kept.pop(0)
        victims.append(victim)
        total -= victim[1]

    removed = 0
    bytes_freed = 0
    for path, size, _mtime in victims:
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
        bytes_freed += size
    return PruneResult(removed=removed, bytes_freed=bytes_freed, kept=len(kept))


def _prepare(
    directory: Path,
    *,
    kind: str,
    logger: Any | None,
    protect: Iterable[Path | str],
    max_files: int,
    max_bytes: int,
    max_age_seconds: int,
) -> PruneResult:
    result = prune_files(
        directory,
        max_files=max_files,
        max_bytes=max_bytes,
        max_age_seconds=max_age_seconds,
        protect=protect,
    )
    info = probe(directory)
    if info is not None and info.low and logger is not None:
        try:
            logger.warning(
                "disk_space_low",
                source="disk",
                kind=kind,
                free_bytes=info.free,
                threshold_bytes=config.MIN_FREE_DISK_BYTES,
                pruned=result.removed,
                bytes_freed=result.bytes_freed,
            )
        except Exception:
            pass
    return result


def prepare_report_write(
    directory: Path | str | None = None,
    logger: Any | None = None,
) -> PruneResult:
    target = Path(directory) if directory is not None else config.report_dir()
    return _prepare(
        target,
        kind="reports",
        logger=logger,
        protect=(),
        max_files=config.REPORT_MAX_FILES,
        max_bytes=config.REPORT_MAX_BYTES,
        max_age_seconds=config.ARTIFACT_MAX_AGE_SECONDS,
    )


def prepare_backup_write(
    directory: Path | str | None = None,
    logger: Any | None = None,
    protect: Iterable[Path | str] = (),
) -> PruneResult:
    target = Path(directory) if directory is not None else config.backup_dir()
    return _prepare(
        target,
        kind="backups",
        logger=logger,
        protect=protect,
        max_files=config.BACKUP_MAX_FILES,
        max_bytes=config.BACKUP_MAX_BYTES,
        max_age_seconds=config.ARTIFACT_MAX_AGE_SECONDS,
    )


def should_skip_optional_write(
    path: Path | str | None = None,
    logger: Any | None = None,
    kind: str = "optional",
) -> bool:
    """Return True when an optional cache write should be skipped."""

    info = probe(path)
    if info is None or not info.low:
        return False
    if logger is not None:
        try:
            logger.warning(
                "optional_write_skipped",
                source="disk",
                kind=kind,
                free_bytes=info.free,
                threshold_bytes=config.MIN_FREE_DISK_BYTES,
            )
        except Exception:
            pass
    return True
