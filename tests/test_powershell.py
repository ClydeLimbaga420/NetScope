from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.runner import FakeRunner
from powershell.runner import (
    PowerShellError,
    PowerShellLayer,
    as_list,
    parse_powershell_json,
)
from powershell.validation import (
    ValidationError,
    validate_adapter_name,
    validate_host,
    validate_port,
    validate_port_spec,
)


def test_parse_json_handles_bom_and_warnings():
    assert parse_powershell_json('\ufeff{"a": 1}') == {"a": 1}
    assert parse_powershell_json('warning line\n[{"a": 1}]\n') == [{"a": 1}]
    assert parse_powershell_json("") is None
    with pytest.raises(PowerShellError):
        parse_powershell_json("not json at all")


def test_batch_parses_and_strips_errors(tmp_path):
    payload = {
        "adapters": [{"Name": "Ethernet"}],
        "services": [],
        "services__error": "cmdlet missing",
    }
    runner = FakeRunner({"powershell.exe": (0, json.dumps(payload), "")})
    layer = PowerShellLayer(runner, temp_root=tmp_path)

    batch = layer.run_batch(["adapters", "services"])

    assert batch.available
    assert batch.data["adapters"][0]["Name"] == "Ethernet"
    assert batch.errors == {"services": "cmdlet missing"}
    assert "services__error" not in batch.data
    assert runner.calls
    assert runner.calls[0][0] == "powershell.exe"


def test_batch_rejects_unknown_section(tmp_path):
    runner = FakeRunner()
    layer = PowerShellLayer(runner, temp_root=tmp_path)
    with pytest.raises(ValueError):
        layer.run_batch(["nope"])


def test_batch_handles_empty_output(tmp_path):
    runner = FakeRunner({"powershell.exe": (0, "", "")})
    layer = PowerShellLayer(runner, temp_root=tmp_path)
    batch = layer.run_batch(["adapters"])
    assert batch.data == {}
    assert batch.command is not None


def test_language_mode_detection(tmp_path):
    runner = FakeRunner({"powershell.exe": (0, "ConstrainedLanguage\n", "")})
    layer = PowerShellLayer(runner, temp_root=tmp_path)
    assert layer.detect_language_mode() == "ConstrainedLanguage"
    assert layer.constrained


def test_unavailable_language_mode(tmp_path):
    runner = FakeRunner({"powershell.exe": (127, "", "missing")})
    layer = PowerShellLayer(runner, temp_root=tmp_path)
    assert layer.detect_language_mode() == "Unavailable"


def test_user_values_are_separate_arguments(tmp_path):
    runner = FakeRunner({"powershell.exe": (0, "ok", "")})
    layer = PowerShellLayer(runner, temp_root=tmp_path)
    hostile = 'x & calc"; del *; `whoami`'

    argv = layer._argv_for_file(Path("script.ps1"), {"Name": hostile})

    assert argv[-2:] == ["-Name", hostile]
    assert argv[-2] == "-Name"
    assert "script.ps1" in argv
    # The value is one argument, never concatenated into the script path/text.
    assert all(hostile != part or part == hostile for part in argv)


def test_boolean_switch_parameter(tmp_path):
    layer = PowerShellLayer(FakeRunner(), temp_root=tmp_path)
    argv = layer._argv_for_file(Path("s.ps1"), {"Force": True, "Other": False})
    assert "-Force" in argv
    assert "-Other" not in argv


def test_parameter_validation(tmp_path):
    layer = PowerShellLayer(FakeRunner(), temp_root=tmp_path)
    with pytest.raises(ValidationError):
        layer._argv_for_file(Path("s.ps1"), {"Bad-Name": "x"})
    with pytest.raises(ValidationError):
        layer._argv_for_file(Path("s.ps1"), {"Name": "line\nbreak"})


def test_as_list_normalisation():
    assert as_list(None) == []
    assert as_list({"a": 1}) == [{"a": 1}]
    assert as_list([{"a": 1}, "junk", {"b": 2}]) == [{"a": 1}, {"b": 2}]


@pytest.mark.parametrize(
    "value",
    ["8.8.8.8 & del *", '"; calc', "1.1.1.1; calc", "foo bar"],
)
def test_malicious_hosts_rejected(value):
    with pytest.raises(ValidationError):
        validate_host(value)


@pytest.mark.parametrize("value", ["8.8.8.8", "example.com", "::1"])
def test_valid_hosts_accepted(value):
    assert validate_host(value) == value


def test_adapter_and_port_validation():
    assert validate_adapter_name("Wi-Fi 2") == "Wi-Fi 2"
    with pytest.raises(ValidationError):
        validate_adapter_name('bad"; calc')
    assert validate_port("443") == 443
    with pytest.raises(ValidationError):
        validate_port("70000")
    assert validate_port_spec("80,443,8000-8080") == "80,443,8000-8080"
    with pytest.raises(ValidationError):
        validate_port_spec("80; calc")
