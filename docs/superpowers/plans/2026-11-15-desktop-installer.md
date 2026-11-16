# NetScope desktop window + installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Ship NetScope as a per-user Windows desktop application with an Inno Setup installer, a native pywebview/WebView2 window, and `netscope` available on the user PATH.

**Architecture:** Keep the existing Flask/Werkzeug server and all diagnostic/fix logic. `web/run.py` gains `window`, `browser`, and `headless` launch modes; `web/window.py` hosts the WebView2 window. Inno Setup owns the per-user install layout, shortcuts, PATH entry, App Paths entry, and uninstaller. The CLI installer remains for portable/source installs but refuses to modify an Inno-managed install.

**Tech Stack:** Python 3.14, Flask/Werkzeug, pywebview + WebView2/pythonnet, PyInstaller one-file console build, Inno Setup 6/7, PowerShell build scripts, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-15-desktop-installer-design.md`

## Global Constraints

- Per-user install only; `PrivilegesRequired=lowest`; never write `HKLM` or require admin.
- Default install directory is `%LOCALAPPDATA%\Programs\NetScope`.
- Keep one server per user; a second launch resolves the existing boot URL and opens another window.
- Server stays bound to `127.0.0.1`; boot/session tokens, CSP, same-origin checks, and offline assets remain unchanged.
- `netscope`, `netscope diagnose`, `netscope gui --no-browser`, `__gui__`, and the JSON API keep working.
- `window` is the default `gui`/shortcut mode; `--browser` forces the existing Edge/Chrome path; `--no-browser` is headless.
- Clean uninstall by default: remove `%LOCALAPPDATA%\NetScope` (logs/reports/backups), with a prompt defaulting to Yes and an opt-out.
- The installer writes `.netscope-inno`; `netscope install`/`uninstall` must refuse to touch that install.
- App version comes from `config.APP_VERSION`; AppId is a stable GUID owned by NetScope.
- No auto-update, code signing, MSI, machine-wide install, or icon change in this change.
- Payload stays a one-file console-subsystem PyInstaller executable; the brief console flash on shortcut launch remains accepted.
- Do not put diagnostic/fix/installer business logic in `web/` or the installer.
- No commit or push steps: repository policy requires an explicit user request before either.

## Review Focus

1. **Python 3.14 + pythonnet/pywebview compatibility:** importing pywebview or starting the edgechromium backend must not fail the app; verify the installed versions support the project interpreter before relying on the window path.
2. **WebView2/pywebview unavailable:** the app must log `webview_unavailable`, fall back to the browser path, and still serve the UI instead of crashing.
3. **Second launch / stale lock:** a second process must open the existing boot URL or print it, never start a competing server or hang indefinitely.
4. **Elevation handoff:** the old server must stop, the elevated process must wait for the lock, and a cancelled UAC prompt must leave the original server running.
5. **Uninstall cleanup:** default uninstall removes app, shortcuts, App Paths, PATH entry, and `%LOCALAPPDATA%\NetScope`; opt-out keeps data; unrelated PATH entries survive.

---

### Task 1: WebView2 detection and native window host

**Files:**
- Create: `web/window.py`
- Create: `tests/test_window.py`
- Modify: `requirements.txt`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WEBVIEW2_CLIENT_ID: str`, `_webview2_version() -> str | None`, `webview2_available() -> bool`, `run_native_window(boot_url: str) -> bool`.

- [x] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import sys
from types import SimpleNamespace

import web.window as window


def test_webview2_available_positive(monkeypatch):
    monkeypatch.setattr(window, "_webview2_version", lambda: "120.0.2210.91")
    assert window.webview2_available() is True


def test_webview2_available_missing_or_zero(monkeypatch):
    monkeypatch.setattr(window, "_webview2_version", lambda: None)
    assert window.webview2_available() is False
    monkeypatch.setattr(window, "_webview2_version", lambda: "0.0.0.0")
    assert window.webview2_available() is False


def test_run_native_window_skips_without_runtime(monkeypatch):
    monkeypatch.setattr(window, "webview2_available", lambda: False)
    assert window.run_native_window("http://127.0.0.1:1/__boot__") is False


def test_run_native_window_configures_edgechromium(monkeypatch):
    url = "http://127.0.0.1:54321/__boot__?token=t"
    calls = {}
    fake = SimpleNamespace(
        create_window=lambda *args, **kwargs: calls.setdefault("window", (args, kwargs)),
        start=lambda **kwargs: calls.setdefault("start", kwargs),
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(window, "webview2_available", lambda: True)

    assert window.run_native_window(url) is True
    args, kwargs = calls["window"]
    assert args == ("NetScope", url)
    assert kwargs == {"width": 1280, "height": 860, "min_size": (900, 600)}
    assert calls["start"] == {"gui": "edgechromium", "debug": False}
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_window.py -v`
Expected: FAIL because `web.window` does not exist.

- [x] **Step 3: Implement `web/window.py`**

```python
WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _webview2_version() -> str | None:
    """Return the installed WebView2 runtime version, or None."""


def webview2_available() -> bool:
    """True when a WebView2 runtime newer than 0.0.0.0 is registered."""


def run_native_window(boot_url: str) -> bool:
    """Open the NetScope window and block until it closes."""
```

Implementation rules:
- `_webview2_version` returns `None` when `os.name != "nt"`; otherwise checks HKCU and HKLM (including `WOW6432Node`) `...\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` `pv` values with `winreg`, returning the first string found.
- `webview2_available` parses the first four dot-separated version parts as integers and returns `False` on missing/non-numeric/`0.0.0.0` values.
- `run_native_window` returns `False` when WebView2 is unavailable or `import webview` fails; otherwise calls `webview.create_window("NetScope", boot_url, width=1280, height=860, min_size=(900, 600))` then `webview.start(gui="edgechromium", debug=False)`, returning `True`. Catch pywebview start errors and return `False`.

- [x] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_window.py -v`
Expected: PASS.

- [x] **Step 5: Add dependencies and verify the interpreter can import pywebview**

Add to `requirements.txt`:

```text
pywebview>=5.4
pythonnet>=3.0; sys_platform == "win32"
```

Add the same two lines to `[project].dependencies` in `pyproject.toml`. Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -c "import webview, clr; print(webview.__version__)"
```

Expected: a pywebview version prints. If `import webview` or `import clr` fails on Python 3.14, stop and report the exact error before continuing; do not silently replace the window requirement with browser mode.

---

### Task 2: Launch modes, window lifecycle, and lock takeover

**Files:**
- Modify: `web/run.py`
- Modify: `tests/test_window.py`

**Interfaces:**
- Consumes: `run_native_window`, `webview2_available` from Task 1.
- Produces:
  - `run_web_ui(port: int | None = None, no_browser: bool = False, browser: bool = False, print_url: bool = False, replace: bool = False) -> int`
  - `_launch_mode(no_browser: bool, browser: bool) -> str`
  - `_show_existing(url: str, mode: str, state: WebState) -> bool`
  - `_acquire_lock_with_wait(timeout: float = 10.0) -> BinaryIO | None`
  - `_run_window_session(state: WebState, srv: object, boot_url: str, print_url: bool) -> None`

- [x] **Step 1: Write the failing tests**

Add to `tests/test_window.py`:

```python
import threading
from types import SimpleNamespace

import web.run as run


class WindowLogger:
    def __init__(self):
        self.events = []

    def warning(self, event, **fields):
        self.events.append((event, fields))

    def event(self, event, **fields):
        self.events.append((event, fields))

    def error(self, event, **fields):
        self.events.append((event, fields))


def test_launch_mode_precedence():
    assert run._launch_mode(True, True) == "headless"
    assert run._launch_mode(False, True) == "browser"
    assert run._launch_mode(False, False) == "window"


def test_show_existing_window_uses_native(monkeypatch):
    calls = []
    state = SimpleNamespace(logger=WindowLogger())
    monkeypatch.setattr(run, "run_native_window", lambda url: calls.append(url) or True)
    assert run._show_existing("http://127.0.0.1:1/boot", "window", state) is True
    assert calls == ["http://127.0.0.1:1/boot"]


def test_show_existing_browser_uses_open_url(monkeypatch):
    calls = []
    state = SimpleNamespace(logger=WindowLogger())
    monkeypatch.setattr(run, "_open_url", lambda url: calls.append(url) or True)
    assert run._show_existing("http://127.0.0.1:1/boot", "browser", state) is True
    assert calls == ["http://127.0.0.1:1/boot"]


def test_show_existing_headless_prints(monkeypatch, capsys):
    state = SimpleNamespace(logger=WindowLogger())
    assert run._show_existing("http://127.0.0.1:1/boot", "headless", state) is True
    assert capsys.readouterr().out.strip() == "http://127.0.0.1:1/boot"


def test_window_session_falls_back_to_browser(monkeypatch):
    state = SimpleNamespace(shutdown_event=threading.Event(), logger=WindowLogger())
    srv = SimpleNamespace(serve_forever=lambda: None)
    calls = []

    def unavailable(_url):
        state.shutdown_event.set()
        return False

    monkeypatch.setattr(run, "run_native_window", unavailable)
    monkeypatch.setattr(run, "_open_url", lambda url: calls.append(url) or True)
    run._run_window_session(state, srv, "http://127.0.0.1:1/boot", False)
    assert calls == ["http://127.0.0.1:1/boot"]
    assert any(event == "webview_unavailable" for event, _ in state.logger.events)


def test_window_close_does_not_stop_shared_server(monkeypatch):
    class RecordingEvent:
        def __init__(self):
            self.waited = False
            self.stopped = False

        def wait(self):
            self.waited = True

        def set(self):
            self.stopped = True

    event = RecordingEvent()
    state = SimpleNamespace(shutdown_event=event, logger=WindowLogger())
    srv = SimpleNamespace(serve_forever=lambda: None)
    monkeypatch.setattr(run, "run_native_window", lambda _url: True)

    run._run_window_session(state, srv, "http://127.0.0.1:1/boot", False)

    assert event.waited is True
    assert event.stopped is False


def test_replace_waits_for_lock(monkeypatch):
    token = object()
    attempts = iter([None, None, token])
    times = iter([0.0, 0.0, 0.2, 0.4, 0.6])
    monkeypatch.setattr(run, "_acquire_instance_lock", lambda: next(attempts))
    monkeypatch.setattr(run.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: None)
    assert run._acquire_lock_with_wait(10.0) is token
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_window.py -v`
Expected: FAIL for the new mode/session/lock tests.

- [x] **Step 3: Implement the helpers and refactor `run_web_ui`**

Implementation rules:
- `_launch_mode` returns `"headless"` if `no_browser`, else `"browser"` if `browser`, else `"window"`.
- `_show_existing` prints the URL for `headless`; for `window` tries `run_native_window(url)` and falls back to `_open_url(url)` with a `webview_unavailable` warning; for `browser` calls `_open_url(url)`. Return `True` when it printed/opened successfully.
- `_acquire_lock_with_wait` retries `_acquire_instance_lock()` every 0.1 seconds until `time.monotonic()` passes the deadline, returning the lock or `None`.
- `_run_window_session` starts `srv.serve_forever` in a daemon thread, prints `boot_url` when `print_url` is true, calls `run_native_window`, falls back to `_open_url` with a `webview_unavailable` warning, then waits on `state.shutdown_event`. Closing this window must not set `shutdown_event`; the heartbeat monitor owns final shutdown.
- `run_web_ui` creates `WebState(mode="web")` before lock handling. On `replace=True`, wait up to 10 seconds for the lock; if it never arrives, log `elevate_takeover_timeout` and return 1. Otherwise keep the existing 5-second existing-instance lookup: print the URL when `print_url` or headless, call `_show_existing` for window/browser, and return 0. After binding, write the lock, start the monitor, then:
  - `window`: print the boot URL when `print_url`; call `_run_window_session`.
  - `browser`: print when `print_url`; start the existing 0.6-second `_open_url` timer; call `srv.serve_forever`.
  - `headless`: print the boot URL; call `srv.serve_forever`.
- Preserve the existing `server_bind_failed` handling, `server_start` event, `_remove_lock`, and `_release_instance_lock` behavior.

- [x] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_window.py -v`
Expected: PASS.

---

### Task 3: CLI flags, detached launch, and elevation handoff

**Files:**
- Modify: `cli/parser.py`
- Modify: `cli/commands.py`
- Modify: `cli/launch.py`
- Modify: `cli/main.py`
- Modify: `web/api.py`
- Modify: `tests/test_launch.py`

**Interfaces:**
- Consumes: `run_web_ui(..., browser=..., print_url=..., replace=...)` from Task 2.
- Produces:
  - `gui_relaunch_argv(replace: bool = False) -> list[str]`
  - `gui --browser`, `gui --print-url`, `gui --replace` parsing
  - `_run_gui_process(extra: Sequence[str] = ()) -> int`

- [x] **Step 1: Update the failing tests**

Change the existing `test_cmd_gui_reports_launch` expectation to include the new keyword arguments:

```python
assert calls == [
    {"port": None, "no_browser": False, "browser": False, "print_url": False, "replace": False}
]
```

Add:

```python
def test_gui_relaunch_argv_can_request_replace():
    argv = gui_relaunch_argv(replace=True)
    assert argv[-2:] == [GUI_INTERNAL, "--replace"]


def test_gui_parser_accepts_browser_and_print_url():
    args = apply_defaults(build_parser().parse_args(["gui", "--browser", "--print-url"]))
    assert args.browser is True
    assert args.print_url is True


def test_cmd_gui_detached_child_opens_window(monkeypatch):
    url = "http://127.0.0.1:54321/__boot__?token=launch-token"
    popen_calls = []
    process = type("Process", (), {
        "stdout": io.StringIO(url + "\n"),
        "poll": lambda self: None,
        "terminate": lambda self: None,
        "wait": lambda self, **_kwargs: None,
    })()
    monkeypatch.setattr("cli.commands._stdin_is_tty", lambda _ctx: True)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: popen_calls.append(argv) or process)
    args = apply_defaults(build_parser().parse_args(["gui", "--browser"]))
    ctx = make_cli_ctx()

    assert cmd_gui(args, ctx) == exit_codes.OK, ctx.stderr.getvalue()
    assert "--print-url" in popen_calls[0]
    assert "--browser" in popen_calls[0]
    assert "window launched" in ctx.stderr.getvalue()


def test_main_hidden_gui_token_passes_replace(monkeypatch):
    calls = []
    monkeypatch.setattr("web.run.run_web_ui", lambda **kwargs: calls.append(kwargs) or 0)
    assert main([GUI_INTERNAL, "--replace"]) == 0
    assert calls == [{"replace": True}]
```

Update the existing detached-launch test so it no longer expects the parent to call `_open_url`; the child owns the window. Update `tests/test_web_api.py::test_elevate_requests_restart` to assert `"--replace" in calls[0]`.

- [x] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_launch.py -v`
Expected: FAIL for the new flags and kwargs.

- [x] **Step 3: Implement the plumbing**

Implementation rules:
- `cli/parser.py`: add `gui.add_argument("--browser", action="store_true", default=argparse.SUPPRESS, help="open the UI in the system browser instead of the native window")`, plus suppressed `--print-url` and `--replace` flags. Add `browser`, `print_url`, and `replace` to `apply_defaults`.
- `cli/launch.py`: `gui_relaunch_argv(replace=False)` appends `"--replace"` after `GUI_INTERNAL` when requested.
- `cli/main.py`: change `_run_gui_process` to accept the tokens after `GUI_INTERNAL`. Call `run_web_ui(replace=True)` only when `"--replace"` is present; otherwise call `run_web_ui()` unchanged so existing no-flag behavior and tests stay intact.
- `cli/commands.py` `cmd_gui`: read `browser`, `print_url`, and `replace` from args. For an interactive non-JSON launch that is not `--no-browser`, spawn the detached child with `gui --print-url` (frozen) or `-m cli gui --print-url` (source), plus `--browser` when requested, plus `--port` when present. Read the boot URL from the child, validate it, and report `NetScope window launched.` Do not call `_open_url` from the parent; remove the now-unused import. Forward `browser`, `print_url`, and `replace` to `run_web_ui` in the foreground path.
- `web/api.py` `api_elevate`: call `gui_relaunch_argv(replace=True)`.
- Keep UAC cancellation behavior: `relaunch_elevated` returning `False` must still log `elevate_cancelled`, return 409, and leave `shutdown_event` unset.

- [x] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_launch.py -v`
Expected: PASS.

---

### Task 4: Block CLI installer changes on Inno-managed installs

**Files:**
- Modify: `cli/installer.py`
- Modify: `tests/test_installer.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `INNO_MARKER_NAME = ".netscope-inno"` and an `InstallerError` guard in `install()` and `uninstall()`.

- [x] **Step 1: Write the failing tests**

Add to `tests/test_installer.py`:

```python
from cli.installer import INNO_MARKER_NAME, InstallerError


def test_install_refuses_inno_managed_install(tmp_path):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / INNO_MARKER_NAME).write_text("managed", encoding="utf-8")
    with pytest.raises(InstallerError, match="Settings > Apps"):
        install(source_exe=Path("missing.exe"), install_dir=install_dir)


def test_uninstall_refuses_inno_managed_install(tmp_path):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / INNO_MARKER_NAME).write_text("managed", encoding="utf-8")
    with pytest.raises(InstallerError, match="Settings > Apps"):
        uninstall(install_dir=install_dir)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_installer.py -k inno -v`
Expected: FAIL because `INNO_MARKER_NAME` is undefined.

- [x] **Step 3: Implement the guard**

- Add `INNO_MARKER_NAME = ".netscope-inno"` beside `MARKER_NAME`.
- In `install()`, compute `target_dir` before resolving `source_exe`, then raise `InstallerError("NetScope is managed by the Windows installer. Use Settings > Apps to uninstall it.")` when `(target_dir / INNO_MARKER_NAME).is_file()`.
- Do the same at the start of `uninstall()`, before registry or filesystem changes.
- Do not treat `.netscope-inno` as a file owned by the CLI installer; `_is_our_install` and uninstall file removal continue to use only `APP_EXE_NAME` and `MARKER_NAME`.

- [x] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_installer.py -v`
Expected: PASS, including the existing install/uninstall tests.

---

### Task 5: Inno Setup script

**Files:**
- Create: `installer/NetScope.iss`
- Create: `tests/test_installer_script.py`

**Interfaces:**
- Consumes: `dist\NetScope.exe` from the existing PyInstaller build; version passed as `/DAppVersion=...`.
- Produces: `dist\installer\NetScope-Setup.exe` and `.netscope-inno` in the install directory.

- [x] **Step 1: Write the failing script-invariant tests**

```python
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
    assert "MB_YESNO" in SCRIPT
    assert "MB_DEFBUTTON1" in SCRIPT
    assert r"{localappdata}\NetScope" in SCRIPT
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_installer_script.py -v`
Expected: FAIL because `installer/NetScope.iss` does not exist.

- [x] **Step 3: Implement `installer/NetScope.iss`**

Required setup values:
- `#ifndef AppVersion` default `"0.0.0"`; `AppVersion={#AppVersion}`.
- `AppId={{8E6F1C2A-4B7D-4E3A-9C5F-2D1B7A6E8F04}`; `AppName=NetScope`; `AppPublisher=NetScope`; `DefaultDirName={localappdata}\Programs\NetScope`; `DefaultGroupName=NetScope`; `DisableProgramGroupPage=yes`; `PrivilegesRequired=lowest`; `ArchitecturesAllowed=x64`; `ArchitecturesInstallIn64BitMode=x64`; `OutputDir=..\dist\installer`; `OutputBaseFilename=NetScope-Setup`; `Compression=lzma2/max`; `SolidCompression=yes`; `WizardStyle=modern`; `ChangesEnvironment=yes`; `UninstallDisplayIcon={app}\NetScope.exe`.
- `[Files]` installs `..\dist\NetScope.exe` into `{app}` with `ignoreversion`.
- `[Tasks]` provides an unchecked `desktopicon` task using `{cm:CreateDesktopIcon}`.
- `[Icons]` creates `{autoprograms}\NetScope` and `{autodesktop}\NetScope` (task-gated), target `{app}\NetScope.exe`, working directory `{app}`.
- `[Registry]` writes `HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\NetScope.exe` default value `{app}\NetScope.exe` with `uninsdeletekey`.
- `[Registry]` appends `{app}` to `HKCU\Environment\Path` via `ValueData: "{olddata};{app}"`, `Flags: preservestringtype`, `Check: NeedsAddPath('{app}')`. `NeedsAddPath` must compare semicolon-delimited entries case-insensitively and return `False` when the directory is already present.
- `[Run]` offers `{app}\NetScope.exe` as a post-install launch with `nowait postinstall skipifsilent`.
- `[Code]` implements `NeedsAddPath(Param: string): Boolean`, `RemoveFromUserPath(const Dir: string)`, `CurStepChanged(CurStep: TSetupStep)`, and `CurUninstallStepChanged(CurUninstallStep: TUninstallStep)`.
- `CurStepChanged(ssPostInstall)` writes `{app}\.netscope-inno` containing `Managed by NetScope Setup`.
- `CurUninstallStepChanged(usUninstall)` removes only the `{app}` entry from `HKCU\Environment\Path` using `RegQueryStringValue`/`RegWriteExpandStringValue` and leaves unrelated entries untouched. `ChangesEnvironment=yes` broadcasts the environment change.
- `CurUninstallStepChanged(usPostUninstall)` prompts `Also remove NetScope logs, reports, and fix backups?` with `MsgBox(..., mbConfirmation, MB_YESNO or MB_DEFBUTTON1) = IDYES` and, on Yes, `DelTree(ExpandConstant('{localappdata}\NetScope'), True, True, True)`.
- Do not write `HKLM`, do not delete the whole PATH value, and do not call `netscope install`.

- [x] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_installer_script.py -v`
Expected: PASS.

---

### Task 6: Installer build script, smoke test, and CI artifact

**Files:**
- Create: `scripts/build_installer.ps1`
- Create: `scripts/installer_smoke.py`
- Modify: `tests/test_installer_script.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `installer/NetScope.iss`, `dist\NetScope.exe`, and `config.APP_VERSION`.
- Produces: `dist\installer\NetScope-Setup.exe`; `scripts/installer_smoke.py --installer PATH` exits 0 only after install/launch/uninstall checks pass.

- [x] **Step 1: Write the failing tests**

Add to `tests/test_installer_script.py`:

```python
BUILD = Path("scripts/build_installer.ps1").read_text(encoding="utf-8")
SMOKE = Path("scripts/installer_smoke.py").read_text(encoding="utf-8")


def test_build_script_finds_iscc_and_targets_installer():
    assert "ISCC.exe" in BUILD
    assert r"installer\NetScope.iss" in BUILD
    assert r"dist\installer" in BUILD
    assert "/DAppVersion=" in BUILD


def test_installer_smoke_uses_silent_install_and_uninstall():
    assert "/VERYSILENT" in SMOKE
    assert "/SUPPRESSMSGBOXES" in SMOKE
    assert "unins000.exe" in SMOKE
    assert "App Paths" in SMOKE
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_installer_script.py -v`
Expected: FAIL because the build and smoke scripts do not exist.

- [x] **Step 3: Implement `scripts/build_installer.ps1`**

- `param([string]$Version = "")`; derive the repo root from `$PSScriptRoot` so the script works from any directory.
- Resolve the version with `$repo\.venv\Scripts\python.exe -c "import config; print(config.APP_VERSION)"` when `-Version` is empty.
- Find `ISCC.exe` with `Get-Command ISCC.exe -ErrorAction SilentlyContinue`, then check `$env:ProgramFiles(x86)\Inno Setup 6`, `$env:ProgramFiles\Inno Setup 6`, and `$env:ProgramFiles\Inno Setup 7`.
- Throw `Inno Setup (ISCC.exe) not found. Install Inno Setup 6 or 7.` when absent.
- Run `& $iscc "/DAppVersion=$Version" "installer\NetScope.iss"`; fail on non-zero exit.
- Verify `dist\installer\NetScope-Setup.exe` exists and print its size.

- [x] **Step 4: Implement `scripts/installer_smoke.py`**

- Args: `--installer` (default `dist\installer\NetScope-Setup.exe`), `--install-dir` (default `%LOCALAPPDATA%\Programs\NetScope`).
- Run the installer with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=<install-dir>`; require exit code 0.
- Assert `NetScope.exe` exists, the Start Menu shortcut `%APPDATA%\Microsoft\Windows\Start Menu\Programs\NetScope.lnk` exists, `HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\NetScope.exe` exists, and `HKCU\Environment\Path` contains the install directory.
- Run `NetScope.exe --version`; require stdout to start with `NetScope `.
- Run `<install-dir>\unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`; require exit code 0.
- Wait up to 10 seconds for the install directory, App Paths key, PATH entry, and `%LOCALAPPDATA%\NetScope` to disappear. Fail with the remaining artifact listed. (`/SUPPRESSMSGBOXES` takes the data-removal prompt's Yes default; the keep-data opt-out is covered by the manual checklist.)
- Never touch paths outside the install directory and `%LOCALAPPDATA%\NetScope`; the script is for disposable CI profiles.

- [x] **Step 5: Update CI**

In the `build` job:
- After the PyInstaller build and frozen smoke, install Inno Setup when `ISCC.exe` is missing: `choco install innosetup --no-progress -y`.
- Run `.\scripts\build_installer.ps1`.
- Run `.\.venv\Scripts\python.exe scripts\installer_smoke.py --installer dist\installer\NetScope-Setup.exe`.
- Replace the raw `NetScope-windows-x64` artifact upload with `NetScope-Setup` uploading `dist/installer/NetScope-Setup.exe`. Keep the raw exe only inside the CI workspace for frozen checks.

- [x] **Step 6: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_installer_script.py -v`
Expected: PASS.

Run: `.\.venv\Scripts\python.exe scripts/installer_smoke.py --help`
Expected: usage text and exit 0.

---

### Task 7: PyInstaller packaging for pywebview

**Files:**
- Modify: `NetScope.spec`
- Modify: `tests/test_frozen.py` or `tests/test_installer_script.py`

**Interfaces:**
- Consumes: `pywebview`, `pythonnet`, `clr_loader` installed by Task 1.
- Produces: a one-file `dist\NetScope.exe` that imports the edgechromium backend when the window path runs.

- [x] **Step 1: Write the failing packaging test**

Add to `tests/test_installer_script.py`:

```python
SPEC = Path("NetScope.spec").read_text(encoding="utf-8")


def test_spec_collects_webview_runtime():
    assert 'collect_all("webview")' in SPEC
    assert 'collect_all("pythonnet")' in SPEC
    assert 'collect_all("clr_loader")' in SPEC
    assert "webview.platforms.edgechromium" in SPEC
    assert '"clr"' in SPEC
    assert '"Python.Runtime"' in SPEC
```

- [x] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_installer_script.py -k spec -v`
Expected: FAIL because the collections are missing.

- [x] **Step 3: Update `NetScope.spec`**

- Import `collect_all` from `PyInstaller.utils.hooks`.
- Collect `webview`, `pythonnet`, and `clr_loader`; append their datas, binaries, and hidden imports to the existing `datas`, `binaries`, and `hiddenimports`.
- Add `webview.platforms.edgechromium`, `webview.platforms.winforms`, `clr`, and `Python.Runtime` to `hiddenimports`.
- Exclude non-Windows GUI backends that are safe to name (`webview.platforms.gtk`, `webview.platforms.qt`, `webview.platforms.cocoa`).
- Keep `console=True`, one-file mode, UPX off, and the existing web template/static/fix catalog datas.

- [x] **Step 4: Run test and build**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_installer_script.py -k spec -v`
Expected: PASS.

Run: `.\scripts\build.ps1 -Clean`
Expected: `dist\NetScope.exe` built; record the size.

Run: `.\.venv\Scripts\python.exe scripts\frozen_smoke.py --exe dist\NetScope.exe`
Expected: 9/9 checks pass. If the one-file loader cannot load WebView2/pythonnet, stop and report; the documented fallback is an onedir payload inside the installer, which is a separate change.

---

### Task 8: Documentation and close-out notes

**Files:**
- Modify: `README.md`
- Modify: `docs/manual-test-checklist.md`
- Modify: `docs/phaseDE-report.md`
- Modify: `docs/phaseE-deliverables.md`
- Modify: `AGENTS.md`
- Modify: `task.md`

- [x] **Step 1: Update `README.md`**

Document:
- Install with `NetScope-Setup.exe`; per-user, no admin, installs to `%LOCALAPPDATA%\Programs\NetScope`.
- WebView2 runtime requirement; if missing/unavailable NetScope falls back to the browser and logs `webview_unavailable`.
- Shortcut/default launch opens the native window; `netscope gui --browser` and `--no-browser` remain.
- Uninstall via Settings > Apps; default removes `%LOCALAPPDATA%\NetScope`, with an opt-out to keep logs/reports/backups.
- Build flow: `scripts\build.ps1`, `scripts\build_installer.ps1`; Inno Setup 6/7 required.
- `netscope install` remains for portable/source installs and refuses Inno-managed installs.

- [x] **Step 2: Update the manual checklist**

Add installer/window items: install silently and interactively, first-run window, second launch reuses the server, Start Menu/desktop shortcuts, `netscope --version` in a new terminal, elevation handoff (`/api/elevate`), uninstall default data removal, uninstall opt-out keeps data, and WebView2-missing browser fallback.

- [x] **Step 3: Update reports and agent notes**

- `docs/phaseDE-report.md`: add the installer artifact, pywebview window, Inno flow, CI installer job, and the one-file console-flash tradeoff.
- `docs/phaseE-deliverables.md`: add `dist\installer\NetScope-Setup.exe` and the manual installer checks.
- `docs/superpowers/specs/2026-11-15-desktop-installer-design.md`: change `Status: proposed` to `Status: approved (2026-11-15)`.
- `AGENTS.md`: update status, launch modes, packaging/installer, CI artifact, and remaining manual work.
- `task.md`: append a dated session note with the implemented installer/window changes and verification results.

- [x] **Step 4: Verify documentation**

Run: `git diff --check`
Expected: no whitespace errors.

---

### Task 9: Full verification

**Files:**
- No new files; update `task.md`/`AGENTS.md` only with final measured results.

- [x] **Step 1: Run the Python suite**

Run: `.\.venv\Scripts\python.exe -m pytest`
Expected: all tests pass; record passed/skipped counts.

- [x] **Step 2: Run the coverage gate**

Run: `.\.venv\Scripts\python.exe -m pytest --cov=core --cov=fixes --cov=powershell --cov-fail-under=80`
Expected: coverage at or above 80%.

- [x] **Step 3: Check JavaScript**

Run: `Get-ChildItem web\static\js\*.js | ForEach-Object { node --check $_.FullName }`
Expected: no syntax errors.

- [x] **Step 4: Build and smoke the frozen app**

Run: `.\scripts\build.ps1 -Clean`
Run: `.\.venv\Scripts\python.exe scripts\frozen_smoke.py --exe dist\NetScope.exe`
Expected: build succeeds; frozen smoke 9/9.

- [x] **Step 5: Build and smoke the installer**

Requires Inno Setup 6/7. Run:

```powershell
.\scripts\build_installer.ps1
.\.venv\Scripts\python.exe scripts\installer_smoke.py --installer dist\installer\NetScope-Setup.exe
```

Expected: `dist\installer\NetScope-Setup.exe` exists; install/CLI/uninstall smoke passes; the actual window is covered by the manual VM review.

- [x] **Step 6: Re-run the browser smoke**

Run: `.\.venv\Scripts\python.exe scripts\browser_smoke.py --screenshots`
Expected: smoke passes and screenshots are written under `artifacts/browser-smoke`.

- [x] **Step 7: Record final state**

Update `task.md` Notes and the status paragraph in `AGENTS.md` with the measured suite count, coverage, exe/installer sizes, and any remaining manual checks. Run `git status --short` and `git diff --check`. Do not commit or push unless the user explicitly asks.
