from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", ".git", "tests", "__pycache__", "build", "dist"}


def python_files():
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def test_no_shell_true_anywhere():
    offenders = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant):
                    if keyword.value.value is True:
                        offenders.append(f"{path}:{node.lineno}")
    assert not offenders, f"shell=True found: {offenders}"


def test_no_os_system_calls():
    offenders = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                    and func.attr == "system"
                ):
                    offenders.append(f"{path}:{node.lineno}")
    assert not offenders, f"os.system found: {offenders}"


def test_powershell_scripts_are_static_no_format_slots():
    from powershell import scripts

    offenders = []
    for name in scripts.BATCH_QUERIES:
        expression = scripts.BATCH_QUERIES[name]
        if "{0}" in expression or "%s" in expression:
            offenders.append(name)
    assert not offenders, f"interpolated PowerShell scripts: {offenders}"


def test_user_input_never_built_into_script_text():
    """The PowerShell layer passes values as argv, so no f-string concat exists."""

    source = (ROOT / "powershell" / "runner.py").read_text(encoding="utf-8")
    assert "_argv_for_file" in source
    assert "script_text" in source
    # Values are added with argv.extend([f"-{name}", text]).
    assert "argv.extend" in source
