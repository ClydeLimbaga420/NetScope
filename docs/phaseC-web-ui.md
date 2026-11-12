# Phase C web UI — design audit, changelog, parity notes

Scope: `feature/web-ui` / `phasec` work that integrates the build engine into
main's dashboard design without redesigning it. This file is the Phase C
deliverable for the design-file changelog, the offline/CSP audit, and the
"main elements with no build backing" list.

## Design files under main (ownership: design = main)

The following files are the design surface inherited from `main`. They were
kept in place; changes were limited to wiring, local/offline assets, state
hooks, and the shared design system already agreed in Session 41.

| File | What changed | Why |
| --- | --- | --- |
| `web/templates/base.html` | Split shell into sidebar + main + footer; added skip link, mobile topbar/drawer, SVG nav icons, admin-control slot, footer version/time, and includes for `_toast.html`; loads only local CSS/JS. | Reusable shell for the web UI; offline/CSP safe; no external URL. |
| `web/templates/index.html` | Page views for Monitoring, Troubleshoot and Repair Library; connection/stat cards; devices panel; engine-backed troubleshoot rail/stage; repair library list/detail. Header now uses `{% include "_page_header.html" %}`. | Keep main's layout/components while giving every build feature a home in existing regions. |
| `web/static/css/style.css` | Shared design-system stylesheet (tokens, cards, conn-grid, buttons, tables, drawer, breakpoints, reduced motion). Byte-identical to the legacy copy in `static/css/style.css`. | Single source of truth for main's visual language. |
| `web/static/js/dashboard.js` | Safe-DOM status/devices rendering, adapter pills, `data-live`, local Chart.js init, drawer heartbeat, null guards. | Preserve main's monitoring behavior using dynamic data without unsafe HTML sinks. |
| `templates/index.html` (legacy Flask) | Rewritten to the same shell markup (drawer, conn-grid, troubleshoot rail incl. `#repair-steps`, elevation badge, footer). | Keep the still-supported legacy dashboard visually aligned. |
| `static/css/style.css` (legacy) | Copy of the web stylesheet. | Legacy dashboard inherits the identical design system. |
| `static/js/dashboard.js` (legacy) | Adapter pills, `data-live`, `\u2715` markers, refresh-busy state, guarded Chart init, drawer IIFE, label-aware gateway button. | Legacy parity without changing its endpoints. |

### New design files (web-only, loaded after main CSS)

| File | Purpose |
| --- | --- |
| `web/templates/_page_header.html` | Reusable page header (eyebrow/title/subtitle + status block). |
| `web/templates/_status.html` | Reusable live-status block (`#top-status`, `#last-updated`, pulse). |
| `web/templates/_toast.html` | Reusable aria-live toast region (`#toast-region`). |
| `web/static/css/web-overrides.css` | Engine-view components layered after `style.css`: layers, evidence, output cards, fix facts, dialogs, tool panel, admin control, Repair Library, structured fix/unresolved results, info tables, toasts. |
| `web/static/js/engine-ui.js` | Engine-backed Troubleshoot/Repair Library wiring. |
| `web/static/js/job-stream.js` | SSE follow + polling fallback. |
| `web/static/js/web-init.js` | Session bootstrap, heartbeat, drawer, Toast API. |

## Offline / CSP audit

- Every stylesheet, script, font, and vendor file is served from `/static`
  (local); no CDN, Google Fonts, or remote script/style `<link>` exists.
- Templates contain only external scripts with `src=`; there are no inline
  `<script>` blocks, inline `on*=` handlers, or `style=` attributes.
- CSP is `default-src 'self'` with `script-src 'self'`, `style-src 'self'`,
  `img-src 'self' data:`, `font-src 'self'`, `connect-src 'self'`,
  `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`.
  Inline styles/scripts would therefore be blocked in a browser even if added
  by accident.
- Dynamic rendering in web JS uses `document.createElement`,
  `textContent`, `append`, and `replaceChildren`. There is no `innerHTML`,
  `document.write`, `eval`, or `new Function`.
- Jinja autoescape is enabled for `.html` templates; a dynamic value in the
  shell (for example the version string) is escaped. Tests cover this
  explicitly.
- SVG favicon and CSS chevrons use `data:` URLs; the only `http://` string in
  JS is the SVG namespace constant, not a network fetch.

## Build-feature parity notes

Mapped into main's existing regions:

- Monitoring: `/api/status`, `/api/devices`, packet-loss polling, connectivity
  dots, adapter list, traffic chart (legacy main behavior kept).
- Troubleshoot: layer selection, `/api/checks` planned list, engine diagnosis
  with per-check SSE/polling fallback, findings/evidence, fix planning,
  dry-run, high-risk typed confirmation, live fix outcome with steps,
  durations, re-check and rollback, unresolved isolation question with ranked
  causes/next checks/evidence, utility jobs (ping/trace/dns/arp/routes/ports/
  mtu), network info tables with copy/refresh, logs, report export, fix history.
- Repair Library: full catalog list, search, procedure (steps, exact commands,
  verification, rollback, if-unresolved), link from Troubleshoot.
- Admin: status badge, non-admin hint, UAC restart; admin-only repairs labelled.

Main elements with no build feature backing are left as-is:

- Traffic chart and speed/packet-loss cards (main dashboard data, not part of
  the build engine).
- Device discovery table and rename overrides (main feature, uses
  `modules/network_info`/ARP discovery, not the engine).
- Connection card values come from `/api/status` (main dashboard payload);
  build `info` data is shown separately under Network info.

Build features intentionally not placed as new navigation:

- CLI-only `monitor`, shell, install/uninstall surfaces have no dedicated web
  view; their web-safe equivalents (status polling, tools, logs, report) live in
  existing Troubleshoot/Tools regions.
- No build "settings" surface exists, so no settings page/section was invented.

## Verification

- Full pytest suite covers shell rendering/local assets, autoescape, offline
  asset rules, unsafe DOM sinks, design tokens/breakpoints, shared stylesheet
  identity, and this changelog's required files.
- `node --check` passes for all `web/static/js` files.
- Browser end-to-end flows remain the last Phase C verification item.
