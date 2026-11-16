from __future__ import annotations

from pathlib import Path

SCRIPT = Path("installer/NetScope.iss").read_text(encoding="utf-8")


def test_installer_is_per_user_and_uses_localappdata():
    assert "PrivilegesRequired=lowest" in SCRIPT
    assert r"DefaultDirName={localappdata}\Programs\NetScope" in SCRIPT
    assert "HKLM" not in SCRIPT


def test_installer_has_stable_identity_and_payload():
    assert "8E6F1C2A-4B7D-4E3A-9C5F-2D1B7A6E8F04" in SCRIPT
    assert "AppName=NetScope" in SCRIPT
    assert "OutputBaseFilename=NetScope-Setup" in SCRIPT
    assert r'Source: "..\dist\NetScope.exe"' in SCRIPT


def test_installer_creates_shortcuts_app_paths_and_path_entry():
    assert r"{autoprograms}\NetScope" in SCRIPT
    assert r"{autodesktop}\NetScope" in SCRIPT
    assert "App Paths" in SCRIPT
    assert "Environment" in SCRIPT
    assert "preservestringtype" in SCRIPT
    assert "NeedsAddPath" in SCRIPT
    assert ".netscope-inno" in SCRIPT


def test_installer_removes_path_and_offers_clean_data_removal():
    assert "CurUninstallStepChanged" in SCRIPT
    assert "RemoveFromUserPath" in SCRIPT
    assert "UninstallSilent" in SCRIPT
    assert "MB_YESNO" in SCRIPT
    assert "MB_DEFBUTTON1" in SCRIPT
    assert r"{localappdata}\NetScope" in SCRIPT
