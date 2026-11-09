#!/usr/bin/env python3
"""Convenience launcher: ``python netscope.py <command>``."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
