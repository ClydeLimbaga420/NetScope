# NetScope desktop window + per-user installer design

Date: 2026-11-15
Status: approved
Branch: `phasec`

## Intent

Distribute NetScope as a normal Windows desktop application instead of a raw
`NetScope.exe`. The installer creates the app under the user's profile, adds
Start Menu (and optional desktop) shortcuts, registers an uninstaller, and
puts `NetScope` on the user PATH. Opening the shortcut starts a NetScope-owned
window (WebView2), not a browser tab or an Edge `--app` window. The CLI keeps
working from any terminal via `netscope`.

## Why

The current build is a console-subsystem executable. `netscope gui` finds
Edge/Chrome and opens `--app=...`, falling back to the default browser. The
existing `netscope install` only copies the exe and edits HKCU. There is no
installer artifact, no Apps & Features entry, and no app-owned window.

## Goals

- Produce `NetScope-Setup.exe`, a per-user installer requiring no elevation.
- Install to `%LOCALAPPDATA%\Programs\NetScope`.
- Create a Start Menu shortcut and an optional desktop shortcut.
- Register a per-user uninstaller in Apps & Features.
- Add the install directory to the user PATH; `netscope` works in a new terminal.
- Shortcut/default launch opens a native WebView2 window owned by NetScope.
- Keep one server per user; a second launch opens a window to the existing server.
- Keep `netscope`, `netscope diagnose`, `netscope gui --no-browser`, `__gui__`,
  the JSON API, the security model, and offline assets working.
- Clean uninstall by default: remove logs, reports, and fix backups along with
  the app, with an opt-out to keep them.
- Keep the CLI installer usable for standalone/source installs, but never let it
  fight an Inno-managed install.

## Non-goals

- Auto-update.
- Code signing (the installer is unsigned for now).
- Machine-wide/all-users installation or MSI.
- Replacing the Flask/Werkzeug backend or rewriting the UI in Electron.
- Changing detection/fix logic or moving business logic into `web/` or the
  installer.

## Anti-goals

- Shipping a browser tab or Edge `--app` window as the primary experience.
- Requiring admin rights or writing machine-wide registry keys.
- Overwriting the user PATH wholesale.
- Bundling a fixed WebView2 runtime (~150 MB) by default.
- Making the CLI depend on the GUI.

## Approaches considered

1. **pywebview + WebView2 + Inno Setup (chosen).** Same Python backend, a real
   app window, small installer, no Node toolchain. Adds pywebview/pythonnet and
   a WebView2 runtime dependency.
2. **Electron wrapper.** True Chromium shell, but adds Node/Electron tooling and
   roughly 100–200 MB, plus duplicate packaging. Rejected as overkill.
3. **Edge `--app` shortcut.** No new dependency, but still an Edge process and
   not an app-owned window. Rejected because it misses the requested behaviour.

## Design

### Launch modes

`web/run.py` gains explicit modes:

- `window` (default for `gui` and no-arg shortcut launches): start the server in
  a daemon thread, then run pywebview on the main thread.
- `browser`: current Edge/Chrome `--app` behaviour, then default browser.
- `headless`: current `--no-browser` behaviour; server only, boot URL printed.

CLI changes:

- `netscope gui` / `NetScope.exe` with no args and an owned console: detached
  child launches `window` mode.
- `netscope gui --browser`: force the existing browser path.
- `netscope gui --no-browser`: unchanged headless server.
- `netscope gui` in a shared terminal still detaches and returns.

`__gui__` continues to be the in-process entry point.

### Native window

New `web/window.py`:

- `webview2_available()` checks the WebView2 runtime registry keys
  (`HKLM`/`HKCU` `...\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`,
  `pv > 0.0.0.0`).
- `run_native_window(boot_url)` creates a 1280×860 window (minimum 900×600),
  title “NetScope”, loads the boot URL, and calls
  `webview.start(gui="edgechromium", debug=False)`.
- Closing a window does **not** set `shutdown_event`. Multiple windows can share
  one server, and a window close must not kill the others. The existing
  heartbeat timeout stops the server after the last window goes away.
- If pywebview is unavailable or WebView2 is missing, return `False` so the
  caller falls back to browser mode and logs `webview_unavailable`.

The server remains bound to `127.0.0.1`; the window loads the same boot-token
URL, and all CSP/session rules stay unchanged.

### Single instance

The existing lock/port-file/health check stays. If another instance owns the
lock, the new process resolves the boot URL, opens a window (or prints the URL
in headless mode), and exits after the window closes. Multiple windows may
share one server; closing the last window lets the existing heartbeat timeout
stop the server. No new IPC protocol.

### Elevation handoff

`/api/elevate` still calls `ShellExecuteW(..., "runas", ...)`, but the relaunch
gets a `--replace` flag. The old process stops accepting work, sets its
shutdown event, and exits. The elevated process waits up to 10 seconds for the
old lock to disappear and then acquires it and starts its own server/window.
If the old server is still alive after the deadline, the elevated process logs
`elevate_takeover_timeout` and exits instead of opening a window against a
dying server. Cancelling UAC leaves the original server untouched.

### Installer

`installer/NetScope.iss` (Inno Setup 6/7):

- `AppId` fixed GUID; `AppName=NetScope`; version from `config.APP_VERSION`
  passed as `/DAppVersion=...`.
- `PrivilegesRequired=lowest`; `DefaultDirName={localappdata}\Programs\NetScope`.
- Installs `NetScope.exe` from `dist`.
- `[Icons]` Start Menu shortcut; optional desktop shortcut via a task.
- `[Registry]` App Paths entry (`uninsdeletekey`).
- `[Code]` helpers append/remove only the NetScope entry in
  `HKCU\Environment\Path`, preserving the existing value type, and broadcast
  `WM_SETTINGCHANGE`. Never rewrite unrelated entries.
- Uninstaller removes shortcuts, App Paths, PATH entry, and the app directory.
  It also removes `%LOCALAPPDATA%\NetScope` (logs/reports/backups) by default
  for a clean uninstall; the uninstaller asks once and defaults to Yes. Users
  can opt out if they want to keep diagnostic history.
- The installer writes a `.netscope-inno` marker in the install directory.
  `netscope install`/`uninstall` detect it and refuse to touch an Inno-managed
  install, directing the user to Settings → Apps. The CLI installer remains for
  portable/source installs.
- The installer does not call `netscope install`; Inno owns the install layout.

The payload stays a one-file console-subsystem executable, so the shortcut
still flashes a console briefly before the window appears. This is the same
documented tradeoff as today; a separate windowless launcher is out of scope
for this change.

`scripts/build_installer.ps1`:

- Finds `ISCC.exe` on PATH or under `Program Files (x86)\Inno Setup 6`,
  `Program Files\Inno Setup 6`, or `Program Files\Inno Setup 7`.
- Runs `ISCC.exe /DAppVersion=<version> installer\NetScope.iss`.
- Output: `dist\installer\NetScope-Setup.exe`.
- Fails with a clear message if Inno Setup is not installed.

CI installs Inno Setup with Chocolatey if `ISCC.exe` is absent, builds the app,
builds the installer, runs a silent install/uninstall smoke test, and uploads
`NetScope-Setup.exe` instead of the raw exe.

### Packaging

`NetScope.spec` adds `collect_all("webview")`, `collect_all("pythonnet")`, and
`collect_all("clr_loader")`, keeps `webview.platforms.edgechromium` and
`webview.platforms.winforms`, and excludes non-Windows backends (GTK, Qt,
Cocoa). The one-file build stays the payload. If frozen one-file loading of the
WebView2 loader proves unreliable, the documented fallback is an onedir payload
inside the installer (same layout, installer copies the folder).

### Version and identity

- App version comes from `config.APP_VERSION`; no duplicate literal.
- `AppId` is a stable GUID owned by NetScope.
- No icon is introduced in this change; the existing favicon is not reused as
  the executable icon unless a suitable `.ico` is added later.

## Files touched

- `web/window.py` (new): WebView2 detection and pywebview host.
- `web/run.py`: launch modes, server thread/window lifecycle, fallback,
  `--replace` lock takeover.
- `cli/commands.py`, `cli/parser.py`: `--browser`, `--replace`, mode plumbing.
- `cli/installer.py`: refuse to modify an Inno-managed install.
- `web/api.py`: elevation relaunch passes `--replace`.
- `cli/launch.py`: detached launch for window mode.
- `pyproject.toml` / `requirements.txt`: pywebview dependency.
- `NetScope.spec`: collect pywebview/pythonnet/clr_loader.
- `installer/NetScope.iss` (new): Inno Setup script.
- `scripts/build_installer.ps1` (new): installer build.
- `.github/workflows/ci.yml`: installer build + silent install smoke + artifact.
- `scripts/frozen_smoke.py` / `tests/test_frozen.py`: new build path if payload
  layout changes.
- `tests/test_launch.py` / new `tests/test_window.py` /
  `tests/test_installer_script.py`: window selection, fallback, installer script
  invariants.
- `README.md`, `docs/manual-test-checklist.md`, `docs/phaseDE-report.md`,
  `AGENTS.md`, `task.md`: distribution, WebView2 requirement, installer flows.

## Testing

- Unit: WebView2 detection with a fake registry; pywebview unavailable/available;
  window close does not stop a shared server; server starts before window;
  browser/headless modes still work; single-instance opens a window to the
  existing URL; `--browser`, `--no-browser`, and `--replace` parsing; Inno
  marker blocks CLI install/uninstall.
- Installer script invariants: `PrivilegesRequired=lowest`, localappdata default,
  stable AppId, Start Menu/desktop shortcuts, App Paths, PATH helper, uninstall
  entries, data-removal prompt, no machine-wide keys.
- Build: frozen smoke still covers headless boot/dashboard/API/shutdown. A
  `--window` smoke runs only where a WebView2 runtime and desktop are available;
  CI uses headless checks plus the silent installer test.
- Installer smoke on CI: silent install into a temp/CI profile, assert
  `NetScope.exe` and shortcut exist, `NetScope.exe --version` runs, `netscope`
  resolves on a refreshed PATH, then silent uninstall and assert cleanup.
- Manual Windows 10/11 VM: install, first-run WebView2 window, second launch,
  elevation handoff, Start Menu/desktop shortcuts, uninstall, data-removal
  prompt, CLI on PATH.

## Open items

- Code signing certificate.
- Auto-update channel.
- Whether to ship the WebView2 Evergreen bootstrapper for machines without the
  runtime (current plan: detect and fall back to browser mode).
- Visual review of the native window on high-DPI displays.
