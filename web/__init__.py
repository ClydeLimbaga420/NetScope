"""Local web UI package for NetScope.

Front end only: routes and jobs call the existing engine, fix catalog/executor,
and logging. No detection or fix business logic belongs here.
"""

from __future__ import annotations

__all__ = ["create_app"]
