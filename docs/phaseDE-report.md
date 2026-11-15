# Phase D/E report: launch, packaging, installer, CI

Date: 2026-11-15
Branch: `phasec`
Status: Phase D implementation complete; Phase E documentation/CI complete
except browser E2E and a real Windows 10 VM run. Nothing has been pushed.

Deliverables index: `docs/phaseE-deliverables.md`.

## Branch and merge state

- `main` was merged into `phasec` as a fast-forward: `49db262 -> cbb69b7`.
- Commit `d1c610d` ("add mit license, bump version to 0.3.0") added `LICENSE`
  and updated `pyproject.toml` metadata.
- The packaging, installer, CI, docs, and test changes in this report are in the
  working tree and are not committed yet.
- `LICENSE` is standard MIT with a blank author/copyright-holder line
  (`Copyright (c) 2026`); add the desired name before publishing if required.
- `pyproject.toml` version is `0.3.0`, license metadata is MIT, and the removed
  `gui*` package is no longer listed.

## tkinter removal

- Deleted the `gui/` package (`app.py`, `dialogs.py`, `runtime.py`,
  `launch.py`, `__init__.py`, `__main__.py`).
- Moved `gui/launch.py` to `cli/launch.py`, keeping `GUI_INTERNAL`,
  `owns_console`, `detach_console`, `launch_detached_gui`, and
  `gui_relaunch_argv`.
- Moved `gui/runtime.py` to `web/runtime.py` and renamed `GuiRuntime` to
  `AppRuntime`; `build_runtime`, `runtime_from_context`, and `empty_catalog`
  are unchanged in behaviour.
- Updated imports in `cli/main.py`, `app.py`, `web/server.py`, and
  `web/api.py`.
- Deleted `tests/test_gui.py`; added `tests/test_launch.py` for the retained
  launch helpers (11 tests).

## Packaging

- `NetScope.spec`: PyInstaller one-file, console-subsystem build.
  - Bundles `web/templates`, `web/static`, and `fixes/fixes.json`.
  - Hidden imports cover Flask/Werkzeug/Jinja2, psutil, requests, the legacy
    modules used by status/devices, gateway repair, and every web module.
  - Excludes tkinter, PyQt5/PySide6, matplotlib, numpy, IPython, pytest, pip,
    setuptools, and wheel.
- `scripts/build.ps1`: uses `.venv\Scripts\python.exe` when present, supports
  `-Clean`, verifies PyInstaller is installed, and reports the exe size.
- `scripts/frozen_smoke.py`: isolated-`LOCALAPPDATA` frozen smoke test. It
  checks the boot URL, dashboard, bundled CSS, `/api/status`, shutdown, clean
  exit, quiet console, structured `source:web` logging, and port-lock removal
  (9 checks).
- `tests/test_frozen.py`: version and smoke checks, skipped unless
  `NETSCOPE_EXE` is set.
- `web/paths.py` already resolves bundled assets through `sys._MEIPASS`; the
  frozen smoke test proves the bundled paths work.

### Executable size

Current build: **13.8 MB** (`dist/NetScope.exe`, Python 3.14.7, PyInstaller
6.22.3, UPX disabled).

A comparable tkinter build was never produced in this checkout, so a numeric
"before" size does not exist. tkinter/Tcl/Tk is excluded from the Flask build;
the only honest claim is that the packaged runtime no longer contains tkinter,
not a measured reduction. Rebuild an older revision if a numeric comparison is
required for a release note.

## Installer

`cli/installer.py` implements a per-user install with no elevation:

- Copy to `%LOCALAPPDATA%\Programs\NetScope\NetScope.exe` and write
  `.netscope-install`.
- Add the install directory to `HKCU\Environment\Path`, preserving the raw
  value and `REG_EXPAND_SZ` type and avoiding duplicate entries.
- Register `HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\NetScope.exe`.
- Create `%APPDATA%\Microsoft\Windows\Start Menu\Programs\NetScope.lnk` through
  a static PowerShell `WScript.Shell` script (user paths passed as separate
  argv values).
- Broadcast `WM_SETTINGCHANGE` so new shells pick up PATH.

Uninstall removes the PATH entry, App Paths key, shortcut, and only the
NetScope exe/marker inside the install directory, then removes the directory if
it is empty. Unrelated files are preserved. `--purge` also removes
`%LOCALAPPDATA%\NetScope` (logs, reports, backups).

CLI wiring:

- `netscope install [--source FILE] [--dir DIR] [--no-shortcut]`
- `netscope uninstall [--dir DIR] [--purge]`
- Both support `--dry-run` and `--json`; non-interactive use requires `--yes`.
- Frozen builds install themselves (`sys.executable` when `sys.frozen`); source
  checkouts look for `dist/NetScope.exe`, `build/dist/NetScope.exe`, or
  `NETSCOPE_EXE`.

Tests: `tests/test_installer.py` covers install copy/PATH/App Paths/shortcut
marker, duplicate PATH entries, dry-run, custom directories, no-shortcut,
uninstall preservation, purge, missing source, and CLI confirmation/JSON paths
(24 focused tests with the launch tests).

## Launch and lifecycle

- Double-click/Win+R/Start Menu uses the owned-console path: detach the console,
  start the server, and open the app window.
- `netscope gui` from a terminal detaches, waits for a bounded boot URL, and
  opens the browser; `--no-browser --port N` runs in the foreground.
- No arguments in a terminal opens the `netscope>` shell.
- Single instance per user: OS lock plus atomically published port file, health
  verification before reuse, owner-checked cleanup.
- Heartbeat timeout is 120 s; idle shutdown is suppressed while a job or fix is
  active. `POST /api/shutdown` and Ctrl+C exit cleanly and remove the lock.
- Werkzeug/Flask startup banners are suppressed; request records are routed to
  structured NetScope logs. The frozen smoke test asserts both.
- Elevation status is exposed in the UI; `/api/elevate` requests the UAC
  relaunch and cancellation keeps the server alive (409).

## CI

`.github/workflows/ci.yml` runs on `windows-latest` when `main` is updated
(push or merge); it does not run on pull requests or feature-branch pushes:

- Tests on Python 3.11 and 3.14 with `pytest`, coverage over `core`, `fixes`,
  and `powershell`, `--cov-fail-under=80`, and a coverage XML artifact.
- Browser job (after tests): installs Playwright plus Chromium and runs
  `scripts/browser_smoke.py` (shell, session, CSS, stat layout, mobile drawer,
  Troubleshoot, shutdown). It captures dashboard/mobile/Troubleshoot
  screenshots, uploads them as an artifact, and prints a skip and exits 0 when
  no browser is available.
- Build job (after tests): installs PyInstaller, runs
  `scripts/build.ps1 -Clean`, runs `scripts/frozen_smoke.py`, runs
  `tests/test_frozen.py` with `NETSCOPE_EXE`, reports exe size in the job
  summary, and uploads `NetScope-windows-x64`.

## Verification run

| Check | Result |
| --- | --- |
| Full pytest suite (no exe env) | 259 passed, 2 skipped |
| Coverage (`core`, `fixes`, `powershell`) | 82% |
| Installer + launch tests | 24 passed |
| Frozen smoke test | 9/9 checks passed |
| Frozen pytest (`NETSCOPE_EXE`) | 2 passed |
| Playwright browser smoke | Passed (shell, session, CSS, stat layout, drawer, Troubleshoot, shutdown) |
| `NetScope.exe --version` | `NetScope 0.3.0` |
| `NetScope.exe --help` | All commands and exit codes listed |
| `NetScope.exe diagnose --json` | Valid JSON, exit code 2 on this host |
| `node --check` on web JS | Clean |

## Remaining open items- Screenshots are captured by the browser smoke, but human visual comparison
  across every page/theme and assistive-technology review remains manual.
- Manual checklist on a Windows 10 VM (`docs/manual-test-checklist.md`); the
  `[VERIFY]` repairs and Win10/Win11 differences are listed in
  `docs/known-unverified.md`.
- No remote CI run yet; the workflow has only been validated locally.
- The working tree still needs a commit (and the user has not requested a push).
