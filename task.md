# NetScope Rebuild - Task Checklist

Source of truth: `prompt.txt`. Work phase by phase; only start a phase when the
previous one is complete and tested. Update `AGENTS.md` at the end of every
phase and keep the **Notes** section below current for the next session.

Existing code that must keep working: the Flask dashboard (`app.py`,
`modules/*`, `templates/*`, `static/*`).

---

## Phase 1 - Core engine, command runner, PowerShell layer, logging, tests

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
- [x] Pipeline layer order: adapter -> services -> ip -> gateway -> lan -> dns ->
      internet -> stack

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

## Phase 2 - CLI (argparse + interactive shell)

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

## Phase 3 - Fix catalog, fix flow, snapshot/rollback, if_unresolved

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
      commands, valid finding->fix mappings
- [x] Fix-flow tests (confirm/decline/dry-run/snapshot/rollback/re-check/admin/
      risk H)
- [x] If-unresolved tests (gating, ranking, wording, report/log inclusion)

### 3.5 Phase 3 close-out
- [x] Update `AGENTS.md`
- [x] Update Notes below

---

## Phase 4 - GUI (tkinter)

### 4.1 GUI shell
- [x] Main window: status, findings list, plain-language explanations
- [x] Each fix has "Proceed to Fix" + confirmation dialog with exact commands
- [x] Admin/risk/reboot labels; high-risk double confirmation
- [x] "Still not working? Likely causes" expandable panel
- [x] "View Logs", report export, diagnose button, layer selection
- [x] Same engine calls as CLI; no business logic in GUI

### 4.2 Dual-mode launch
- [x] Console-subsystem exe behaviour
- [x] `GetConsoleProcessList` detection: terminal -> shell; own console ->
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

## Phase 5 - Packaging, installer, CI, docs

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


## Phase 6 - Web UI replacement (tkinter to local web UI)

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

### Phase A - Verification, merge, audit, plan, parity
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
- [x] Full design audit: pages/regions/components/themes/animations/breakpoints
      and conflicts with security/offline rules (CDN/fonts, inline
      script/style/handlers, inline style attrs, eval/new Function,
      innerHTML/document.write with dynamic data, mock data, browser-only
      settings that must be CLI-shared). Documented in `docs/phaseA-web-ui.md`.
- [x] Build-features inventory (engine checks, fix catalog/flow/snapshot/
      rollback/unresolved, CLI utilities info/ping/trace/dns/arp/routes/ports/
      mtu/logs/report/monitor, logging, install/uninstall semantics) mapped to
      main's existing layout (TOOLS focus per decision).
- [x] Produce parity tables: (1) every tkinter GUI screen/button/feature and
      every CLI-only build feature ? web equivalent + place in main's layout +
      status; (2) main design elements with no build feature behind them; (3)
      build features with no natural place in main's layout (flag, use closest
      existing pattern; ask before new nav/pages/regions).
- [x] Confirm plan before large amounts of code (placement decisions for
      CLI-only tools inside TOOLS, legacy Troubleshoot `/api/diagnostics` vs
      engine/fix integration approach, any appearance-affecting conflicts).

### Phase B - Server, API, jobs/SSE, security (+ tests)
- [x] `web/` package scaffold: `server.py`, `api.py`, `security.py`, `jobs.py`,
      `pages.py`, `paths.py`, `run.py`, `templates/`, `static/{css,js,img}`;
      app factory `create_app`, Blueprints (pages + `/api`), explicit
      template/static folders via resource-path helper (dev + `sys._MEIPASS`).
      Copied main's design files into `web/templates|static` as baseline.
- [x] Flask run: debug=False, reloader off, threaded=True, bound to 127.0.0.1;
      suppress werkzeug banner; app-style browser open (Edge/Chrome --app,
      fallback default). Request/security events routed into NetScope log
      (`source:"web"`); packaged-console quieting/werkzeug-to-log refinement pending.
- [x] Background jobs for long ops (diagnose, fix/rollback, tools) with job IDs;
      SSE `text/event-stream` progress/results (`/api/jobs/<id>/events`, keep-alive,
      end marker) and cancel endpoint; diagnose streams per-check results.
      Job cancellation now reaches the active `CommandRunner` subprocess, queued
      cancellation and terminal-state races are handled with a `cancelling`
      state that holds the active-fix slot until worker cleanup completes; the
      browser has an SSE polling fallback. Windows commands run in kill-on-close Job Objects;
      cancellation/timeout/Ctrl+C terminate descendants, covered by a spawned
      parent-child process test. API-level disconnect recovery is tested;
      Node tests cover EventSource-error and unavailable-EventSource polling
      fallback. Browser end-to-end reconnect verification stays in Phase C.
- [x] Security (initial): bind 127.0.0.1; per-session + boot token, boot->
      HttpOnly SameSite=Strict cookie exchange + clean redirect, `/__session__`
      for JS POST header token; API requires cookie, POST requires
      `X-NetScope-Token` + Origin/Referer + JSON; Host allowlist; strict CSP
      + nosniff + no-referrer; consistent JSON errors. CORS disabled. Review/
      hardening and complete coverage tests pending.
- [x] Server-side fix confirmation (initial): `/api/fix/plan` returns preview
      (exact cmds/admin/risk/reboot/snapshot/rollback/explanation) + single-use
      expiring bound `confirmation_token`; `/api/fix/execute` requires valid
      token, Risk H requires `second_confirmation`, dry-run passed server-side,
      one-fix-at-a-time reservation is atomic; `/api/fix/rollback` is serialized
      with fix execution and requires explicit confirmation. Expired plan records
      are pruned and confirmation/dry-run flags require JSON booleans. Catalog
      IDs only; param validation via executor/CLI validators - audit pending.
- [x] JSON API routes (initial, over existing engine/fixes/utilities): `/api/status`,
      `/api/diagnose`, `/api/jobs/<id>`, `/api/jobs/<id>/events`,
      `/api/jobs/<id>/cancel`, `/api/findings`, `/api/fix/plan`,
      `/api/fix/execute`, `/api/fix/rollback`, `/api/unresolved/answer`,
      `/api/fixes`, `/api/fix/history`,
      `/api/info`, `/api/tools/<name>` (ping,trace,dns,arp,routes,ports,mtu),
      `/api/logs`, `/api/logs/stream`, `/api/report` (txt/json),
      `/api/open-log-folder`, `/api/ui-event`, `/api/heartbeat`,
      `/api/shutdown`, `/api/elevate`. JSON shapes aligned to engine/CLI where
      applicable; full alignment/streaming parity and error-contract audit pending.
- [x] Logging (initial): web mode logger, `source:"web"` events for server
      start/stop, API requests/responses, diagnose/tool/fix actions, security
      rejections, UI events. Command-level/snapshot/rollback/unresolved-detail
      events continue through the shared logger/runner; API request/response,
      utility command, and primary report/fix result shapes have focused parity
      tests. Packaged-mode output remains a Phase D verification.
- [x] CLI integration: `gui` gains `--no-browser`/`--port`; `netscope gui`
      runs web UI (detached spawn from interactive terminal so prompt returns);
      no-args from owned console / hidden `__gui__` launches web UI in-process.
      Existing CLI behavior/log formats preserved for non-web commands.
- [x] Single-instance ownership: OS-level per-user lock, atomic JSON port-file
      publication, health-verified instance reuse, and owner-checked cleanup;
      lock exclusivity and health response are covered by `tests/test_web_run.py`.
- [x] TTY detached launch handoff uses a bounded startup read, validates the
      loopback boot URL, opens the app/browser from the parent, and terminates
      a child that fails to publish a valid URL. Source/frozen launch argv are
      selected explicitly; mocked launch and failure paths are tested.
- [x] Werkzeug request records are routed to structured NetScope `source:web`
      events without duplicate handlers; source startup is banner-free.
- [x] Phase B completion: single-instance ownership, source launch handoff,
      security/fix confirmations, API contracts, SSE/polling/disconnect recovery,
      job/process-tree cancellation, injection rejection, and structured web/
      command logging are implemented and covered. The full suite passed
      (171 tests, 2026-11-10).
- [x] Phase B completion gate: proceed with Phase C. Browser E2E/design-fidelity
      checks remain Phase C; frozen launch and packaged log visibility remain
      Phase D because no executable artifact exists yet.

### Phase C - Templates, wiring, CSP/offline fixes, feature integration
- [x] Remove external asset dependencies from the main dashboard template and
      bundle the local font/Chart.js files so the UI remains offline-safe and
      CSP-compliant without changing the layout or the legacy dashboard
      behavior.
- [x] Convert the web dashboard template to inherit a Jinja `base.html` shell
      containing the existing sidebar/navigation, main wrapper, footer, and
      shared local assets; page-view markup remains in `index.html`.
- [ ] Finish reusable header/status/toast blocks and any server-rendered
      dynamic shell content while keeping the main markup and appearance exact.
- [x] Remove external runtime asset dependencies and keep dynamic dashboard
      rendering on safe DOM/text APIs; scripts/styles are external local assets
      and no inline handlers are required in the web template.
- [ ] Complete the security/offline audit for every dynamic rendering path,
      including CSP browser validation and an explicit autoescape test. Keep
      class names/CSS/layout/interactions/copy/order.
- [x] Initial build-feature wiring in the existing Troubleshoot stage: layer
      selection, engine diagnosis with per-check SSE and polling fallback,
      findings/evidence, catalog fix preview, dry-run, typed high-risk
      confirmation, unresolved isolation question, CLI utility jobs, network
      info/logs/report access, and fix-history/rollback controls.
- [ ] Complete feature parity and verify end-to-end behavior: live fix
      output/timings/re-check, full unresolved causes/checklist, rich network
      info tables and copy/refresh, utility cancellation/copy-export, dashboard
      run/status integration, and shared settings where backed by build.
- [ ] Wire any remaining build features into main's existing layout/components
      only:
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
- [x] Tests: dashboard template render and referenced static assets; full suite
      passes (213 tests as of Session 34, 2026-11-11).
- [ ] Tests: dynamic template autoescape, browser end-to-end flows, design
      fidelity (screenshot/computed styles), design-file changelog, and
      unchanged-main-CSS assertions where feasible.

### Phase D - Launch/lifecycle, packaging, build tests
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
      Flask web UI after); verify frozen-mode structured log routing and quiet
      console behavior.

### Phase E - Remove tkinter, docs, CI, final reports
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
validated behaviour. Next session starts at **Phase 2 - CLI** in this file.

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

Phase 2 close-out: `AGENTS.md` updated. Next session starts at **Phase 3 - Fix
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

Session 8 (Web UI replacement - Phase A start, on `feature/web-ui`):
- Branch verification: `main` / `build` merge and branch roles confirmed.
- Step 0 complete: safety tag `build-pre-merge` on `build`; `git merge --no-ff
  main` into `build` created merge commit `7ae6f8b`.
- Post-merge validation: `pytest -q` passed and `netscope diagnose --json`
  returned valid data with a warning exit code consistent with this host.
- Phase A audit: documented engine API, fix flow, logging, tkinter GUI,
  design review, and parity plan in `docs/phaseA-web-ui.md`.
- `task.md` updated with the Phase 6 checklist; remaining actions are Phase B
  server/API/security/hardening, then Phase C/D/E web integration and cleanup.

Session 9 (Web UI replacement - Phase B in progress, `feature/web-ui`):
- Scaffolded the `web/` package with app factory, blueprints, paths, security,
  jobs, API endpoints, templates, and static assets based on the legacy main
  dashboard.
- Added initial job/SSE flow, fix confirmation tokens, secure cookie/session
  exchange, Host/Origin/CSP headers, and JSON APIs over the existing engine/
  fix/utilities code paths.
- Integrated `netscope gui` to launch the web UI with `--no-browser` and
  `--port` support while preserving existing CLI behavior.
- Tests: initial `tests/test_web_api.py` coverage added for host rejection,
  cookie/token checks, and diagnose job + findings.
- Remaining B: single-instance lock/port handling, more robust detach/browser
  launch, deeper parity/hardening, and further API/security tests.

Session 10 (Web UI replacement - Phase A/B/C progress, `feature/web-ui`):
- Added design-preserving compatibility work: local bundled Chart.js + Inter
  fonts, `web-init.js` session bootstrap, and legacy dashboard API compatibility
  to keep the main shell working while build features are integrated.
- Safe-DOM refactor continued in `web/static/js/dashboard.js` to prevent
  dynamic `innerHTML` usage from unsafe browser data while preserving layout and
  class names.
- Validation: `py_compile web/api.py` passed; full suite remained green.
- Remaining: continue safe-DOM cleanup, wire engine/fix tool data into existing
  TOOLS/Troubleshoot panels, and finish Jinja/base extraction.

Session 11 (Web UI replacement - Phase C safe-DOM progress, `feature/web-ui`):
- Continued hardening the dashboard JS with textContent/safe DOM creation for
  dynamic rows and device/troubleshoot sections while keeping the original UI
  structure intact.
- Verified the web API tests still pass; client-side refactors retain the same
  behavior and design structure.
- Remaining: finish remaining dynamic rendering paths and build the build-feature
  integration in the main layout.

Session 12 (Web UI replacement - Phase B/C progress, `feature/web-ui`):
- Cleaned task markdown and added single-instance lock/port handling in
  `web/run.py` to reuse an existing server instance when one is already running.
- Continued safe-DOM refactor and preserved the bundled local assets and legacy
  API compatibility work from earlier sessions.
- Remaining: finish the build-feature wiring, Jinja base extraction, and
  remaining lifecycle/hardening tasks.

Session 13 (Web UI replacement - Phase B hardening, `feature/web-ui`):
- Routed Werkzeug request logs into the NetScope logger and enforced security
  logging for auth/host/origin/header failures.
- Expanded `tests/test_web_api.py` to cover security headers, missing tokens,
  fix plan/execute token expiry/reuse constraints, high-risk confirmation,
  and server-side dry-run execution.
- Validation: `tests/test_web_api.py` and the full suite remained green.
- Remaining B/C: robust browser detachment/opening, fuller job-cancel parity,
  more complete API/logging parity, and the final design-integrated web wiring.

Session 14 (Phase 6 continuation / task document update):
- Aligned the Phase 6 checklist in `task.md` with the actual web work already
  completed in the branch, especially the Phase A audit and parity planning.
- Captured the later session history in the Notes section so the task log matches
  the branch reality and the current work plan.
- Current focus remains in the remaining Phase B hardening and the Phase C build
  feature integration into the main web shell without changing the design
  layout or engine behavior.

Session 15 (Phase B/C implementation continuation):
- Added job-scoped cancellation propagation to `SubprocessRunner`; active
      commands terminate on cancel, cancelled state is preserved across worker
      completion, and queued cancelled jobs do not start. Engine/fix execution
      propagates cancellation instead of swallowing it.
- Serialized fix execution and rollback reservations, required explicit rollback
      confirmation, pruned expired confirmation plans, and required strict JSON
      booleans for dry-run/high-risk confirmation. Added `/api/fixes` and
      `/api/fix/history` metadata endpoints.
- Extracted `web/templates/base.html`, bundled root-dashboard fonts/Chart.js,
      and added `engine-ui.js` + `web-overrides.css` for the first engine-backed
      Troubleshoot integration. The UI currently includes diagnosis, basic fix
      planning/execution, tools, info/log/report access, and rollback/history.
- Updated launch tests to mock the current web entry point instead of starting
      a real server; made the safety AST scan BOM-aware. Added template/static,
      SSE/cancel, confirmation-expiry, rollback/history, and job-cancellation tests.
- Validation: full pytest suite passed (148 tests). Phase B completion remains
      open for process-tree/disconnect/lifecycle/API parity; Phase C remains open
      for browser verification, design fidelity, and remaining feature parity.

Session 16 (Phase B single-instance hardening):
- Added an OS-level per-user lock that prevents concurrent web UI processes
      from both starting, with a five-second wait for an owner to publish its
      endpoint before reuse.
- Port metadata now publishes atomically, is removed only by its recorded PID,
      and is reused only after a localhost `/health` response confirms NetScope.
- Added `tests/test_web_run.py` coverage for exclusive ownership, release,
      cleanup ownership, valid health probes, and rejecting an unrelated service.
- Validation: `tests/test_web_run.py` passed (4 tests). Remaining Phase B work
      includes launch handoff, process-tree/disconnect cancellation, and API/logging
      parity; this does not close the Phase B gate.

Session 17 (Phase B detached-launch handoff):
- The TTY `netscope gui` branch now starts the web child with a bounded URL
      handoff, validates that the emitted URL is an HTTP loopback `/__boot__`
      endpoint, and asks the parent to open it. Browser-open failure leaves a
      usable local URL in stderr; invalid startup output terminates the child and
      returns a failure instead of hanging.
- Added explicit source and frozen executable launch arguments and fixed
      TTY-only `CliContext`/`sys.executable` issues found by the launch tests.
- Validation: `tests/test_gui.py` passed (22 tests). Real process/browser smoke
      tests for source and frozen builds remain pending.

Session 18 (Phase B process-tree cancellation):
- Added Windows kill-on-close Job Object assignment in `SubprocessRunner` so
      timeout, Ctrl+C, and job cancellation end the command and its descendants;
      unsupported or denied job assignment falls back to direct-child termination.
- Added a Windows-only regression test that spawns a sleeping child, cancels
      the parent command, and verifies the child process no longer exists.
- Validation: 13 focused job/runner/subprocess tests passed. Browser disconnect
      behavior and real source/frozen launch smoke tests remain open.

Session 19 (Phase B cancellation lifecycle race):
- Running jobs now transition to `cancelling` when cancellation is requested;
      they become terminal only after worker cleanup. This keeps cancelled fixes
      from releasing the serialized-fix slot early and prevents idle shutdown while
      cancellation is still being processed.
- Added job-manager coverage for fix-slot exclusivity during cancellation and
      updated the API cancel test to verify the transitional state.
- Validation: `tests/test_jobs.py tests/test_web_api.py` passed (22 tests).

Session 20 (Phase B SSE disconnect recovery):
- Added API-level coverage for closing an SSE response while its job is active;
      disconnect does not cancel the job, and its final result remains available
      through `/api/jobs/<id>` polling.
- Validation: the targeted disconnect-recovery test passed. Browser-level
      reconnect behavior remains for the full web UI smoke test.

Session 21 (Phase B API input validation):
- Added a web API test that submits a shell-injection-like ping host, waits for
      its background job to fail validation, and asserts the shared command runner
      received no arguments.
- Validation: the targeted API injection test passed. Broader input-validation
      parity across all utilities and fix parameters remains open.

Session 22 (Phase B source launch smoke test):
- Added a real subprocess test for `python -m cli gui --no-browser --port N`;
      it verifies the boot URL, successful loopback `/health` response, and process
      cleanup using an isolated `%LOCALAPPDATA%` test directory.
- Validation: the targeted source-launch smoke test passed. Frozen executable
      startup and actual browser-window handoff remain unverified.

Session 23 (Phase B quiet startup verification):
- Replaced `Flask.app.run()` with Werkzeug `run_simple()` using the same
      loopback, threaded, debug-disabled, reloader-disabled settings to avoid
      Flask's unconditional console banner. The no-browser boot URL is flushed so
      the detached parent can receive it without relying on that banner.
- Extended the real source subprocess smoke test to check startup output,
      loopback health, and cleanup.
- Validation: focused `tests/test_web_run.py tests/test_jobs.py tests/test_gui.py`
      passed (34 tests). Structured Werkzeug request-log routing and browser-level
      reconnect verification remain open.

Session 24 (Phase B Werkzeug request logging):
- Added coverage that a Werkzeug INFO request record becomes a structured
      NetScope event with `source="web"`, and that configuring the handler twice
      does not duplicate records.
- Source startup banner suppression remains verified by the real CLI smoke
      test. Packaged-mode log visibility remains pending with Phase D packaging.
- Validation: the targeted request-log routing test passed.

Session 25 (Phase B API parity and input validation):
- Diagnosis-job and findings responses are asserted against the shared engine
      report serialization. Shell-like host/name inputs are tested across ping,
      trace, DNS, ports, and MTU and must fail before reaching the command runner.
- Added idle-shutdown coverage proving a `cancelling` job keeps the server alive.
- Validation: the focused parity/injection/lifecycle selection passed (7 tests).
- Remaining: audit fix-parameter injection and complete CLI/API shape and logging
      parity; these checks are not claimed complete based on the focused tests.

Session 26 (Phase B job-stream polling fallback):
- Extracted EventSource and polling behavior to `web/static/js/job-stream.js`;
      `engine-ui.js` supplies event/fallback callbacks while the helper owns stream
      closure, terminal status, polling, and error propagation.
- Added Node VM tests for EventSource failure falling back to `/api/jobs/<id>`
      polling and for environments without EventSource. The template asset test
      verifies the helper is served locally.
- Validation: 3 Node/template tests passed; both job-stream and engine UI
      scripts pass `node --check`. Browser-level reconnect remains a Phase C test.

Session 27 (Phase B fix-parameter validation):
- Added an authenticated `/api/fix/plan` test using the real catalog and
      `FixExecutor`; an injected adapter name fails planning and produces no call
      to the shared command runner.
- Validation: the targeted fix-parameter injection test passed. API/CLI
      serialization and command-logging parity remain open.

Session 28 (Phase B API/CLI contract and logging parity):
- Added exact report and fix outcome serialization checks, a utility result
      schema check against the shared CLI `UtilityRunner`, and a live loopback ping
      proving web utilities use the shared `SubprocessRunner` and structured command
      log fields. Added API request/response event field assertions.
- Packaged log visibility and frozen launch were moved to Phase D because there
      is no built executable; browser reconnect remains a Phase C browser test.
- Validation: 4 focused report/fix/utility/request-log tests passed. Rerun the
      full suite before closing Phase B.

Session 29 (Phase B close-out):
- Full suite passed: 171 tests in 3.79 seconds on 2026-11-10.
- Closed Phase B after validating source launch, singleton locking, web
  security/confirmation, API/core result shapes, utility/fix parameter
  rejection, request/command logging, SSE polling fallback/disconnect recovery,
  and cancellation through Windows process descendants.
- Browser E2E/design fidelity remains in Phase C; frozen executable launch and
  packaged log visibility remain in Phase D.

Session 30 (Phase 6C live-stack P0 verification):
- Re-ran the live repro against the real stack (real `python -m cli gui
  --no-browser --port N` child with isolated %LOCALAPPDATA%, real
  engine/catalog/FixExecutor, real PowerShell/ping jobs; no test client or
  mocks): 25/25 checks passed.
- Proven live: boot/session handshake with strict CSP; local dashboard.js +
  engine-ui.js asset wiring; /api/status real runtime (PowerShell layer
  available, live gateway/internet pings); diagnose job streamed 33 per-check
  SSE events and terminated with the end marker at EOF; a second SSE stream
  opened on the finished job ended in 0.0s (old code: 15s+); /api/findings
  returned the real machine findings; /api/fixes served all 61 catalog
  entries; fix plan + dry-run execute completed on the real FixExecutor
  (outcome dry_run, the old stray `snapshot=` kwarg TypeErrored); /api/logs
  /stream emitted keep-alives while idle and hit EOF after shutdown; no idle
  shutdown while a real job ran (>20s without heartbeat, /health ok);
  single-instance reuse handoff printed the running URL and exited 0; POST
  /api/shutdown exited the process (rc 0) and removed the port lock.
- The repro caught a remaining defect in the bind-failure P0 fix: werkzeug
  3.1.9 converts bind OSErrors into print(strerror) + sys.exit(1) inside
  BaseWSGIServer.__init__, so run_web_ui's `except OSError` never fired (rc 1
  came from werkzeug itself and `server_bind_failed` was never logged; the
  boot URL was also printed before the bind was known to succeed). Fixed
  web/run.py to bind via `werkzeug.serving.make_server` before advertising
  the boot URL/port lock, catching SystemExit(1) and OSError into a
  `server_bind_failed` event + clean return 1. Added regression tests
  (SystemExit bind, OSError bind, serve-until-KeyboardInterrupt shape).
- Full suite after the fix: 197 passed (2026-11-11); live repro re-run: 25/25
  including the bind-failure log check.
- Browser-level E2E (engine-ui adopt/MutationObserver double-fire guard, SSE
  reconnect, design fidelity) remains Phase C; the repro verified only the
  served page's local asset wiring and CSP.

Session 30 (automatic default-gateway repair, merged from origin/main):
- Added `core/gateway_setup.py` for read-only gateway discovery. It selects an
  active physical adapter (preferring one without a gateway), ranks DHCP
  server/lease, existing gateways, default routes, and first/last/common subnet
  addresses, then pings candidates.
- Added catalog fix `IP-09` ("No default gateway configured", verify `IP-05`,
  admin, risk medium). Its ladder renews DHCP, then adds a persistent default
  route via PowerShell/`netsh`; snapshot and rollback are catalog-driven.
- `IP-05` (missing default route) now points to `IP-09`; both the legacy
  dashboard and the new web Troubleshoot header have an
  `#auto-configure-gateway` button.
- The button now runs the one-click `fixes/gateway_config.py` path: if any
  default route exists it does nothing; otherwise it detects the gateway and
  executes `IP-09` immediately (still using the pre-fix snapshot, verification
  and rollback). No preview/confirmation dialog is shown.
- Fixed the web fix-execute call to stop passing an unsupported `snapshot` kwarg.
- Tests: added `tests/test_gateway_setup.py` (detection, one-click path, ladder,
  rollback), a web gateway-job test, and template assertions. Full suite: 197
  passed (2026-11-11). Browser-level verification of the new button remains
  Phase C.

Session 31 (gateway false-negative fix):
- The legacy `/api/status` warning "No default gateway was detected" was a
  parser bug, not a missing gateway: `ipconfig` can print an IPv6 gateway and
  then the IPv4 gateway on the next line, and the old regex only read the first
  line. Added `_windows_default_gateway()` with continuation-line handling and
  tests in `tests/test_network_info.py`.
- Verified on this host that `get_network_info()` now reports
  `192.168.254.254` and no missing-gateway issue. Full suite: 200 passed
  (2026-11-11). The running web UI must be restarted to load the fix.

Session 32 (combined connectivity card):
- Replaced the single Internet status card with a Connectivity card that shows
  both Internet and Gateway reachability from `/api/status`
  (`internet_ping` / `gateway_ping`) in both the web UI and legacy dashboard.
- Added `#internet-dot`, `#internet-status`, `#internet-host`,
  `#gateway-dot`, `#gateway-status`, `#gateway-host`, and reason rows, plus
  matching JS updates and a CSS `.card.connectivity` layout. Template tests now
  assert both status dots.
- Full suite remains 200 passed (2026-11-11).

Session 33 (merge origin/main into main):
- Merged `origin/main` (`88d3150` "Added Gateway Ping") into local main
  (`543b08a` "fixed engine patches, api handling and few bugs"), keeping both
  feature sets: the Session 30 live-stack/web fixes and the gateway discovery,
  `IP-09` repair, and combined Connectivity card.
- Conflicts were in `AGENTS.md`, `task.md`, and `web/static/js/engine-ui.js`.
  The engine UI now adopts `#auto-configure-gateway` with the same
  `cloneNode(true)` + `replaceWith` approach used for the other Troubleshoot
  controls (dropping legacy handlers) while still calling
  `/api/gateway/configure`; `configureGateway()` is retained.
- Full merged suite: 210 passed (2026-11-11).

Session 34 (web UI: elevation and repair library):
- Added a sidebar **Run as administrator** button (hidden when elevated) that
  calls `/api/elevate`; `/api/elevate` now returns 409
  `elevate_cancelled` and keeps the server alive when UAC is declined, instead
  of shutting down with no replacement instance. An ADMINISTRATOR badge and a
  short hint replace the button when elevated.
- Added a Repair Library page (`data-view="repairs"`, nav below Troubleshoot)
  with a row per catalog entry (id, name, symptom, risk, admin, detect-only)
  and a procedure pane. Each procedure shows plain-language step names and
  descriptions, exact commands in collapsible sections, verification checks,
  rollback notes/commands, and if-unresolved guidance.
- Added `/api/fixes/<id>` returning the catalog entry `to_dict()` plus current
  admin state. The Troubleshoot repair detail links to the library with **View
  full procedure**. Standard checks and non-admin repairs remain available to
  standard users; admin repairs are labelled and instruct users to elevate.
- Added tests for the detail endpoint, template ids, elevation cancellation and
  successful restart request. Full suite: 213 passed (2026-11-11); JS passes
  `node --check`.
