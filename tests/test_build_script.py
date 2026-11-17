from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import config


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


def test_setuptools_packages_vendor_data_without_removed_modules():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"modules*"' not in pyproject
    assert "[tool.setuptools.package-data]" in pyproject
    assert 'core = ["oui_vendors.json"]' in pyproject


def test_config_excludes_retired_dashboard_server_settings():
    assert not hasattr(config, "HOST")
    assert not hasattr(config, "PORT")
    assert not hasattr(config, "REFRESH_INTERVAL_MS")
    assert config.PING_TIMEOUT_SECONDS == 1


@pytest.mark.skipif(
    BASH is None or os.name != "nt",
    reason="Git Bash on Windows is required to exercise the Windows build",
)
def test_build_script_builds_the_setup_installer_with_the_executable(tmp_path):
    source_script = ROOT / "build.sh"
    assert source_script.is_file(), "build.sh should exist in the repository root"

    project = tmp_path / "project"
    project.mkdir()
    shutil.copy2(source_script, project / "build.sh")
    (project / "NetScope.spec").touch()
    (project / "requirements.txt").write_text("runtime-dependency\n", encoding="utf-8")
    (project / "config.py").write_text('APP_VERSION = "1.2.3"\n', encoding="utf-8")

    calls = tmp_path / "python-calls.txt"
    installer_calls = tmp_path / "installer-calls.txt"
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$BUILD_TEST_CALLS\"\n"
        "if [[ \"$*\" == '-m PyInstaller '* ]]; then mkdir -p dist; touch dist/NetScope.exe; fi\n"
        "if [[ \"$*\" == *'import config; print(config.APP_VERSION)'* ]]; then printf '1.2.3\\n'; fi\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    fake_powershell = tmp_path / "fake-powershell"
    fake_powershell.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$BUILD_TEST_INSTALLER_CALLS\"\n"
        "mkdir -p dist/installer\n"
        "touch dist/installer/NetScope-Setup.exe\n",
        encoding="utf-8",
    )
    fake_powershell.chmod(0o755)
    env = os.environ.copy()
    env["PYTHON"] = str(fake_python)
    env["BUILD_TEST_CALLS"] = str(calls)
    env["POWERSHELL"] = str(fake_powershell)
    env["BUILD_TEST_INSTALLER_CALLS"] = str(installer_calls)

    result = subprocess.run(
        [BASH, str(project / "build.sh")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "-m pip install -r requirements.txt",
        "-m pip install pyinstaller",
        "-m PyInstaller --noconfirm --clean --distpath dist NetScope.spec",
        "-c import config; print(config.APP_VERSION)",
    ]
    assert installer_calls.read_text(encoding="utf-8").strip() == (
        "-NoProfile -ExecutionPolicy Bypass -File scripts/build_installer.ps1 -Version 1.2.3"
    )
    assert (project / "dist" / "NetScope.exe").is_file()
    assert (project / "dist" / "installer" / "NetScope-Setup.exe").is_file()
    assert not (project / "NetScope.exe").exists()
