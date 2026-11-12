# AGENTS.md

NetScope is being evolved (per `prompt.txt`, tracked in `task.md`) from a Flask
dashboard into a universal Windows network troubleshooting tool with one shared
engine and two front ends (CLI + GUI). Work phase by phase; update this file and
`task.md` Notes at the end of every phase.

**Current status: Phase 4 complete; Phase 6 Phase B complete and Phase C in progress.** Phase 5 packaging is pending. The web UI has its localhost server/API/job/security foundation, local assets, engine-backed Troubleshoot/Repair Library integration, reusable shell partials/toasts, structured fix/unresolved/network-info output, and Phase C audit/changelog docs. Remaining Phase C work is broad browser E2E and screenshot/computed-style design verification; headless Edge + CDP is available on this host and has been used for spot checks (Troubleshoot single-check flow, blank amber `.step-reason` fix).

## Run / environment
- The Flask dashboard still works: `python app.py` → http://127.0.0.1:5000
  locally, or `http://<LAN-IP>:5000` from another device. It binds
  `HOST`/`PORT` from `config.py` (`0.0.0.0`, `debug=False`, `threaded=True`)
  and prints reachable LAN URLs via `_lan_urls()`. No authentication — keep
  it on a trusted LAN; never port-forward it to the internet.
- This checkout originally had **no `.venv`**. A venv now exists (Python 3.14.7).
  Recreate with `py -m venv .venv`, then
  `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt`.
- Run tests: `.\.venv\Scripts\python.exe -m pytest` (latest full run: 234 passed, 2026-11-12).
- Run the CLI: `.\.venv\Scripts\python.exe netscope.py --help`
  (or `python -m cli`). `netscope.py diagnose --json` is the machine interface.
- Run the web UI: `netscope gui` launches the localhost interface; use
  `netscope gui --no-browser --port N` to run it in the foreground and print
  its boot URL. The hidden `__gui__` entry serves the UI in-process. The legacy
  tkinter code remains until the Phase 6 parity checklist is complete.
- Double-clicking a terminal (no args) opens the interactive shell; double-
  clicking a launcher that owns its console detaches and opens the GUI.
- PowerShell is required for diagnostics (Windows PowerShell 5.1).
- Run `app.py` as a script: imports are flat/absolute (`from config ...`,
  `from modules...`, `from core...`), not a package.

## New architecture (Phase 1)
- `core/models.py` — `Status`, `Layer`, `CheckResult`, `DiagnosticReport`,
  pipeline order (`LAYER_ORDER`), exit-code logic.
- `core/runner.py` — the **single mockable command interface**.
  `CommandRunner.run(args, timeout=...)`; `SubprocessRunner` (never `shell=True`,
  `CREATE_NO_WINDOW`, timeouts, encoding-safe capture, logs every command) and
  `FakeRunner` for tests.
- `core/native.py` — native ping/netsh/arp/route parsing, defensive against
  localized/malformed output.
- `powershell/scripts.py` — static PowerShell query fragments (`BATCH_QUERIES`);
  no user interpolation. `powershell/runner.py` — `PowerShellLayer` runs scripts
  from a temp `.ps1` via `-File`, passes user values as separate `-ParamName
  value` arguments, batches all queries into one PowerShell startup, parses JSON,
  detects `ConstrainedLanguage`.
- `powershell/validation.py` — strict validators for hosts, IPs, ports, adapter
  names, profile names, fix IDs, paths. Reject shell metacharacters/control chars.
- `core/snapshot.py` — collects one immutable `Snapshot` (batched PowerShell +
  needed native tools including `arp`, MTU subinterfaces and pings) that all
  checks consume.
- `core/info.py` — builds the plain-data `info` view (adapters, addressing,
  routes, ARP, DNS, proxy, VPN, Wi-Fi, MTU, admin status is added by the CLI).
- `core/checks/` — one module per layer (`adapter`, `services`, `ip`, `gateway`,
  `lan`, `dns`, `internet`, `stack`); each exposes `run(ctx) -> list[CheckResult]`.
- `core/subnets.py` — finds private remote LAN subnets from the routing table
  (excluding local/virtual/loopback/link-local ranges) and picks their lowest-
  metric next hop. `collect_snapshot` pings up to 8 of those next hops, and the
  `LAN-03` check reports cross-subnet LAN reachability (route present but next
  hop silent / no next hop / not tested). It is block-level only: NetScope
  probes the next-hop router, not arbitrary hosts behind it.
- `core/probes.py` — pure-Python socket/DNS/HTTP probes (`NetworkProbe`,
  `FakeProbe`) with timeouts.
- `core/engine.py` — `DiagnosticEngine.diagnose(layers=None, snapshot=None,
  progress=..., on_check=..., mode=...)`; builds the snapshot, runs layers in
  order, captures check exceptions as `ERROR` results, reports progress per
  layer and optionally per result.
- `core/logging_config.py` — JSON-lines rotating logs. **Do not create a
  top-level `logging/` package** (it would shadow the stdlib).
- `config.py` — app version, timeouts, pipeline constants, `%LOCALAPPDATA%`
  paths (`data_dir`, `log_dir`, `report_dir`, `backup_dir`).

## CLI (Phase 2)
- Entry points: root `netscope.py`, `cli/main.py`, `python -m cli`. Rendering and
  terminal concerns stay in `cli/`; diagnostics stay in `core/`.
- `cli/parser.py` — argparse commands: `diagnose`, `fix`, `info`, `ping`,
  `trace`, `dns`, `arp`, `routes`, `ports`, `mtu`, `monitor`, `logs`, `report`, `gui`,
  `install`, `uninstall`, `--version`. Global flags: `--json`, `--no-color`,
  `--quiet`, `--verbose`, `--yes`, `--dry-run`, `--yes-i-understand-risk`.
  Usage errors exit 64 (custom `CliArgumentParser.error`).
- `cli/commands.py` — dispatch/handlers. `diagnose` streams each result to stdout
  as it completes (stderr shows collection), then a summary. `--json` emits one
  document without the full snapshot. `info` uses `core/info.py`. `fix` resolves a
  finding or fix ID, shows the preview (finding, cause, exact commands,
  admin/risk/reboot, snapshot plan), confirms, runs the ladder, verifies by
  re-checking, and prints outcome + rollback/if-unresolved. Options: `--dry-run`,
  `--yes`, `--yes-i-understand-risk`, `--rollback`, `--adapter`, `--target`,
  `--value`, `--param`. Non-TTY without `--yes` errors with exit 64.
  `report` includes unresolved sections from `build_unresolved_sections()`.
- `cli/utilities.py` — validated `ping`, `trace`, `dns`, `arp`, `routes`,
  `ports` (port-spec expansion capped at 1024) and `mtu` (DF-ping binary search
  548-1472 payload → path MTU).
- `cli/colors.py` — ASCII status symbols + ANSI colour; disables on non-TTY,
  `NO_COLOR`, `TERM=dumb`, `--json`/`--quiet`; enables Windows VT via ctypes.
- `cli/shell.py` — `netscope>` shell, history/completion when stdlib `readline`
  exists, `help`, numbered `menu`, `exit`. Shell commands reuse the same parser
  and dispatch. Type `monitor` to enter live dashboard mode.
- `cli/monitor.py` — ANSI-based live monitoring dashboard (`netscope monitor`).
  Periodic diagnostics (default 3s interval), real-time overall/layer/key-findings
  view, keyboard controls (`q` quit, `r` refresh, `i` interval). Requires TTY
  with color support.
- `cli/admin.py` — `is_admin()`, `format_admin_command()`,
  `relaunch_elevated()`; admin status is logged at startup and shown by `info`.
- `cli/exit_codes.py` — 0/1/2/3/4/64/130 and `--help` text.
- `logs` reads `%LOCALAPPDATA%\NetScope\logs\netscope.log`; `report` writes
  txt/json to `%LOCALAPPDATA%\NetScope\reports\` by default. `--output -` prints
  the report body to stdout.
- `SubprocessRunner` now uses `Popen` so timeouts and Ctrl+C kill the child,
  preserve timeout exit code 124, and keep stderr clean.

## Fixes (Phase 3)
- `fixes/catalog.py` — `CommandSpec`, `FixStep`, `Parameter`, `IfUnresolved`,
  `FixEntry`, `Catalog`; `parse_catalog()`, `load_catalog()`; validates unique
  IDs, required fields, parameter sources/validators, PS `$Param` declarations,
  native placeholders, high-risk second-confirmation, DETECT-ONLY restrictions,
  `[VERIFY]` flag on IP-08, LAN-10, DNS-04, DNS-05, NET-06, NET-08, NET-11.
- `fixes/fixes.json` — 62 seeded entries: ADP-01..06, SVC-01..06, IP-01..09,
  LAN-01..11, DNS-01..05, NET-01..11, VPN-01..06, WIFI-01..04, STK-01..04.
  Each has id, name, symptom, detection, explanation, admin, risk, reboot,
  snapshot (PS commands), rollback (commands + notes), verify (check IDs),
  ladder (steps with PS + native fallback), if_unresolved (this_device,
  beyond_device, next_checks, evidence_to_collect).
- `core/gateway_setup.py` — read-only gateway discovery for `IP-09`:
  `active_target()` picks an active physical adapter (preferring one without a
  default gateway); `detect_gateway()` ranks DHCP server/lease, existing
  gateways, default routes, then first/last/common subnet addresses, and pings
  candidates. `fixes/gateway_config.py` runs the one-click path: it skips when
  any default route exists, otherwise detects and executes `IP-09` immediately
  (snapshot/verification/rollback preserved). Both the legacy dashboard and the
  web Troubleshoot header expose `#auto-configure-gateway` for this action.
- `fixes/executor.py` — `FixExecutor`: `prepare()` builds `FixPlan` with
  resolved parameter values and preview lines; parameter sources
  `adapter_missing_gateway` and `detected_gateway` use `core/gateway_setup.py`.
  `run()` executes ladder with
  per-step confirmations (`--yes` skips normal, `--yes-i-understand-risk`
  required for risk-H), takes pre-fix snapshot, verifies by re-checking,
  stops when resolved, returns `FixOutcome` with status (resolved/dry_run/
  rolled_back/needs_admin/declined/error/detection_only/unresolved), exit code,
  step details, verification evidence, rollback availability, unresolved
  causes. `rollback()` restores latest saved snapshot for the fix ID.
- `fixes/if_unresolved.py` — `RankedCause`, `rank_causes()`, `unresolved_section()`,
  `build_unresolved_sections()`, `unresolved_for_results()`. Ranks
  this_device vs beyond_device using evidence + isolation answer; probabilistic
  wording ("probable"/"possible", never diagnosis); `build_unresolved_sections()`
  gated to DETECT-ONLY findings by default (fixable shown only after ladder
  exhausted via executor). Included in CLI report output.
- CLI `fix` subcommand: `netscope fix [finding|fix-id] [--dry-run] [--yes]
  [--yes-i-understand-risk] [--rollback] [--adapter NAME] [--target VALUE]
  [--value VALUE] [--param NAME=VALUE]`. Streams preview to stdout, prompts
  interactively, logs confirmations/fix_applied/unresolved. JSON output
  includes full outcome + preview on `--dry-run`.
- `tests/test_fixes.py` — 22 tests: catalog completeness/schema, DETECT-ONLY,
  verify flags, check fix_ids, executor resolve/dry-run/decline/admin/high-risk/
  rollback/detect-only, if_unresolved ranking/gating/wording/report, CLI
  dry-run/resolved/detect-only/unknown-id. Total 106 tests passed at Phase 3.

## GUI (Phase 4)
- `gui/` is a front end only: it calls the same `DiagnosticEngine`,
  `FixExecutor` and catalog as the CLI and reuses `cli.render` helpers. **Never
  put detection, fix or validation logic in `gui/`** — extend `core/` or
  `fixes/` instead.
- `gui/runtime.py` — `GuiRuntime` (engine/catalog/runner/ps/logger/
  admin_check/session_id/backup_dir, `executor()` factory), `build_runtime()`
  (fresh `gui`-mode logging + real catalog; empty catalog if it fails to load)
  and `runtime_from_context()` (reuse a `CliContext`).
- `gui/app.py` — `NetScopeGui`: status line, findings `Treeview` with colour
  tags, per-finding detail (message/cause/evidence + "Proceed to Fix"),
  preview dialog with exact commands and Admin/Risk/Reboot labels, "Still not
  working? Likely causes" collapsible panel (from `unresolved_section`),
  layer checkbuttons, Run diagnosis, Export report (txt/json to
  `%LOCALAPPDATA%\NetScope\reports\`), View Logs. Workers run on daemon
  threads and post dicts to a `queue.Queue`; `root.after(100)` polling applies
  them on the Tk thread. `shutdown()` cancels the poll timer.
- `gui/dialogs.py` — `DialogBridge`: worker calls `submit()` and block on an
  `Event`; `poll()` on the Tk thread answers them. `submit()` from the Tk
  thread itself answers inline (`answer_directly`) to avoid self-deadlock.
- `gui/launch.py` — `GUI_INTERNAL = "__gui__"`, `owns_console()`
  (`GetConsoleProcessList == 1`), `detach_console()` (`FreeConsole`),
  `launch_detached_gui()` (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`,
  devnull stdio, cwd = project root), `gui_relaunch_argv()` (source:
  `[netscope.py, "__gui__"]`; frozen: `["__gui__"]`).
- `cli/main.py` intercepts `__gui__` before argparse and runs the GUI in
  process (`_run_gui_process`). `netscope gui` (`cmd_gui`) pre-checks
  `tkinter`, spawns the detached GUI and returns 0. No args + own console →
  detach + GUI; no args in a shared terminal → shell; no args without a TTY →
  help/exit 64.
- Fix flow: `prepare()` preview → bridge confirmation → `run(assume_yes=True)`;
  high-risk steps still trigger the executor's second confirmation (rendered as
  a warning dialog). DETECT-ONLY findings never run the executor. `needs_admin`
  offers `relaunch_elevated(gui_relaunch_argv())`.
- Launcher tradeoff (document in Phase 5 README): the exe stays
  console-subsystem, so double-clicking it briefly flashes a console; the GUI
  child itself is detached and shows no console. A double-clicked `.py` via
  `py.exe` shares a console, so `owns_console()` is False and it opens the
  shell — the frozen exe behaves as specified.
- `tests/test_gui.py` — 20 tests: launch helpers, dialog bridge
  (round-trip/no-handler/UI-thread direct answer), runtime builders, headless-
  safe construction (`pytest.skip` on `TclError`), rendering/detail/buttons,
  layer selection, background diagnosis, failure surfacing, real fix flow via
  `FixExecutor` + `FakeRunner`, declined fix, DETECT-ONLY causes panel, report
  export, `cmd_gui`, `__gui__` token, own-console launch.

Usage:
```python
from core.engine import DiagnosticEngine
report = DiagnosticEngine().diagnose(layers=["adapter", "ip"])
print(report.exit_code, report.first_failing_layer, report.to_dict())
```

```python
from fixes.catalog import load_catalog
from fixes.executor import FixExecutor
from core.engine import DiagnosticEngine

catalog = load_catalog()
engine = DiagnosticEngine()
snapshot = engine.collect_snapshot()
report = engine.diagnose(snapshot=snapshot)
entry = catalog.require("IP-01")
executor = FixExecutor(runner, ps, logger, engine, catalog)
plan = executor.prepare(entry, snapshot=snapshot)
outcome = executor.run(entry, plan=plan, assume_yes=True)
print(outcome.exit_code, outcome.status, outcome.to_dict())
```

```python
from gui.app import run_gui
from gui.runtime import build_runtime

raise SystemExit(run_gui(build_runtime()))  # same engine, Tk front end
```

## Web UI (Phase 6B complete; Phase 6C in progress)
- `web/run.py` serves on `127.0.0.1`, owns a per-user process lock, atomically
  publishes its port/boot token, validates existing instances with `/health`,
  and uses a bounded detached-launch URL handoff. Source startup is banner-free.
  The server binds via `werkzeug.serving.make_server` *before* advertising the
  boot URL/port lock; werkzeug 3.x turns bind errors into
  `print(strerror)` + `sys.exit(1)` inside `BaseWSGIServer.__init__`, so
  `run_web_ui` catches both `SystemExit(1)` and `OSError`, logs
  `server_bind_failed`, and returns 1 cleanly (verified against the real
  stack, 2026-11-11). A monitor thread handles explicit shutdown (sleeps briefly
  to flush the HTTP response, logs `server_shutdown`, removes the port lock,
  `os._exit(0)`),   while heartbeat timeout shutdown is gated on
  `jobs.has_active_jobs()`; the heartbeat threshold is 120s to survive
  Chrome's background-tab timer throttling.
- `web/security.py` enforces localhost Host checks, boot/session tokens,
  same-origin state-changing requests, CSP, and security headers.
- `web/server.py` builds the runtime explicitly with `SubprocessRunner`,
  `PowerShellLayer` and `NetworkProbe` (so `/api/status` reports a live
  PowerShell layer) and falls back to `empty_catalog()` with a logged
  `fix_catalog_unavailable` warning if the catalog fails to load.
- `web/jobs.py` provides SSE plus job polling, cancellation states, and a
  job-scoped command cancellation context. Windows commands use kill-on-close
  Job Objects so cancelled commands and descendants terminate together.
  Streams mark `Job.events_done` under the job lock and drain with `get_nowait`
  first, so a stream opened on a finished job ends immediately (0.0s instead of
  the old 15s timeout) and keep-alives are sent only while genuinely idle.
  `JobManager.has_active_jobs()` is the single source for idle-shutdown gating.
- `web/api.py` routes operations through the existing engine, catalog,
  `FixExecutor`, `UtilityRunner`, report builder, and structured logger. Do not
  add diagnostic or fix business logic to the web layer. `/api/logs/stream`
  emits keep-alives when idle and stops on `shutdown_event`; fix execution does
  not pass the stale `snapshot=` kwarg to `FixExecutor.run()`.
- The overview card is a combined Connectivity card showing both Internet and
  Gateway status (`#internet-dot`/`#gateway-dot`), fed by `/api/status`
  `internet_ping` and `gateway_ping`.
- `web/static/js/engine-ui.js` adopts the shared Troubleshoot controls by
  `cloneNode(true)` + `replaceWith`, dropping the legacy dashboard handlers
  registered first (cannot stop them with capture ordering alone). This also
  covers `#auto-configure-gateway`, which calls `/api/gateway/configure`. A
  `MutationObserver` re-asserts the engine view if the legacy registry renders
  late into `#check-steps`/`#repair-steps`/`#diag-stage`.
- The Repair Library (`data-view="repairs"`, nav below Troubleshoot) lists every
  catalog entry as a row (id/name/symptom/risk/admin) and renders its procedure
  from `/api/fixes/<id>`: plain-language steps, collapsible exact commands,
  verification, rollback, and if-unresolved guidance. The Troubleshoot repair
  detail links to it with **View full procedure**. A sidebar **Run as
  administrator** button calls `/api/elevate`; cancellation (UAC declined) logs
  `elevate_cancelled`, returns 409 and keeps the server running.
- Tests: latest full suite is 226 passing (2026-11-12). Session 30's live repro
  verified the real CLI child, boot/session/CSP, local assets, 33 SSE check
  events, findings/fixes/catalog, fix plan+dry-run, log streaming, shutdown,
  single-instance reuse and bind-failure logging (25/25); the gateway repair
  adds `/api/gateway/configure` and combined Internet/Gateway status. Phase C
  still needs browser E2E and design-fidelity verification; Phase D owns
  frozen-build launch/log checks.
- UI overhaul (Session 41, Phase C design pass): `web/templates/base.html` +
  `web/templates/index.html` restructured (skip-link, mobile topbar +
  `#nav-toggle`/`aside.sidebar`/`#sidebar-backdrop` drawer, SVG nav icons,
  conn-grid Connectivity card, `.btn`/`.btn-secondary`/ghost buttons carry an
  SVG + `<span class="btn-label">` so busy state text swaps via
  `setButtonLabel`/`.btn-label`, `.top-status[data-live]` live badge,
  footer shows `config.APP_VERSION` + `#footer-time`). Stat cards: the
  Connectivity card is a full-width hero row (`grid-column: 1 / -1`) with the
  four single-metric cards in an even 4-up row below (the old 6-track
  single-row grid squeezed them to ~141px and wrapped their labels; verified
  via headless-Edge DOM measurement, cards now 219px at the same width; pairs
  up below 1180px as before). `style.css` is the full
  shared design system; `web-overrides.css` holds engine-view components
  (layer controls, evidence, `.engine-output` cards + `.engine-copy`, fix-fact
  chips, dialogs, tool panel, admin control, Repair Library with
  `.repair-search` filtering + `.repair-search-count`). `engine-ui.js` gained
  `svgIcon`/`emptyState`/`fixFact`/`renderFixFacts`/`setButtonLabel` helpers,
  empty states, and label-aware busy buttons. `dashboard.js` (web) renders
  adapter pills (`adapter-dot`/`adapter-body`/`adapter-state`), sets
  `data-live` (success/catch/401), uses `\u2715` error markers, null-guards
  `#repair-steps` (web template has none — repairs live in the Repair Library)
  and disables the Refresh devices button via `setRefreshDevicesBusy`. Brand:
  the "N" tile logo is gone everywhere (no `.brand-icon`); NetScope carries as
  a gradient wordmark (`@supports` background-clip text) and the favicon is a
  non-letterform signal glyph. The legacy dashboard was synced to the same
  design: `templates/index.html` rewritten (drawer markup, conn-grid,
  troubleshoot rail incl. `#repair-steps`, `#elevation-badge`, footer), its
  `static/css/style.css` is a copy of the web stylesheet, and
  `static/js/dashboard.js` got the same adapter pills/data-live/`\u2715`/
  `setRefreshDevicesBusy` treatment plus a guarded Chart init
  (`let chart = null; try ... catch`), `.btn-label`-aware `configureGateway`
  and a drawer IIFE mirroring `web-init.js`. Test constraints drove markup:
  the web templates must keep the literal tags `<aside class="sidebar">`,
  `<main class="main">`, `<footer>` (no extra attributes on those tags — the
  skip link targets the inner `#main-content` wrapper div instead).
- Phase C session 42: reusable shell partials `web/templates/_page_header.html`,
  `_status.html`, `_toast.html` (`#toast-region`, `window.NetScope.toast`,
  textContent-only); fix outcomes render structured steps/timings/verification
  and unresolved sections render ranked causes + next checks + evidence;
  Network info renders tables with copy/export/refresh; utilities export and use
  the shared cancel control. `docs/phaseC-web-ui.md` is the design-file
  changelog/offline-CSP audit/parity map. `tests/test_web_design.py` enforces
  offline/local assets, no inline handlers/scripts/styles, no unsafe DOM sinks,
  design tokens/breakpoints, shared-CSS identity, and changelog coverage;
  autoescape tests live in `tests/test_web_api.py`. Browser E2E/design
  screenshots remain open (no browser on this host).
- Phase C session 42b: `FixExecutor.run(progress=...)` emits best-effort
  snapshot/step/verify/guidance events (swallows callback errors);
  `/api/fix/execute` forwards them as `fix_progress` job events, and the web
  Troubleshoot stage renders an APPLYING FIX progress bar with per-step
  running/verifying/done chips before the structured outcome. Fix History and
  Recent Logs render readable rows (localized time, badges, compact field
  summaries) instead of raw JSON; rollback appears only on the newest snapshot
  per fix, older snapshots are labelled. Tests cover executor progress events,
  callback-failure safety, and web forwarding; full suite 229 passed.

## Logging
- JSON-lines file at `%LOCALAPPDATA%\NetScope\logs\netscope.log`, rotating
  (5 MB × 5). Every record has `ts`, `level`, `logger`, `session_id`, `event`,
  optional `fields`; secrets are redacted.
- Structured logger helpers: `event`, `debug`, `warning`, `error`, `command`,
  `check`, `confirmation`, `fix_applied`, `unresolved`, `action`.
- `setup_logging(mode, session_id, log_dir=..., console=...)` reinitialises
  handlers safely.

## Check results / exit codes
- Each result carries `id`, `layer`, `status` (pass/warn/fail/skip/error),
  message, `cause`, `evidence`, `fix_ids`, `detection_only`.
- `report.exit_code`: 0 all pass/skip, 1 warnings, 2 fail/error. CLI adds 3 fix
  failed, 4 needs admin, 64 usage error, 130 Ctrl+C.
- Check IDs use descriptive IDs (e.g. `GW-02`, `NET-PING`) while `fix_ids`
  reference the future catalog (`ADP-01`, `IP-01`, `LAN-02`, ...).

## Phase 1 behaviour that was validated on the real machine
- Full pipeline works end-to-end against real `Get-NetAdapter`/`Get-NetIP*`,
  netsh, arp, ping, DNS and HTTP. `collect_snapshot` returns all major sections.
- APIPA/stale-lease/IP-overlap checks intentionally ignore virtual, disconnected,
  Bluetooth, Wi-Fi Direct, Npcap loopback and `Local Area Connection*` adapters.
- PnP driver errors only count for real NICs and critical problem codes
  (10/28/31/43); Bluetooth/WAN Miniport/Kernel Debug/Wi-Fi Direct are ignored.
- Winsock third-party detection only considers `Layered Service Provider` entries,
  so Microsoft base providers (MSAFD, Hyper-V RAW, AF_UNIX, ...) do not warn.
- Firewall discovery check evaluates a group as enabled if any inbound Allow rule
  is enabled (avoids false "62 rules disabled").

## Legacy dashboard notes (still true, merged from main)
- `app.py` exposes `/`, `/api/status`, `/api/devices`, `/api/diagnostics`, and
  `POST /api/diagnostics/<step_id>/run`; `static/js/dashboard.js`
  polls `/api/status` every 2000 ms (`config.REFRESH_INTERVAL_MS` is unused; only
  `PING_TIMEOUT_SECONDS` is read). No authentication: the dashboard and the
  diagnostics/repair endpoints are reachable by anyone who can access port 5000.
- `modules/diagnostics.py` is a registry of predefined checks/repairs (adapter
  status, IP config, loopback, gateway/internet ping, DNS, traceroute, DNS
  flush, DHCP renew, Winsock/TCP-IP reset). Commands are argv lists — never
  shell strings — and the client can only select a known `step_id`; there is
  no arbitrary command execution. Windows-only repairs report as unsupported
  elsewhere. `run_diagnostic` returns `{id, success, commands, output,
  duration_ms}`; `list_diagnostics` returns each step's `id`, `title`,
  `description`, `kind`, `requires_admin`, `supported`, `available`,
  `command`, `reason`, `timeout`, plus `elevated`, `system`, `check_count`,
  `repair_count`.
- `BandwidthMonitor` is a module-level singleton; rates are deltas between
  requests (multiple tabs or a changed poll interval distort readings); the
  dashboard applies EMA smoothing (`SMOOTHING_FACTOR = 0.34`) client-side.
- Each `/api/status` call synchronously shells out to `ping` twice
  (hardcoded internet host `1.1.1.1` and the detected gateway); ping output
  is regex-parsed per OS. `modules/network_info.get_default_gateway()` uses
  `_windows_default_gateway()` to handle `ipconfig` output where an IPv6
  gateway line is followed by the IPv4 gateway on a continuation line.
- Device discovery warms the ARP cache (private subnets, max 1024 hosts, 15 s
  cache) then parses `arp -a`, filtering multicast/broadcast entries; it never
  scans public/routed networks. Names via NetBIOS UDP 137 then reverse DNS
  (1.5 s budget, 300 s/60 s caches). The dashboard retries `/api/devices`
  after 6 s.
- Brands come from the offline OUI map in `modules/oui_vendors.py`
  (common-prefix subset generated from Wireshark's `manuf` data at
  `https://www.wireshark.org/download/automated/data/manuf`); locally
  administered MACs show `Private MAC`. Regenerate this data if vendor
  coverage is insufficient. The device table has six columns (name, brand,
  IP, MAC, connection, entry type); `/api/devices` returns `name`, `vendor`,
  `ip`, `mac`, `connection`, `connection_detail`, `type`. `connection` is a
  best-effort label (`This PC`, `Router`, `Wireless`, `Wired`, `Unknown`)
  derived from ARP interface mapping (Wi-Fi adapter names), the default
  gateway (with `route print -4` fallback), randomized MACs, and
  mobile/IoT vendor OUIs — Windows does not expose the AP's client list.
  Each entry also carries `mac_randomized`, `hardware_mac` and `mac_note`.
  Remote devices with randomized (locally administered) MACs are flagged
  because their real hardware MAC is hidden by design; the PC's own active
  adapters are added as `type: "local"` rows with their real hardware MAC
  (queried from `Get-NetAdapter` `PermanentAddress`, with virtual adapters
  and locally administered/unknown permanent addresses excluded).
  Device overrides are in browser localStorage; double-click a name
  to rename it. The table shows up to 8 rows (`DEVICE_VISIBLE_ROWS` in
  `dashboard.js`; `applyDeviceScrollHeight()` measures the sticky `thead`
  plus the first 8 rows and sets `.table-wrap` max-height, rerun on device
  refresh and window resize; 420px CSS fallback). `#device-count` is a pill
  updated on each `/api/devices` render.
- Chart.js and Inter fonts are bundled locally in `static/` and `web/static/`;
  the dashboard no longer depends on a font or chart CDN. `dashboard.js` still
  initializes Chart.js at startup, so the referenced local asset must remain
  present (covered by the web template asset test).
- The Troubleshoot panel is a master-detail UI: `#check-steps`/`#repair-steps`
  render a grouped rail and `#diag-stage` renders the selected step.
  Per-step results live in `diagnosticStates`;
  `updateDiagnosticsSummary()` drives the progress bar
  (`#diag-progress-fill`, `#troubleshoot-percent`). Unsupported steps stay
  selectable so their `reason` is visible, but their run button is disabled.
  Repairs prompt via `window.confirm` and warn when not elevated.
- `database/db.py` is not imported anywhere — the SQLite schema is unused
  scaffolding (`database/netscope.db` is gitignored).
- Do not delete `modules/`, `templates/`, `static/`, SQLite scaffolding until a
  later phase explicitly replaces them.

## Safety invariants (do not break)
- All system calls go through `CommandRunner.run`; never `shell=True`, never
  `os.system`, never build shell strings from user input.
- PowerShell scripts are static catalog text; user values are separate argv.
- Validate all user input before it reaches a command (`powershell/validation.py`).
- Timeouts on every command; record state before changing it (fix phases).
- Never enable SMB1, disable SMB signing, or disable NCSI active probing by
  default (DETECT-ONLY or second confirmation only).

## Next phases
- Phase 5: PyInstaller exe, installer/uninstaller (PATH/App Paths/Start Menu),
  GitHub Actions, README/manual test checklist. Replace `install`/`uninstall`
  stubs. Document: LAN-09 stays DETECT-ONLY (deliberate deviation from
  `prompt.txt`'s optional registry fix) and the console-flash launcher
  tradeoff.
## Dev install / running
- `pip install -e .` (after requirements) exposes the `netscope` command from any
  shell; a `netscope.bat` wrapper is also provided in `.venv\Scripts`. Run
  `netscope --help`, `netscope diagnose`, `netscope gui`.
- Troubleshoot now lists all 32 planned checks before a run (via
  `/api/checks` + `core/checks/descriptors.py`); repairs live only in the
  Repair Library. The diagnostic rail scrolls independently of the detail pane.
## Packaging fix (dev install root cause)
- Bug: `netscope` command failed with `ModuleNotFoundError: No module named 'config'`
  because flat imports (`import config`, `from modules...`) assume the project
  root is importable, but `pyproject.toml` only declared packages `cli`, `core`,
  `fixes`, `gui`, `powershell`, `web`. `config.py` (a top-level module) and
  the `modules` package were not declared, so the editable finder never exposed
  them.
- Fix: `pyproject.toml` now sets `py-modules = ["config"]` and adds `modules*`
  to `[tool.setuptools.packages.find] include`. No PYTHONPATH tricks or wrapper
  scripts. Deleted the masking `.venv\Scripts\netscope.bat`.
- Verify with venv activated/on PATH: `netscope --help`, `netscope diagnose`,
  `netscope gui` work from any directory.
## Stale-UI fix (Session 37)
- `refreshDevices` referenced an undefined `devices` variable, so the device
  table never updated (stuck on "Loading..."). refreshStatus could throw on
  missing fields (latency_ms strict-null check). Both fixed with null-safe
  guards and explicit 401 handling. All /api/* endpoints verified to return
  real data with a valid session cookie.
## Initial-load / nav fix (Session 38)
- `$("repair-steps").addEventListener(...)` threw (element removed from
  template), aborting dashboard.js before refreshStatus/refreshDevices/nav
  listeners ran. Guarded all top-level addEventListener calls with null checks.
