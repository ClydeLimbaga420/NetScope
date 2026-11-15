from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import config

EXE = os.environ.get("NETSCOPE_EXE")
ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not EXE, reason="set NETSCOPE_EXE to a built NetScope.exe to run frozen-build tests"
)


def test_frozen_exe_reports_version():
    result = subprocess.run(
        [EXE, "--version"],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert config.APP_VERSION in result.stdout


def test_frozen_exe_serves_dashboard_and_shuts_down():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "frozen_smoke.py"), "--exe", EXE],
        check=True,
        timeout=240,
    )
