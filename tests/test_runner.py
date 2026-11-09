from __future__ import annotations

import sys

import pytest

from core.runner import CommandResult, FakeRunner, SubprocessRunner


def test_subprocess_runner_runs_argument_list():
    runner = SubprocessRunner(default_timeout=10)
    result = runner.run([sys.executable, "-c", "print('hello-netscope')"])
    assert result.ok
    assert "hello-netscope" in result.stdout
    assert result.args[0] == sys.executable


def test_subprocess_runner_rejects_shell_string():
    runner = SubprocessRunner()
    with pytest.raises(TypeError):
        runner.run("echo hello")  # type: ignore[arg-type]


def test_subprocess_runner_missing_command():
    runner = SubprocessRunner()
    result = runner.run(["netscope-definitely-not-a-real-binary"])
    assert not result.ok
    assert result.returncode == 127
    assert result.error


def test_subprocess_runner_timeout():
    runner = SubprocessRunner()
    result = runner.run(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        timeout=0.2,
    )
    assert result.timed_out
    assert not result.ok
    assert result.returncode == 124


def test_fake_runner_records_and_returns():
    runner = FakeRunner({"ping": (0, "time=1ms", "")})
    result = runner.run(["ping", "-n", "1", "1.1.1.1"])
    assert result.ok
    assert "time=1ms" in result.stdout
    assert runner.calls == [("ping", "-n", "1", "1.1.1.1")]

    custom = CommandResult(args=("x",), returncode=0, stdout="custom")
    runner = FakeRunner({"x": custom})
    assert runner.run(["x"]).stdout == "custom"

    runner = FakeRunner({"x": ValueError("boom")})
    with pytest.raises(ValueError):
        runner.run(["x"])
