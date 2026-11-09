"""NetScope CLI exit codes (documented in ``netscope --help``)."""

from __future__ import annotations

OK = 0
WARNINGS = 1
FAILURES = 2
FIX_FAILED = 3
NEEDS_ADMIN = 4
USAGE = 64
INTERRUPTED = 130

DESCRIPTIONS = {
    OK: "all checks passed or were skipped",
    WARNINGS: "warnings remain",
    FAILURES: "failures remain (including unresolved after fixes)",
    FIX_FAILED: "a fix failed",
    NEEDS_ADMIN: "administrator privileges are required",
    USAGE: "usage error",
    INTERRUPTED: "interrupted with Ctrl+C",
}


def describe(code: int) -> str:
    return DESCRIPTIONS.get(code, "unknown")


HELP_TEXT = """exit codes:
  0   all checks passed or were skipped
  1   warnings remain
  2   failures remain (including unresolved after fixes)
  3   a fix failed
  4   administrator privileges are required
  64  usage error
  130 interrupted with Ctrl+C
"""
