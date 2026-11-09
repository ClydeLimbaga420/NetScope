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
- [ ] Update `AGENTS.md`
- [ ] Update Notes below

---

## Phase 4 — GUI (tkinter)

### 4.1 GUI shell
- [ ] Main window: status, findings list, plain-language explanations
- [ ] Each fix has "Proceed to Fix" + confirmation dialog with exact commands
- [ ] Admin/risk/reboot labels; high-risk double confirmation
- [ ] "Still not working? Likely causes" expandable panel
- [ ] "View Logs", report export, diagnose button, layer selection
- [ ] Same engine calls as CLI; no business logic in GUI

### 4.2 Dual-mode launch
- [ ] Console-subsystem exe behaviour
- [ ] `GetConsoleProcessList` detection: terminal → shell; own console →
      detach/hide and open GUI
- [ ] `netscope gui` detaches so prompt returns
- [ ] Avoid console flash; document launcher tradeoff (if needed)

### 4.3 GUI tests
- [ ] Construct GUI headless-safe; fix buttons call engine functions
- [ ] Skip gracefully on headless CI

### 4.4 Phase 4 close-out
- [ ] Update `AGENTS.md`
- [ ] Update Notes below

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
- Added `tests/test_fixes.py` (23 tests): catalog schema/completeness, DETECT-ONLY checks, verify flags, check fix_ids refer to catalog, executor resolve/dry-run/decline/admin/high-risk/rollback/detect-only, if_unresolved ranking/gating/wording/report inclusion, CLI dry-run/resolved/detect-only/unknown-id.
- Updated `tests/test_cli.py` to test unknown fix IDs properly.
- All 106 tests pass (84 existing + 22 new).

