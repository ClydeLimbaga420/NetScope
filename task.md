# NetScope Rebuild — Task Checklist

Source of truth: `prompt.txt`. Work phase by phase; only start a phase when the
previous one is complete and tested. Update `AGENTS.md` at the end of every
phase and keep the **Notes** section below current for the next session.

Existing code that must keep working: the Flask dashboard (`app.py`,
`modules/*`, `templates/*`, `static/*`).

---

## Phase 1 — Core engine, command runner, PowerShell layer, logging, tests

### 1.1 Project structure
- [x] Create `core/` package (models, engine, checks, runner, logging, snapshot)
- [x] Create `powershell/` package (static scripts + parameterised execution)
- [x] Keep existing `modules/` and Flask app untouched until the CLI phase
- [x] Add `tests/` package with fixtures and `pytest.ini`

### 1.2 Models
- [x] `Status` (pass/warn/fail/skip/error) and `Layer` enums
- [x] `CheckResult` dataclass: id, layer, status, title, message, cause,
      evidence, fix_ids, `to_dict()`
- [x] `DiagnosticReport`: session id, timestamps, results, first failing layer,
      overall status, exit code, `to_dict()`
- [x] Pipeline layer order: adapter → services → ip → gateway → lan → dns →
      internet → stack

### 1.3 Command execution layer (single mockable interface)
- [x] `CommandResult` / `CommandRunner` interface
- [x] `SubprocessRunner`: argument lists only, `shell=False`, timeouts,
      `CREATE_NO_WINDOW`, encoding-safe capture, OSError/timeout handling
- [x] Native command helpers (`ping`, `arp`, `route`, etc.) with defensive
      parsing utilities
- [x] Every command logged with args, duration, exit code, stdout, stderr

### 1.4 PowerShell layer
- [x] Static, catalog-only PowerShell scripts (no user interpolation)
- [x] `PowerShellLayer` executes scripts from temp `.ps1` files via `-File`,
      user values passed as separate `-ParamName value` arguments
- [x] JSON parsing of cmdlet output; single-object/array normalisation
- [x] Batched query execution (one PowerShell startup per diagnosis)
- [x] Constrained Language Mode detection + native fallback signal
- [x] Strict parameter validation (adapter names, hosts, ports, profile names)

### 1.5 Logging
- [x] JSON-lines logging to `%LOCALAPPDATA%\NetScope\logs\` with rotation
- [x] Session id on every record; event name + fields
- [x] Helpers for CLI/GUI actions, commands, checks, confirmations, errors,
      Ctrl+C
- [x] Logging tests (fields present, rotation, no secrets)

### 1.6 Diagnostic checks (Phase 1 baseline)
- [x] Adapter: disabled, disconnected, no media, driver error, power saving,
      low link speed, virtual adapter winning metric
- [x] Services: WlanSvc, Dhcp, Dnscache, NlaSvc/netprofm, BFE, file sharing
- [x] IP config: APIPA, no gateway, duplicate address, static mismatch,
      default route missing, overlapping routes
- [x] Gateway: ping reachability + ARP/neighbour state
- [x] LAN: peer unreachable / ARP incomplete / Public profile / discovery rules
- [x] DNS: resolve failure while raw-IP ping works, hosts-file entries
- [x] Internet: public-IP ping, HTTP connecttest/captive portal, proxy checks,
      clock check
- [x] Stack: Winsock/TCP-IP evidence check (detect-only)
- [x] Every check returns structured data and suggested fix IDs (IDs may point
      to catalog entries added in Phase 3)

### 1.7 Engine
- [x] Build one snapshot (batched PowerShell) then run checks
- [x] Run full pipeline or selected layer(s)
- [x] Live progress callback after each check
- [x] First failing layer + overall status + exit codes (0/1/2)
- [x] Check exceptions are captured and reported, not crashed

### 1.8 Tests
- [x] Unit tests for parsers using recorded fixture outputs
- [x] Malformed/localised output cases
- [x] Runner tests: timeouts, missing commands, no `shell=True`
- [x] PowerShell tests: JSON, batching, parameter passing, injection rejection
- [x] Logging tests
- [x] Engine tests: mocked scenarios per failing layer
- [x] Safety test: no `shell=True` in the codebase
- [x] All tests pass on Windows (`pytest`)

### 1.9 Phase 1 close-out
- [x] Update `AGENTS.md`
- [x] Update Notes below

---

## Phase 2 — CLI (argparse + interactive shell)

### 2.1 Argument parsing and global flags
- [x] `netscope diagnose [--layer ...]`, `fix`, `info`, `logs`, `report`,
      `gui`, `install`, `uninstall`, `--version`
- [x] Built-in utilities: `ping`, `trace`, `dns`, `arp`, `routes`, `ports`,
      `mtu`
- [x] Global `--json`, `--no-color`, `--quiet`, `--verbose`, `--yes`,
      `--dry-run`, `--yes-i-understand-risk`
- [x] Documented exit codes (0/1/2/3/4/64) in `--help`

### 2.2 Output layer
- [x] Color/symbol renderer with NO_COLOR + piped/non-TTY fallback
- [x] Enable Windows VT processing via ctypes
- [x] stdout = results, stderr = progress/errors
- [x] Live progress lines/spinner; JSON mode emits one valid document
- [x] Never prompt when stdin is not a TTY unless `--yes`

### 2.3 Interactive shell
- [x] `netscope>` prompt, history, tab completion
- [x] Numbered beginner menu fallback
- [x] Shell commands mirror subcommands
- [x] Ctrl+C: kill children, log, restore terminal

### 2.4 Admin handling
- [x] Elevation detection up front
- [x] Offer UAC relaunch or print exact admin command

### 2.5 CLI tests
- [x] Parsing, every `--help`, exit codes, `--json` schema validation
- [x] No ANSI when piped/NO_COLOR
- [x] Non-TTY never prompts; Ctrl+C handling

### 2.6 Phase 2 close-out
- [x] Update `AGENTS.md`
- [x] Update Notes below

---

## Phase 3 — Fix catalog, fix flow, snapshot/rollback, if_unresolved

### 3.1 Catalog data
- [x] `fixes/fixes.json` with every seeded entry (ADP/SVC/IP/LAN/DNS/NET/VPN/
      WIFI/STK)
- [x] Fields: id, name, symptom, detection signal, commands (PS + native),
      explanation, admin, risk, reboot, snapshot, rollback, verification,
      ladder, if_unresolved
- [x] DETECT-ONLY flag; `[VERIFY]` flag on IP-08, LAN-10, DNS-04, DNS-05,
      NET-06, NET-08, NET-11
- [x] Catalog loader + validation (unique IDs, required fields, valid refs)

### 3.2 Fix executor
- [x] Confirmation required; `--yes`/`--dry-run`
- [x] Risk-H second confirmation (`--yes-i-understand-risk`)
- [x] Pre-fix snapshot, change summary, rollback support
- [x] Post-fix verification re-check; honest failure reporting
- [x] Fix ladder progression; stop when resolved
- [x] Report what changed and how to undo

### 3.3 If-unresolved engine
- [x] Only after ladder exhausted and re-check still fails
- [x] Ask/test "Does another device on the same network work?"
- [x] Rank this_device vs beyond_device from evidence + answer
- [x] Probabilistic wording, log everything, include in report
- [x] CLI print + exit code 2; GUI expandable panel

### 3.4 Catalog/flow tests
- [x] Catalog completeness/schema tests, no duplicate IDs, DETECT-ONLY has no
      commands, valid finding→fix mappings
- [x] Fix-flow tests (confirm/decline/dry-run/snapshot/rollback/re-check/admin/
      risk H)
- [x] If-unresolved tests (gating, ranking, wording, report/log inclusion)

### 3.5 Phase 3 close-out
- [x] Update `AGENTS.md`
- [x] Update Notes below

---

## Phase 4 — GUI (tkinter)

### 4.1 GUI shell
- [x] Main window: status, findings list, plain-language explanations
- [x] Each fix has "Proceed to Fix" + confirmation dialog with exact commands
- [x] Admin/risk/reboot labels; high-risk double confirmation
- [x] "Still not working? Likely causes" expandable panel
- [x] "View Logs", report export, diagnose button, layer selection
- [x] Same engine calls as CLI; no business logic in GUI

### 4.2 Dual-mode launch
- [x] Console-subsystem exe behaviour
- [x] `GetConsoleProcessList` detection: terminal → shell; own console →
      detach/hide and open GUI
- [x] `netscope gui` detaches so prompt returns
- [x] Avoid console flash; document launcher tradeoff (if needed)

### 4.3 GUI tests
- [x] Construct GUI headless-safe; fix buttons call engine functions
- [x] Skip gracefully on headless CI

### 4.4 Phase 4 close-out
- [x] Update `AGENTS.md`
- [x] Update Notes below

---

## Phase 5 — Packaging, installer, CI, docs

### 5.1 Packaging
- [ ] PyInstaller `--onefile` console-subsystem `netscope.exe` (or Nuitka if
      smaller)
- [ ] Report final exe size
- [ ] Verify `--version`, `diagnose --json`, `--help` from the exe

### 5.2 Installer
- [ ] `netscope install`: copy to `%LOCALAPPDATA%\Programs\NetScope`, add to
      user PATH, App Paths registry key, Start Menu shortcut, WM_SETTINGCHANGE
- [ ] `netscope uninstall`: remove all of the above safely
- [ ] Installer tests with mocked/temporary registry + PATH

### 5.3 CI
- [ ] GitHub Actions `windows-latest`: tests, coverage (80%+ core/fixes/
      PowerShell), build exe, run build tests

### 5.4 Documentation
- [ ] README: build, CLI reference, exit codes, `[VERIFY]` list, how to add
      checks/fixes/if_unresolved/subcommands, dual-mode explanation
- [ ] Manual test checklist for Windows VM failure simulation
- [ ] Known-unverified / Win10-vs-Win11 differences list

### 5.5 Phase 5 close-out
- [ ] Update `AGENTS.md`
- [ ] Update Notes below

---


## Phase 6 � Web UI replacement (tkinter ? local web UI)

Goal: replace the tkinter GUI with a local web UI served from inside
`netscope.exe` (Flask, Jinja2, vanilla HTML/CSS/JS) that uses **main's
design/layout** and **build's features** over the SAME engine/fix/logging
APIs as the CLI. No new engine/catalog/CLI/log-format behavior except what
is strictly required for the web front end (list any such change and why).

Branch/scope rules (binding): verify branches first; merge `main` into
`build` with `--no-ff` (safety tag, conflicts resolved by ownership: design
files = main wins, engine/catalog/fix/CLI/logging/installer/tests = build
wins), run tests/smoke, then do all web work on `feature/web-ui` from merged
build. **main receives no commits; build receives only the Step 0 merge.**
Do not redesign/restyle/rename/reorganize main's UI. Add only features that
exist in build; wire/trace every UI element to a main element or build
feature. Engine/catalog/CLI behavior and log formats stay unchanged unless
strictly required for web (document why).

### Phase A � Verification, merge, audit, plan, parity
- [x] Verify branches (`git branch -a`, logs, contents); confirm roles (main =
      design/layout + dashboard features incl. packet-loss/QOL; build = engine/
      CLI/fix/GUI/logging features). Flagged overlap on shared dashboard files.
- [x] Step 0: clean tree, tag `build-pre-merge` on build, `git merge --no-ff
      main` into build (real merge). Resolved conflicts by ownership; listed
      resolutions. main unchanged.
- [x] Post-merge checks: pytest, `netscope --version`, `netscope diagnose
      --json` (mocked CLI test) pass. Investigated real-run `diagnose --json`:
      produces valid JSON and correct exit code (1/WARN on this host), no code
      fix required.
- [x] Create `feature/web-ui` from merged build; all subsequent work there.
- [x] Summarize existing tkinter GUI, main's design (templates/static/JS), and
      engine/fix/logging public APIs.
- [ ] Full design audit: pages/regions/components/themes/animations/breakpoints
      and conflicts with security/offline rules (CDN/fonts, inline
      script/style/handlers, inline style attrs, eval/new Function,
      innerHTML/document.write with dynamic data, mock data, browser-only
      settings that must be CLI-shared).
- [ ] Build-features inventory (engine checks, fix catalog/flow/snapshot/
      rollback/unresolved, CLI utilities info/ping/trace/dns/arp/routes/ports/
      mtu/logs/report/monitor, logging, install/uninstall semantics) mapped to
      main's existing layout (TOOLS focus per decision).
- [ ] Produce parity tables: (1) every tkinter GUI screen/button/feature and
      every CLI-only build feature ? web equivalent + place in main's layout +
      status; (2) main design elements with no build feature behind them; (3)
      build features with no natural place in main's layout (flag, use closest
      existing pattern; ask before new nav/pages/regions).
- [ ] Confirm plan before large amounts of code (placement decisions for
      CLI-only tools inside TOOLS, legacy Troubleshoot `/api/diagnostics` vs
      engine/fix integration approach, any appearance-affecting conflicts).

### Phase B � Server, API, jobs/SSE, security (+ tests)
- [ ] `web/` package: `server.py`, `api.py`, `security.py`, `jobs.py`,
      `templates/`, `static/{css,js,img}`; app factory `create_app`, Blueprints
      (pages + `/api`), explicit template/static folders via resource-path
      helper (dev + PyInstaller `sys._MEIPASS`).
- [ ] Flask run: debug=False, reloader off, threaded=True, bound to 127.0.0.1;
      suppress dev-server banner in packaged exe; route Werkzeug request
      logging into NetScope log (not console).
- [ ] Background jobs for long ops (diagnose, fix, ping/trace, mtu, etc.) with
      job IDs; SSE `text/event-stream` progress/results (no buffering,
      keep-alive, disconnected client stops generator) + polling fallback;
      cancel kills child processes.
- [ ] Security (mandatory): bind 127.0.0.1 only; per-session random token
      exchanged to HttpOnly SameSite=Strict cookie, redirect to clean URL; all
      API requires cookie; all POST require custom header + JSON content type;
      Host allowlist (127.0.0.1/localhost:port) + Origin/Referer validation on
      POST; no CORS; strict CSP (`default-src 'self'`, no inline/eval/external,
      `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`,
      `Referrer-Policy: no-referrer`. Template autoescaping; JS renders via
      textContent/safe DOM only (command output/SSIDs/hostnames/names
      attacker-influenced).
- [ ] Server-side fix confirmation: `POST /api/fix/plan` ? exact commands,
      admin/risk/reboot, snapshot/rollback, single-use bound `confirmation_token`
      (expiring); `POST /api/fix/execute` requires valid token, Risk H requires
      `second_confirmation=true`, dry-run enforced server-side; only one fix at
      a time. API accepts only catalog fix IDs/built-in utility names (no
      command strings); params validated same as CLI, never concatenated.
- [ ] JSON API routes (build features only + web infra): `/api/status`,
      `/api/diagnose`, `/api/jobs/<id>`, `/api/jobs/<id>/events`,
      `/api/jobs/<id>/cancel`, `/api/findings`, `/api/fix/plan`,
      `/api/fix/execute`, `/api/fix/rollback`, `/api/unresolved/answer`,
      `/api/info`, `/api/tools/<name>` (ping,trace,dns,arp,routes,ports,mtu),
      `/api/logs`, `/api/logs/stream`, `/api/report`, `/api/open-log-folder`,
      `/api/ui-event`, `/api/heartbeat`, `/api/shutdown`, `/api/elevate`.
      Consistent error objects (code + plain message). JSON shapes aligned with
      engine/CLI `--json`.
- [ ] Logging (web): same module/JSON-lines/session semantics with `source:
      "web"`; log server start/stop+port, every API call/outcome, plan/confirm
      accepted|declined, every command (args/params/timestamps/exit/stdout/
      stderr/duration), snapshots/rollbacks, unresolved+isolation answer,
      UI-only actions, heartbeat loss/shutdown, security rejections, errors
      with tracebacks.
- [ ] Tests: API (Flask test client + real test server for SSE) success/error
      shapes aligned to engine; security; confirmation; injection (template+JS
      paths); jobs (ordered SSE, cancel kills children, disconnect safe, matches
      CLI `--json` for mocked scenarios).

### Phase C � Templates, wiring, CSP/offline fixes, feature integration
- [ ] Convert main's `index.html` to Jinja2 templates (shared base: header/nav/
      status chips/toast/footer) with identical markup/class structure/appearance;
      server-rendered shells, JS fills live data.
- [ ] Resolve security/offline conflicts with smallest identical-looking diffs:
      move inline scripts/styles/handlers to `static/` + `addEventListener`;
      bundle CDN assets/fonts/icons locally (Chart.js, Inter) or propose nearest
      alternative before changing; replace `innerHTML` with textContent/safe DOM
      for dynamic data preserving structure. Keep class names/CSS/layout/
      interactions/copy/order.
- [ ] Wire build features into main's existing layout/components only:
      Dashboard (run/layers/dry-run, live progress, summary); Findings+fixes
      (detail/evidence, Proceed-to-Fix modal with explanation+exact commands+
      snapshot/rollback+admin/risk/reboot+dry-run, Risk H typed confirm, live
      exec output/timings/exit + re-check, ladder/unresolved, fix history+
      rollback); Unresolved panel (Yes/No/Not sure isolation re-rank, on/off
      device ranked probable causes, next-check checklist, evidence); Network
      info cards/tables (adapters/routes/ARP/DNS/proxy/VPN/Wi-Fi, copy/refresh);
      TOOLS (ping/trace/dns/arp/routes/ports/mtu + info/logs/report surfaces as
      needed, validated streaming/cancel/copy-export) in existing TOOLS patterns;
      Settings/status (build-existing only, persisted in %LOCALAPPDATA%\NetScope
      shared with CLI). No new nav/pages/layout regions without asking.
- [ ] Main elements without build backing left as-is and listed; add only
      states/components main lacks (e.g. modal) in main's style in separate
      file(s) loaded after main CSS/JS.
- [ ] Changelog of every edit to main's design files (file/lines/reason) and
      list of every new design file.
- [ ] Tests: template render with mocked data + autoescape; referenced static
      assets exist; design-fidelity (screenshot compare small tolerance,
      computed styles of key elements match) and changelog/unchanged-main-CSS
      assertions where feasible.

### Phase D � Launch/lifecycle, packaging, build tests
- [ ] `netscope gui` / no-args from Win+R|Start|double-click start server+open UI;
      no-args in terminal still opens interactive CLI shell. `netscope gui
      --no-browser` and `--port N` (default random free). Open app-style window
      (Edge --app, Chrome --app, fallback default browser). Preserve hidden
      console on Win+R/Start and detach on `netscope gui`.
- [ ] Single instance per user (lock/port file in %LOCALAPPDATA%\NetScope) opens
      existing instance. Heartbeat (~few s); shutdown when no heartbeat ~20s and
      no job/fix running; "Quit NetScope" (POST /api/shutdown); Ctrl+C exits
      cleanly.
- [ ] Elevation: Administrator status chip, non-admin banner, "Restart as
      administrator" (UAC relaunch, exit old); disable/annotate admin-only
      fixes when not elevated.
- [ ] Bundle `templates/` and `static/` into exe (PyInstaller --add-data) via
      resource-path helper; exclude unused Flask/Werkzeug/Jinja2 extras; verify
      lightweight.
- [ ] Tests: lifecycle (heartbeat shutdown, no shutdown while job runs,
      single-instance, clean Ctrl+C, elevation/non-admin state); build tests
      (`netscope.exe gui --no-browser --port <p>` serves dashboard, a static
      CSS, `/api/status` from inside exe); report exe size (tkinter before vs
      Flask web UI after).

### Phase E � Remove tkinter, docs, CI, final reports
- [ ] Remove tkinter from project and exe only after parity checklist passes
      (all rows done/tested); delete tkinter code/imports.
- [ ] Update README (dev run, server security, API reference, adding
      page/route/static asset, exe bundling), Start Menu/shortcut behavior,
      install/uninstall steps.
- [ ] Update GitHub Actions `windows-latest`: run all web+core+fixes tests with
      coverage; include headless browser smoke (Playwright) skipped gracefully
      where unavailable.
- [ ] Deliverables complete: branch/merge report, existing GUI+design+engine
      summary & plan, exe size before/after, parity checklist (+ 2 extra
      tables), web layer/templates/CSS/JS changes file-by-file + design
      changelog + git diff --stat vs main, test suite + CI, build/launch/
      installer updates, manual test checklist (VM scenarios incl. unfixable ?
      unresolved panel).
- [ ] Final: confirm `git log main..feature/web-ui`, `git diff --stat` vs main
      for design files, `main` has no new commits, `build` has only Step 0
      merge commit.

---

## Notes

Session 1 (Phase 1):
- Environment: no `.venv` existed in this checkout; created `.venv` with
  Python 3.14.7 and installed Flask, psutil, pytest, pytest-cov. Dev deps are in
  `requirements-dev.txt`. Run tests with
  `.\.venv\Scripts\python.exe -m pytest` (62 passing).
- New packages: `core/` (engine, models, runner, snapshot, logging, checks)
  and `powershell/` (static scripts + parameterised executor). Existing
  `modules/` and Flask `app.py` are intentionally unchanged in Phase 1; the
  dashboard was smoke-tested with Flask's test client after config changes.
- Logging package is named `core/logging_config.py`, NOT a top-level `logging/`
  package, because a top-level `logging` package would shadow the stdlib.
- PowerShell scripts are executed from a temp `.ps1` file with `-File` and
  user values passed as separate arguments; scripts are never built by string
  interpolation.
- Check results already carry suggested fix IDs matching the spec
  (ADP-xx/SVC-xx/IP-xx/LAN-xx/DNS-xx/NET-xx/STK-xx); the catalog itself lands
  in Phase 3.
- Real-machine validation (Windows 11, Wi-Fi + disconnected Ethernet + Npcap +
  Wi-Fi Direct adapters) exposed false positives that were fixed: APIPA checks
  ignore virtual/disconnected/`Local Area Connection*`/Npcap aliases; PnP driver
  errors ignore Bluetooth/WAN Miniport/Kernel Debug/Wi-Fi Direct and only count
  codes 10/28/31/43; Winsock detection only looks at `Layered Service Provider`
  entries; the discovery firewall check treats a group as enabled when any
  inbound Allow rule is enabled.
- Expected real-machine warnings on this host: `NlaSvc` stopped/manual,
  `FDResPub`/`upnphost` stopped, and one sharing firewall group disabled. These
  are genuine warning states, not parser bugs.
- Keep the Flask dashboard working; do not delete `modules/` or SQLite
  scaffolding until a later phase explicitly replaces them.

Phase 1 close-out: `AGENTS.md` updated with the new architecture, commands and
validated behaviour. Next session starts at **Phase 2 — CLI** in this file.

Session 2 (Phase 2):
- Added the CLI package (`cli/`) and root `netscope.py`: argparse parser,
  dispatch/handlers, ANSI/ASCII renderer, `netscope>` shell (readline history +
  completion when available, numbered menu), admin helpers, exit codes and
  utilities (`ping`, `trace`, `dns`, `arp`, `routes`, `ports`, `mtu`).
- `diagnose` streams each check result as it completes and prints a summary;
  `--json` emits one document with `summary` and **no full snapshot**.
  `DiagnosticReport.to_dict(include_snapshot=...)` keeps reports full and CLI
  output small.
- `core/info.py` + `parse_mtu` + `mtu_interfaces` snapshot command provide
  adapters, addressing/origin/state, routes, ARP, DNS, proxy, VPN, Wi-Fi and MTU
  for `netscope info`. Admin status is attached by the CLI.
- `DiagnosticEngine` now accepts an `on_check` callback in addition to the
  per-layer `progress` callback.
- `SubprocessRunner` uses `Popen` + `communicate`: timeouts and Ctrl+C kill the
  child, timeouts keep exit code 124, and interrupted commands are logged.
- `logs` reads/opens/exports `%LOCALAPPDATA%\NetScope\logs\netscope.log`;
  `report` writes txt/json to `%LOCALAPPDATA%\NetScope\reports\` (or `--output`,
  with `-` for stdout). Config/log/report paths remain in `config.py`.
- Honest stubs remain: `fix` validates the ID, prints admin guidance and exits 3
  until Phase 3; `gui`/`install`/`uninstall` exit 3 with phase messages until
  Phases 4/5.
- Real-machine smoke tests passed for `--help`, `--version`, `info`, `diagnose`,
  `ping`, `dns`, `arp`, `routes`, `ports`, `mtu`, `logs` and `report`.
  Fixes found during validation: numeric `PrefixOrigin`/`AddressState` mapping,
  filter placeholder `{}` DNS values, normalize Wi-Fi key casing, always
  collect native ARP, and exclude ping summary lines from latency parsing.
- Tests: 84 passing (`tests/test_cli.py` added). Lint/typecheck is still not
  configured; `python -m compileall` is clean.

Phase 2 close-out: `AGENTS.md` updated. Next session starts at **Phase 3 — Fix
catalog, fix flow, snapshot/rollback, if_unresolved** in this file.

Session 3 (Phase 3):
- Created `fixes/` package with `catalog.py` (loader/validator), `executor.py` (FixExecutor with plan/prepare/run/rollback), `if_unresolved.py` (ranking engine), and `fixes.json` (61 seeded entries: ADP-01..06, SVC-01..06, IP-01..08, LAN-01..11, DNS-01..05, NET-01..11, VPN-01..06, WIFI-01..04, STK-01..04).
- Catalog validation: unique IDs, required fields, parameter sources/validators, native placeholders map to declared params, PS scripts declare used $Param names, high-risk non-detect-only fixes require second-confirmation step, DETECT-ONLY entries have no commands.
- Fix executor: parameter resolution from snapshot/evidence/overrides, pre-fix snapshot saved to `%LOCALAPPDATA%\NetScope\backups\`, ladder execution with per-step confirmations, `--yes` skips normal prompts, `--yes-i-understand-risk` required for high-risk steps, `--dry-run` shows preview only, verification by re-running relevant checks, honest failure reporting, rollback via saved snapshot.
- If-unresolved engine: `rank_causes()` scores this_device vs beyond_device using evidence + isolation answer; `unresolved_section()` builds probabilistic wording ("probable"/"possible", never diagnosis); `build_unresolved_sections()` gated to only DETECT-ONLY findings by default (fixable findings shown only after ladder exhausted via executor).
- CLI integration: `netscope fix [finding|fix-id] [--dry-run] [--yes] [--yes-i-understand-risk] [--rollback] [--adapter NAME] [--target VALUE] [--value VALUE] [--param NAME=VALUE]`. Non-interactive confirmation error when not TTY without `--yes`. Admin guidance printed for needs_admin. JSON output includes full outcome + preview on dry-run.
- Report integration: `build_unresolved_sections()` called in `cmd_report`, rendered in both text and JSON reports.
- Added `tests/test_fixes.py` (22 tests): catalog schema/completeness, DETECT-ONLY checks, verify flags, check fix_ids refer to catalog, executor resolve/dry-run/decline/admin/high-risk/rollback/detect-only, if_unresolved ranking/gating/wording/report inclusion, CLI dry-run/resolved/detect-only/unknown-id.
- Updated `tests/test_cli.py` to test unknown fix IDs properly.
- All 106 tests pass (84 existing + 22 new).

Session 4 (CLI Interactive Enhancement):
- Added `monitor` subcommand: `netscope monitor [--interval SECONDS]` for live network status dashboard.
- Implemented `cli/monitor.py` with ANSI-based live updating dashboard:
  - Periodic diagnostic runs (configurable interval, default 3s)
  - Real-time display of overall status, layer statuses, key findings
  - Keyboard controls: `q` quit, `r` refresh, `i` change interval
  - Requires TTY with color support; gracefully exits on non-TTY
- Integrated monitor into interactive shell:
  - Type `monitor` at `netscope>` prompt to enter live mode
  - Added "Live monitoring dashboard" to numbered menu
  - Press `q` to return to shell
- Updated `cli/parser.py`, `cli/commands.py`, `cli/shell.py`, created `cli/monitor.py`
- All 106 tests still pass.

Session 5 (Phase 3 review before Phase 4):
- Reviewed Phase 3 (fixes catalog/executor/if_unresolved, CLI integration,
  tests) against `prompt.txt` seed spec. Verified: 61 entries with correct
  family counts, admin/risk/reboot flags, DETECT-ONLY set, [VERIFY] set,
  high-risk second-confirmation steps (NET-07, STK-03), no SMB1/signing/
  NCSI-probing regressions, check fix_ids all resolve, verify refs resolve
  (SVC via prefix matching), DNS-03 backs up hosts before selective removal.
- Misalignments found and patched:
  - IP-06 was missing the spec's `route -f` last-resort ladder step (risk H,
    second explicit confirmation, reboot noted). Added the step and honest
    explanation/rollback notes; entry risk stays medium, the step is the
    high-risk one.
  - `FixStep.optional` was parsed but ignored by the executor: declining an
    optional step (e.g. NET-10 step 2) aborted the whole fix as "declined"
    (exit 3). The executor now marks optional declined steps "skipped" and
    continues the ladder to an honest unresolved outcome (exit 2).
  - task.md 3.5 close-out boxes were unchecked although done; ticked.
  - Non-JSON `netscope fix X --dry-run` printed the preview twice (once in
    `cmd_fix`, again via `_finish_fix`); the preview now prints once and is
    only embedded in the JSON payload.
- Known deliberate deviation (confirmed by user, keep): LAN-09 is fully
  DETECT-ONLY; `prompt.txt` seeds an optional AllowInsecureGuestAuth=1
  registry fix behind a second confirmation, which the catalog intentionally
  does not script ("outside this safe flow"). Document it in Phase 5 README.
- All tests pass (106 existing + 2 new in `tests/test_fixes.py`).

Session 6 (merge main into build, pre-Phase-4):
- User confirmed LAN-09 stays DETECT-ONLY; review patches committed as
  `22050f1` on `build`.
- Merged `main` (dashboard work: filled `modules/diagnostics.py` registry,
  `/api/diagnostics` + `POST /api/diagnostics/<step_id>/run`, Troubleshoot
  panel, expanded dashboard UI) into `build`.
- Conflicts resolved: `.gitignore` (union: pytest cache + prompt.txt) and
  `AGENTS.md` — this file had leftover committed conflict markers from an
  earlier attempt; resolved properly now: kept the build-side architecture
  doc, folded main's dashboard notes into one updated "Legacy dashboard
  notes" section, corrected stale facts (dashboard binds `HOST`/`PORT`
  0.0.0.0 with `_lan_urls()`; `modules/diagnostics.py` is no longer empty;
  tests 106 -> 108).
- `app.py`/`config.py`/`README.md` auto-merged; app now binds `0.0.0.0`
  from `config.HOST/PORT` and prints LAN URLs.
- Verified post-merge: 108 pytest tests pass; Flask test client smoke of
  `/`, `/api/status`, `/api/devices`, `/api/diagnostics` (11 steps,
  check_count 7 / repair_count 4) and `POST /api/diagnostics/<id>/run`
  all work.
- Phase 4 (tkinter GUI) starts next from this merged state.

Session 7 (Phase 4, tkinter GUI):
- Added `gui/` package; the GUI renders engine output only and calls the same
  `DiagnosticEngine`/`FixExecutor`/catalog as the CLI:
  - `gui/runtime.py` — `GuiRuntime` (engine/catalog/runner/ps/logger/
    admin_check/session_id/backup_dir) with `executor()` factory,
    `build_runtime()` (fresh `gui`-mode logging + real catalog) and
    `runtime_from_context()` (reuse a `CliContext`). Falls back to an empty
    catalog (`CatalogError` logged) so diagnosis still works.
  - `gui/app.py` — `NetScopeGui`: status line, findings `Treeview` with
    colour tags, per-finding detail (message/cause/evidence + "Proceed to Fix"
    buttons), modal preview dialog (exact commands + Admin/Risk/Reboot
    labels), "Still not working? Likely causes" collapsible panel, layer
    checkbuttons (all-on fallback), Run diagnosis, Export report (txt/json to
    `%LOCALAPPDATA%\NetScope\reports\`), View Logs. Workers (diagnose/fix/
    rollback/report) run on daemon threads and post to a `queue.Queue`;
    `root.after(100)` polling marshals dialogs via `DialogBridge`.
  - `gui/dialogs.py` — `DialogBridge.submit()` from workers blocks on an
    `Event`, answered by `poll()` on the Tk thread; calls from the UI thread
    are answered inline (`answer_directly`) to avoid self-deadlock.
  - `gui/launch.py` — `GUI_INTERNAL = "__gui__"`, `owns_console()`
    (`GetConsoleProcessList == 1`), `detach_console()` (`FreeConsole`),
    `launch_detached_gui()` (Popen `DETACHED_PROCESS |
    CREATE_NEW_PROCESS_GROUP`, devnull stdio, cwd=project root),
    `gui_relaunch_argv()` (source: `[netscope.py, __gui__]`; frozen:
    `[__gui__]`).
  - `gui/__main__.py` — `python -m gui` (dev entry, console stays attached).
- Dual-mode launch: `cli/main.py` intercepts the hidden `__gui__` token before
  argparse and runs the GUI in-process (`_run_gui_process`, logs
  `gui_crashed`). No-args + `owns_console()` (double-click/Win+R) →
  `detach_console()` + detached GUI spawn (task spec: detach/hide and open
  GUI); no-args from a shared terminal → interactive shell; no-args without a
  TTY → help + exit 64. `netscope gui` (`cmd_gui`) pre-checks `tkinter`, spawns
  the detached GUI, prints "NetScope GUI launched in a new window." and
  returns 0 so the prompt returns immediately.
- Fix flow: `executor.prepare()` preview → bridge "fix_confirm" dialog →
  `executor.run(assume_yes=True, risk_ack=False)`; high-risk steps still raise
  the executor's second confirmation ("This step is HIGH RISK...") rendered as
  a warning dialog. Rollback confirms via the same bridge. DETECT-ONLY
  findings skip the executor and show `unresolved_section()` in the causes
  panel. `needs_admin` outcomes show `admin_guidance()` and offer
  `relaunch_elevated(gui_relaunch_argv())` (GUI closes, elevated GUI opens).
  Outcomes reuse `render_fix_outcome`; reports reuse `render_report_text` and
  `build_unresolved_sections(report, catalog)`.
- Launcher tradeoff (document in Phase 5 README): the exe stays
  console-subsystem, so a double-click briefly flashes a console window; the
  GUI child itself is spawned `DETACHED_PROCESS`, so it never shows a console.
  `py.exe` wrapper launches (double-clicked `.py`) share the console, so
  `owns_console()` is False there and they open the shell — the frozen exe
  behaves correctly.
- Added `tests/test_gui.py` (20 tests): launch helpers, dialog-bridge
  round-trip/no-handler/UI-thread guards, `build_runtime`/
  `runtime_from_context`, headless-safe window construction (`pytest.skip` on
  `TclError`), findings list + detail + fix-button rendering, layer selection,
  background diagnosis via queue, diagnose failure surfaced (no popup),
  fix flow resolved via real `FixExecutor` + `FakeRunner`, declined fix
  cancelled without running, DETECT-ONLY causes panel, report export,
  `cmd_gui` launch/failure, hidden `__gui__` token, no-args own-console launch.
- Verified end-to-end on Windows: 128 tests pass; self-closing GUI smoke
  (real runtime, 1000x660 window, rows/detail/buttons/causes panel, clean
  shutdown — pending `after` callbacks cancelled); `netscope gui` parent exits
  0 immediately while the detached child logs `app_start mode=gui` →
  `gui_start` (venv redirector shows as two chained `python.exe` processes —
  normal venv behaviour, one GUI). `netscope --help` shows the new gui text.



Session 8 (Web UI replacement � Phase A start, on `feature/web-ui`):
- Branch verification: `main` @ 9d670d9 (design/layout + packet-loss/QOL
  dashboard), `build` @ 9e8be23 (engine/CLI/fixes/GUI/logging). Diverged
  `main +2 / build +11` (base 7b05eed); shared overlap in dashboard files and
  `AGENTS.md`; `build/` dir untracked/ignored local artifact.
- Step 0 complete: safety tag `build-pre-merge` @ 9e8be23; `git merge --no-ff
  main` into `build` ? merge commit **7ae6f8b** (`Merge main into build (keep
  main design/features intact, add build features)`). `main` unchanged.
  Conflicts: `AGENTS.md` only (content) � resolved by merging build
  architecture docs with compatible run/legacy notes (markers removed).
  `app.py/modules/ping_monitor/network_info/diagnostics`, `templates/index.html`,
  `static/css/style.css`, `static/js/dashboard.js` auto-merged from `main`
  (kept intact). `config.py` remained build�s but preserves dashboard keys
  (`APP_NAME/HOST/PORT/REFRESH_INTERVAL_MS/PING_TIMEOUT_SECONDS`). Created and
  moved to `feature/web-ui` @ 7ae6f8b (all web work here).
- Post-merge validation: `pytest -q` ? **128 passed**; `netscope --version` ?
  `NetScope 0.3.0`; mocked `tests/test_cli.py -k "diagnose and json"` ? 1
  passed. Real `netscope diagnose --json`/text investigated: emits complete
  valid JSON and **exit 1 (WARN)** consistent with text output (NlaSvc/manual,
  sharing services/firewall on this host) � not a regression; no engine/CLI/log
  change made.
- Phase A audit (initial): documented engine public API
  (`DiagnosticEngine.collect_snapshot/diagnose`, models/report/exit codes,
  runner/snapshot/probes), fix flow (`Catalog/load_catalog`, `FixExecutor
  prepare/run/rollback`, `FixOutcome` statuses, if_unresolved probabilistic
  ranking), logging (`setup_logging`/`StructuredLogger` JSON-lines fields &
  helpers), tkinter GUI (layout/buttons, queue/worker/DialogBridge, fix
  preview/confirm/risk-H/detect-only/unresolved/export/logs, launch/runtime),
  and main design (shell/views, cards/traffic/devices/troubleshoot, JS
  polling/CDN/`innerHTML` hotspots) for web parity planning.
- `task.md` updated with Phase 6 (Web UI replacement) checklist A�E and this
  session note. Remaining: detailed design/security audit, build-feature
  inventory mapped to TOOLS, parity tables, confirmed plan, then Phase B.
- Branch safety (current): `main` has no new commits; `build` has only Step 0
  merge commit (7ae6f8b) beyond pre-merge tag; work on `feature/web-ui`.

