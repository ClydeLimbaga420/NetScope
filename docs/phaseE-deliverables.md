# Phase E deliverables index

This file collects the Phase E close-out artifacts. Detailed design history
stays in `docs/phaseA-web-ui.md` and `docs/phaseC-web-ui.md`; packaging and
validation details stay in `docs/phaseDE-report.md`.

## 1. Branch / merge report

- `phasec` is the working branch for this close-out.
- `main` was merged with a fast-forward: `49db262 -> cbb69b7`.
- `d1c610d` added the MIT `LICENSE` and bumped `pyproject.toml` to 0.3.0.
- `build` is at `7ae6f8b` (the Phase 6 Step 0 merge); `git log main..build` is
  empty, so no post-merge commits exist on it.
- `feature/web-ui` is at `2d92a22` and remains the prior web-work branch.
- `phasec` = `main` + `d1c610d` + the uncommitted packaging/installer/CI/docs
  changes in this workspace.
- `main` has no new commits from this work. Nothing has been pushed.

## 2. Existing GUI + design + engine summary and plan

- `docs/phaseA-web-ui.md`: branch roles, tkinter GUI inventory, main dashboard
  design audit, engine/fix/logging APIs, parity tables, and the approved plan.
- `docs/phaseC-web-ui.md`: design-file changelog, new design files, offline/CSP
  audit, and build-feature parity map.
- `AGENTS.md`: current architecture, run commands, check IDs, safety invariants,
  and the web UI component map.

## 3. Executable size

| Build | Size | Notes |
| --- | --- | --- |
| tkinter (before) | not built in this checkout | No comparable artifact existed; tkinter is excluded from the Flask build |
| Flask web UI (`dist/NetScope.exe`) | 13.8 MB | Phase D/E build; Python 3.14.7, PyInstaller 6.22.3, one file, UPX disabled |
| Desktop build (`dist/NetScope.exe`) | 16.1 MB | Phase 7; adds pywebview/WebView2 + pythonnet |
| Inno installer (`dist/installer/NetScope-Setup.exe`) | 17.8 MB | Per-user setup, Inno Setup 6.7.3 |

The tkinter code was removed before a packaged artifact was produced, so the
numeric before/after comparison is unavailable. The current build does not
include tkinter/Tcl/Tk. See `docs/phaseDE-report.md`.

## 4. Parity checklist and extra tables

The Phase A parity tables and the Phase C build-feature map are the source of
truth:

- tkinter screen/control -> web equivalent -> status (Phase A)
- main design elements with no build feature (Phase A/C)
- build features with no natural place in main's layout (Phase A/C)
- build-feature wiring status by area (Phase C)

`task.md` tracks the completed Phase C/D/E items. The browser smoke now covers
the served shell, session handshake, CSS, stat-card layout, mobile drawer,
Troubleshoot view, and shutdown; screenshots are written to
`artifacts/browser-smoke/` and uploaded by CI.

## 5. Web layer/templates/CSS/JS changes (vs `main`)

`main` already contains the Phase C design. On `phasec`, the remaining web
changes are wiring only:

| File | Change |
| --- | --- |
| `web/api.py` | Import `cli.launch` instead of the deleted `gui.launch` |
| `web/server.py` | Import `AppRuntime` from the moved `web.runtime` |
| `web/runtime.py` | Moved from `gui/runtime.py`; `GuiRuntime` renamed `AppRuntime` |
| `web/templates/*` | No diff vs `main`; design unchanged |
| `web/static/*` | No diff vs `main`; layout/assets unchanged |

Design changelog: `docs/phaseC-web-ui.md` (file/lines/reason and new design
files). New reusable partials from Phase C are `_page_header.html`,
`_status.html`, and `_toast.html`; engine components live in
`web-overrides.css` and `engine-ui.js`.

## 6. `git diff --stat` vs `main`

Tracked changes in the working tree (excluding new untracked files):

```
 .gitignore           |   5 +
 README.md            | 258 +++++++++++++++++++++++++++++++++++++++++++---
 app.py               |   2 +-
 cli/commands.py      |  83 +++++++++-
 cli/main.py          |   4 +-
 cli/parser.py        |  26 ++-
 pyproject.toml       |   5 +-
 task.md              |  57 ++++---
 tests/test_gui.py    | 455 ---------------------------------------------------
 tests/test_probes.py | 253 +++++++++++++++++++++++++++++++++++++++++++-
 web/api.py           |   4 +-
 web/server.py        |   8 +-
 12 files changed, 632 insertions(+), 528 deletions(-)
```

New files in this close-out:

`LICENSE`, `NetScope.spec`, `.github/workflows/ci.yml`,
`scripts/build.ps1`, `scripts/frozen_smoke.py`, `scripts/browser_smoke.py`,
`cli/installer.py`, `cli/launch.py`, `web/runtime.py`,
`docs/known-unverified.md`, `docs/manual-test-checklist.md`,
`docs/phaseDE-report.md`, `docs/phaseE-deliverables.md`,
`tests/test_installer.py`, `tests/test_launch.py`, `tests/test_frozen.py`.

`git diff --stat main feature/web-ui -- web/templates web/static` shows the
earlier design delta (10 files, +1523/-5288) that was resolved into the current
shared design. `git diff --stat main -- web/templates web/static` is empty on
`phasec`, confirming the design files match `main`.

## 7. Test suite and CI

- Full suite: 259 passed, 2 skipped (frozen tests skip without
  `NETSCOPE_EXE`).
- Coverage over `core`, `fixes`, `powershell`: 82% (threshold 80%).
- Installer/launch: 24 passed. Frozen smoke: 9 checks. Frozen pytest: 2 passed.
- Browser smoke: passed, with screenshots.
- `node --check` clean for all web JS.
- CI: `.github/workflows/ci.yml` (runs only on pushes/merges to `main`; tests on
  3.11/3.14, coverage gate, Playwright browser job + screenshots artifact,
  PyInstaller build + frozen smoke + uploaded exe).

## 8. Build / launch / installer updates

- `NetScope.spec`, `scripts/build.ps1`, `scripts/frozen_smoke.py`.
- `cli/launch.py` owns console detection/detach/relaunch; `cli/main.py`
  dispatches `__gui__`, no-args, and `gui`.
- `cli/installer.py` + `cli/parser.py` + `cli/commands.py` implement
  `install`/`uninstall` with PATH, App Paths, Start Menu, marker, dry-run, JSON,
  and `--purge`.
- `web/runtime.py` hosts the shared runtime after tkinter removal.
- `pyproject.toml` no longer lists `gui*`; the `netscope` console script stays.

## 9. Manual test checklist

`docs/manual-test-checklist.md` covers packaging, launch/single-instance,
connectivity failure simulation, fix safety, unresolved ranking, CLI/shell,
web UI, installer lifecycle, and the legacy dashboard.

`docs/known-unverified.md` lists the `[VERIFY]` repairs, Win10/Win11
differences, and unverified paths.

## 10. Final branch checks (local)

```
git branch --show-current        -> phasec
git rev-parse --short main       -> cbb69b7
git rev-parse --short build      -> 7ae6f8b
git rev-parse --short feature/web-ui -> 2d92a22
git log --oneline main..HEAD     -> d1c610d add mit license, bump version to 0.3.0
git log --oneline main..build    -> (empty)
git diff --stat main -- web/templates web/static -> (empty)
```

The close-out work is still uncommitted. Commit it only when requested; do not
push without an explicit request.

## 11. Desktop installer follow-up (2026-11-16)

- Design/plan live in `docs/superpowers/`:
  `2026-11-15-desktop-installer-design.md` (approved) and
  `2026-11-15-desktop-installer.md` (9-task plan).
- New: `web/window.py`, `installer/NetScope.iss`,
  `scripts/build_installer.ps1`, `scripts/installer_smoke.py`,
  `tests/test_installer_script.py`.
- Updated: `web/run.py`, `cli/parser.py`, `cli/launch.py`, `cli/main.py`,
  `cli/commands.py`, `web/api.py`, `cli/installer.py`, `NetScope.spec`,
  `.github/workflows/ci.yml`, README, manual checklist, and `AGENTS.md`.
- The Windows installer writes `dist\installer\NetScope-Setup.exe` and is built
  from the frozen exe. It is per-user, adds PATH/App Paths/Start Menu entries,
  ships an uninstaller, handles WebView2, and marks the install
  `.netscope-inno`.
- Verification: 280 passed, 2 skipped; frozen smoke 9/9; Inno 6.7.3 compile;
  silent installer smoke passed (install, version, shortcut, App Paths, PATH,
  uninstall, default data removal). Rebuilt exe 16.1 MB; setup 17.8 MB.
- The desktop-installer changes are uncommitted on `phasec`. The Windows 10 VM
  checklist and human UI/window review are still open.
