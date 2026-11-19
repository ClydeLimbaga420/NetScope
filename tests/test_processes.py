from __future__ import annotations

import os
from types import SimpleNamespace

from core import processes


def fake_process(pid: int, exe: str, cmdline: list[str], username: str = "user"):
    return SimpleNamespace(
        pid=pid,
        exe=lambda: exe,
        cmdline=lambda: cmdline,
        info={"pid": pid, "username": username, "exe": exe, "cmdline": cmdline},
    )


def test_is_netscope_process_matches_installed_executable(tmp_path):
    exe = str(tmp_path / "NetScope.exe")
    other = str(tmp_path.parent / "other" / "NetScope.exe")
    proc = fake_process(1, exe, [exe])

    assert processes.is_netscope_process(proc, install_dirs=[tmp_path]) is True
    assert processes.is_netscope_process(proc, install_dirs=[tmp_path.parent / "other"]) is False
    assert processes.is_netscope_process(proc) is True


def test_is_netscope_process_matches_hidden_cli_markers():
    python = r"C:\Python314\python.exe"
    assert processes.is_netscope_process(
        fake_process(2, python, [python, "-m", "cli", "gui", "--print-url"])
    )
    assert processes.is_netscope_process(
        fake_process(3, python, [python, r"C:\src\netscope.py", "__gui__"])
    )
    assert processes.is_netscope_process(
        fake_process(4, r"C:\Programs\NetScope\NetScope.exe", [r"C:\Programs\NetScope\NetScope.exe", "__stop_all__"])
    )


def test_is_netscope_process_never_matches_browsers_or_unrelated_python():
    browser = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    python = r"C:\Python314\python.exe"
    assert not processes.is_netscope_process(
        fake_process(5, browser, [browser, "--app=http://127.0.0.1:1/__boot__"])
    )
    webview = r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\msedgewebview2.exe"
    assert not processes.is_netscope_process(fake_process(6, webview, [webview]))
    assert not processes.is_netscope_process(fake_process(7, python, [python, "-m", "pytest"]))


def test_netscope_processes_filters_other_users_and_excluded_pids(monkeypatch, tmp_path):
    exe = str(tmp_path / "NetScope.exe")
    mine = fake_process(11, exe, [exe], username="me")
    theirs = fake_process(12, exe, [exe], username="someone-else")
    unrelated = fake_process(13, r"C:\Python314\python.exe", [r"C:\Python314\python.exe", "-m", "pytest"], username="me")
    monkeypatch.setattr(processes, "current_username", lambda: "me")
    monkeypatch.setattr(processes.psutil, "process_iter", lambda *_args, **_kwargs: [mine, theirs, unrelated])

    found = processes.netscope_processes(install_dirs=[tmp_path], exclude_pids={99})
    assert [proc.pid for proc in found] == [11]


def test_terminate_processes_escalates_to_kill(monkeypatch):
    events = []

    def make(pid):
        return SimpleNamespace(
            pid=pid,
            terminate=lambda: events.append(("terminate", pid)),
            kill=lambda: events.append(("kill", pid)),
        )

    first = make(21)
    second = make(22)
    stubborn = make(23)
    monkeypatch.setattr(
        processes.psutil, "wait_procs", lambda _procs, timeout: ([first], [stubborn])
    )

    assert processes.terminate_processes([first, second, stubborn], grace=0.1) == 3
    assert events == [
        ("terminate", 21),
        ("terminate", 22),
        ("terminate", 23),
        ("kill", 23),
    ]


def test_terminate_tree_kills_descendants_before_root(monkeypatch):
    calls = []
    monkeypatch.setattr(
        processes, "descendant_processes", lambda pid, **_kwargs: [SimpleNamespace(pid=31)]
    )
    monkeypatch.setattr(
        processes, "terminate_processes", lambda procs, **_kwargs: calls.append([p.pid for p in procs]) or len(procs)
    )
    monkeypatch.setattr(
        processes.psutil,
        "Process",
        lambda pid: SimpleNamespace(pid=pid),
    )

    assert processes.terminate_tree(4321, grace=0.1) == 2
    assert calls == [[31], [4321]]


def test_terminate_children_excludes_detached_gui_child(monkeypatch):
    seen = {}
    processes.PERSISTENT_CHILD_PIDS.add(4321)
    try:

        def fake_tree(pid, *, grace, exclude_pids):
            seen.update(pid=pid, grace=grace, exclude=set(exclude_pids))
            return 0

        monkeypatch.setattr(processes, "terminate_tree", fake_tree)
        processes.terminate_children_of_current_process(
            grace=0.5, exclude_pids=processes.PERSISTENT_CHILD_PIDS
        )
        assert seen == {
            "pid": os.getpid(),
            "grace": 0.5,
            "exclude": {4321},
        }
    finally:
        processes.PERSISTENT_CHILD_PIDS.discard(4321)


def test_wait_for_exit_returns_when_process_disappears(monkeypatch):
    checks = iter([True, False])
    times = iter([0.0, 0.1])
    monkeypatch.setattr(processes.psutil, "pid_exists", lambda _pid: next(checks))
    monkeypatch.setattr(processes.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(processes.time, "sleep", lambda _seconds: None)
    assert processes.wait_for_exit(999, timeout=1) is True


def test_wait_for_exit_gives_up_after_timeout(monkeypatch):
    monkeypatch.setattr(processes.psutil, "pid_exists", lambda _pid: True)
    times = iter([0.0, 2.0])
    monkeypatch.setattr(processes.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(processes.time, "sleep", lambda _seconds: None)
    assert processes.wait_for_exit(999, timeout=1) is False
