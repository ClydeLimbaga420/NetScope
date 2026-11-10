# Phase A — Web UI parity, audit, and plan (feature/web-ui)

## 1. Branch & merge (done)
- `main` @ 9d670d9 (design/layout + dashboard features incl. packet-loss/QOL). `build` @ 9e8be23 (engine/CLI/fix/GUI/logging, phases 1–4). Diverged main +2 / build +11 (base 7b05eed).
- Step 0: tag `build-pre-merge` @ 9e8be23; `git merge --no-ff main` into `build` → **7ae6f8b**. Only conflict `AGENTS.md` (resolved). `main` unchanged; `build` has only Step 0 merge; work on `feature/web-ui`.
- Post-merge: pytest 128→132 passed (incl. web), `netscope --version` OK, mocked diagnose-json OK. Real `diagnose --json` returns valid JSON, exit 1 (WARN on host) — not a regression.

## 2. Existing tkinter GUI summary (to replace, parity source)
- `NetScopeGui` (`gui/app.py`): Run diagnosis, layer checkboxes (all layers), status line/admin label, findings `Treeview` (Status/Check/Layer/Finding, color tags) + detail pane (message/cause/evidence), per-fix **Proceed to Fix** buttons, **Export report** (txt/json), **View Logs**, collapsed **“Still not working? Likely causes”** panel. Background workers + queue, `DialogBridge` confirmations.
- Fix flow: DETECT-ONLY → causes only; else `FixExecutor.prepare` preview (exact cmds/admin/risk/reboot/snapshot/rollback) → confirm → `run(assume_yes=True)` with risk-H second confirmation, `needs_admin` → relaunch elevated offer, re-verify, ladder/unresolved; rollback action where available. Renders via `cli.render`.

## 3. main design/layout (fixed, must remain identical)
- Shell: sidebar brand/nav (MONITORING: Overview/Devices/Traffic; TOOLS: Troubleshoot) + status footer; views `#view-main` and `#view-troubleshoot`; topbar LIVE/updated; stat cards (Internet status, Download/Upload, Latency, Packet loss) with reasons; Traffic chart panel; System info + interfaces/adapters; Devices table (refresh/count, 8-row scroll, rename via localStorage); Troubleshoot panel (elevation badge, Run all checks, progress, rail `#check-steps`/`#repair-steps`, stage `#diag-stage`, notes); footer time.
- Assets: `style.css` (tokens/layout/components/responsive), `dashboard.js` (polling, Chart.js, device render/aliases, troubleshoot rail/stage/progress/run/confirm, view switching).
- Current data sources (legacy dashboard): `/api/status`, `/api/devices`, `/api/packet-loss`, `/api/diagnostics`, `POST /api/diagnostics/<step_id>/run` (`modules/*`, `app.py`). Build features come from `core`/`fixes`/CLI engine (different model).

## 4. Engine / fix / logging public APIs (unchanged)
- `core.engine.DiagnosticEngine(runner,ps,logger,probe,hosts_path)`: `collect_snapshot()->Snapshot`, `diagnose(layers=None,*,snapshot=None,progress=None,on_check=None,mode='cli')->DiagnosticReport`. Pipeline adapter→services→ip→gateway→lan→dns→internet→stack; per-check callback; exceptions captured as ERROR; report has `results/snapshot/session_id/mode/overall_status/first_failing_layer/exit_code/to_dict()`.
- `core.models`: `Status`, `Layer`, `CheckResult`, `DiagnosticReport`; `core.info.build_info`; `core.runner.CommandRunner.run` (no `shell=True`); probes.
- `fixes.catalog.load_catalog()/Catalog/FixEntry`; `fixes.executor.FixExecutor.prepare/run/rollback` + `FixOutcome/FixPlan` (statuses resolved/dry_run/rolled_back/needs_admin/declined/error/detection_only/unresolved, single-use server confirmation required in web, risk-H second confirm, dry-run server-side, one fix at a time); `fixes.if_unresolved` probabilistic ranked causes + isolation answer.
- `core.logging_config`: JSON-lines rotating log, `setup_logging/StructuredLogger` (`event/debug/warning/error/command/check/confirmation/fix_applied/unresolved/action`), redaction, `source` field for web.

## 5. Security/offline/CSP audit (design conflicts to fix minimally in C)
| Item | Location | Issue | Minimal fix (preserve appearance) |
|---|---|---|---|
| Google Fonts (Inter) | `index.html:10-13` | External CDN, CSP/font-src violation | Bundle local `Inter` woff2 + `@font-face` in separate CSS loaded after main CSS |
| Chart.js CDN | `index.html:19` | External script, offline/CSP violation | Bundle Chart.js locally under `web/static/vendor/` |
| Dynamic `innerHTML` | `dashboard.js` (interfaces, devices, troubleshoot rail/stage/console, states/errors) | Attacker-influenced data (hostnames/SSIDs/names/adapter/output) | Replace with safe DOM/textContent/builders keeping same markup/classes/structure |
| Legacy endpoints/polling | `dashboard.js` fetches `/api/status,/api/devices,/api/packet-loss,/api/diagnostics*` | Not the new engine API; some main dashboard features (bandwidth/packet-loss/devices) not in build engine | Provide compatibility layer or map to existing modules/engine where possible; keep UI/behavior intact, flag gaps |
| `localStorage` aliases | `dashboard.js` | Browser-only device rename | Keep as UI-only (does not conflict with CLI-shared settings); log as UI action if needed |
| No token/CSP | current | Required by web server | Server enforces token/Host/Origin/CSP; JS must obtain session token and send header on POST/SSE-safe requests |

No `eval/new Function/document.write/inline onclick` found in scan. Keep class names, IDs, layout, copy, ordering.

## 6. Parity table 1 — tkinter GUI + build/CLI features → web UI (placement in main layout)
| Source feature (build/tkinter/CLI) | Web equivalent | Placement in main layout (existing element/pattern) | Status |
|---|---|---|---|
| tkinter: Run diagnosis (layers, progress) | Run diagnostics job via `/api/diagnose` + SSE, layer selection, live per-check status | TOOLS → `#view-troubleshoot` (existing Run/check controls + progress/stage) and/or Overview status actions using existing buttons/cards | pending C |
| tkinter: Findings list + detail (cause/evidence/fix_ids) | Findings list/detail views from engine results | TOOLS → troubleshoot rail/stage (existing `#check-steps`/`#diag-stage` patterns) | pending C |
| tkinter: Proceed to Fix + preview modal (exact cmds/admin/risk/reboot/snapshot/rollback) + dry-run | `/api/fix/plan` preview in modal using existing confirm/panel style; dry-run toggle | TOOLS → troubleshoot stage/modal pattern (existing confirm flow styling; add modal in separate file if none) | pending C |
| tkinter: Execute fix, stream output/timings/exit, re-check, ladder/unresolved | `/api/fix/execute` job + SSE; re-check/unresolved from outcome | TOOLS → troubleshoot console/stage | pending C |
| tkinter: Risk H second confirmation | Typed/explicit confirm, server `second_confirmation=true` | Modal/confirm in existing style | pending B/C |
| tkinter: Rollback, fix history | `/api/fix/rollback` + history list | TOOLS → troubleshoot/history area in existing panel patterns | pending B/C |
| tkinter: Likely causes panel + isolation (Yes/No/Not sure) re-rank | `/api/unresolved/answer`, probabilistic on/beyond device, next checks/evidence checklist | TOOLS → `#diag-stage`/collapsible panel in existing style | pending C |
| tkinter: Export report, View Logs | `/api/report` download + logs view `/api/logs`/stream/open-folder | TOOLS (logs/report panels) and/or existing action buttons | pending B/C |
| tkinter: Layer selection, admin status | layer selector UI, `/api/status` admin/elevate | existing controls/status chips | pending C |
| CLI/build: `diagnose` | same engine | TOOLS/Overview | pending C |
| CLI/build: `fix` (id/finding, dry-run/yes/risk/rollback/params) | plan/execute/rollback API | TOOLS | pending B/C |
| CLI/build: `info` | `/api/info` | TOOLS (network info panel/cards/tables in existing panel style) | pending B/C |
| CLI/build: `ping/trace/dns/arp/routes/ports/mtu` | `/api/tools/<name>` jobs + streaming output | TOOLS (subpanels/cards within troubleshoot/tools using existing stage/console patterns) | pending B/C |
| CLI/build: `logs` (tail/open/export/filter semantics) | `/api/logs`, `/api/logs/stream`, `/api/open-log-folder` | TOOLS | pending B/C |
| CLI/build: `report` | `/api/report` txt/json | TOOLS/Export | pending B/C |
| Build: packet-loss/QOL dashboard features on main | preserve via existing modules/endpoints or compatible mapping | Overview/Traffic/Devices/Packet-loss cards (existing) | pending C (must keep intact) |

## 7. Parity table 2 — main design elements with no build feature behind them
| Element | Location | Disposition |
|---|---|---|
| Bandwidth download/upload rates & traffic chart (psutil deltas) | Overview cards + `#traffic-chart` | Keep markup/rendering; back with existing `modules.bandwidth`/legacy-compatible data so main feature remains intact (not in core engine) — list as preserved main feature |
| Device discovery/ARP scan, vendor, rename aliases | Devices panel/table | Keep; back with existing `modules.device_scanner`/compat endpoints or equivalent, aliases remain localStorage UI-only |
| Legacy troubleshoot registry steps (`/api/diagnostics`) | Troubleshoot rail/stage | **Decision (confirmed):** re-back to build engine findings + fix catalog while preserving rail/stage/progress/confirm layout and appearance; legacy-only steps with no catalog equivalent left listed/hidden-not-invented as needed (flag in changelog) |

## 8. Parity table 3 — build features with no natural place in main layout
| Feature | Placement (closest existing pattern) | Note |
|---|---|---|
| CLI `install`/`uninstall` | Not UI actions (Phase 5/stubs) | Expose status/help text only if needed in Settings area; otherwise N/A |
| `monitor` live TUI mode | Covered by web live diagnose/progress | No separate UI page |
| PowerShell/CLM status detail | `/api/status` chip/text in existing status area | fits existing topbar/status |
| Raw ARP/routes tables as standalone CLI views | TOOLS subpanels/tables inside existing troubleshoot/info patterns | no new nav |

## 9. Phase C changelog plan (design files) — minimal diffs only
- `web/templates/index.html` (from main): remove external font/Chart.js CDNs, add local bundled assets and app bootstrap script/module includes in same positions/structure; keep all markup, classes, IDs, copy, order.
- `web/static/js/dashboard.js` (from main): refactor dynamic `innerHTML` to safe DOM helpers for attacker-influenced fields while preserving emitted structure/classes; swap data fetches to web API/compat endpoints; add token/header/heartbeat handling and SSE consumption; keep layout logic, chart/device/troubleshoot behaviors and appearance. Large but behavior-preserving refactor — will be split into modules if helpful (loaded in same order) and fully logged in changelog.
- `web/static/css/style.css` (from main): no rule edits/removals; any additions in separate `web/static/css/web-overrides.css` loaded after, only for states/components main lacks.
- New files: `web/static/vendor/chart.*.js`, `web/static/fonts/*`, `web/static/css/fonts.css`, `web/static/js/web-api.js` (etc.), `web/templates/base.html` (if extracting layout) — additive.

## 10. Confirmed decisions (user: “go ahead, 3 yeah in tools”)
- Tools/info/logs/report/CLI utilities placed inside existing **TOOLS/Troubleshoot** panels/patterns (no new nav/pages/regions).
- Re-back Troubleshoot to build engine + fix catalog, preserving layout/appearance; legacy-only elements without build backing listed for decision (not invented).

## 11. Remaining work by phase
- A: keep this doc updated as parity closes; produce final tables at delivery.
- B: single-instance lock/port file, polling fallback, full child-process cancel, Werkzeug log routing refinement, complete API/shape parity and comprehensive tests.
- C: Jinja base conversion (identical), bundle assets, safe DOM wiring, feature integration in main layout, compatibility for main dashboard features.
- D/E: lifecycle/packaging/build tests/exe size, remove tkinter, docs/CI/manual checklist, branch-safety and diff reports.
