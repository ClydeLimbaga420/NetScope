from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
TEMPLATES = sorted((WEB / "templates").glob("*.html"))
SCRIPTS = sorted((WEB / "static" / "js").glob("*.js"))
STYLES = sorted((WEB / "static" / "css").glob("*.css"))


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_web_templates_have_no_inline_scripts_or_handlers():
    for path in TEMPLATES:
        source = text(path)
        assert not re.search(r"<script(?![^>]*\bsrc=)", source, re.I), path
        assert not re.search(r"\son[a-z]+\s*=", source, re.I), path
        assert not re.search(r"\sstyle\s*=", source, re.I), path


def test_web_templates_reference_only_local_asset_urls():
    for path in TEMPLATES:
        source = text(path)
        assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', source, re.I), path


def test_web_assets_are_offline_safe():
    forbidden_hosts = (
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdn.jsdelivr.net",
        "unpkg.com",
        "code.jquery.com",
        "ajax.googleapis.com",
    )
    for path in [*TEMPLATES, *STYLES, *SCRIPTS]:
        source = text(path).lower()
        for host in forbidden_hosts:
            assert host not in source, f"{path} references {host}"


def test_web_scripts_avoid_unsafe_dom_sinks():
    unsafe = re.compile(r"\.innerHTML\s*=|document\.write\s*\(|new\s+Function\s*\(|\beval\s*\(")
    for path in SCRIPTS:
        assert not unsafe.search(text(path)), path


def test_monitoring_ui_distinguishes_pending_and_api_errors():
    source = text(WEB / "static" / "js" / "dashboard.js")
    assert source.count("response.status === 202") >= 2
    assert "data.error && data.error.message" in source
    assert "Packet loss test is still running..." in source
    assert "Scanning local network and resolving names..." in source


def test_traffic_chart_flows_continuously():
    source = text(WEB / "static" / "js" / "dashboard.js")
    # Low-request cadence: fewer /api/status calls and a stepped (unanimated)
    # trace on low-end machines instead of a continuous five-second animation.
    assert "STATUS_POLL_INTERVAL_MS = 15000" in source
    assert "TRAFFIC_HISTORY_LENGTH = 40" in source
    assert "SMOOTHING_FACTOR = 0.28" in source
    assert "duration: 0" in source
    assert "setInterval(refreshStatus, STATUS_POLL_INTERVAL_MS)" in source
    assert "labels.length > TRAFFIC_HISTORY_LENGTH" in source
    # The glowing tip of each live trace.
    assert 'id: "livePoint"' in source
    assert "plugins: [livePointPlugin]" in source
    # Long-running polls must not overlap, and a restored tab must redraw now.
    assert "let statusInFlight = false" in source
    assert "if (statusInFlight) {" in source
    assert "statusInFlight = false;" in source
    assert "new AbortController()" in source
    assert "controller.abort()" in source
    assert "window.clearTimeout(statusTimeout)" in source
    assert 'addEventListener("visibilitychange"' in source
    assert 'chart.update("none")' in source
    assert "lastTrafficSampleAt" in source
    assert "Keep the chart moving when a status poll is skipped" in source


def test_traffic_chart_stays_visible_when_disconnected():
    source = text(WEB / "static" / "js" / "dashboard.js")
    # An idle/zero trace must stay on screen instead of blending into the axis.
    assert "const TRAFFIC_FLOOR_MBPS = 0.05;" in source
    assert "const TRAFFIC_MIN_CEILING_MBPS = 1;" in source
    assert "function visibleTraffic(value)" in source
    assert "suggestedMax: TRAFFIC_MIN_CEILING_MBPS" in source
    assert "function pushTrafficSample(download, upload)" in source
    # Tooltips still report the real rate, not the plotted floor.
    assert "const realDownloads = []" in source
    assert "context.datasetIndex === 0" in source
    # Every poll, including failed ones, keeps the rolling trace alive.
    assert "pushTrafficSample(smoothedDownload, smoothedUpload)" in source
    assert "pushTrafficSample(0, 0)" in source
    assert "realDownloads.shift()" in source


def test_traffic_chart_skips_overlapping_status_polls():
    source = text(WEB / "static" / "js" / "dashboard.js")
    guard = source.index("if (statusInFlight) {")
    fetch = source.index('fetch("/api/status", options)')
    finally_block = source.index("finally {", fetch)
    assert guard < fetch < finally_block


def test_traffic_chart_recovers_from_session_expiry_and_idle_stalls():
    source = text(WEB / "static" / "js" / "dashboard.js")

    # Request setup must be inside the try so a throw cannot leak the guard.
    in_flight = source.index("statusInFlight = true;")
    try_block = source.index("try {", in_flight)
    controller = source.index("const controller =", in_flight)
    assert try_block < controller

    # A 401 must still contribute a sample instead of returning early.
    expired = source.index("if (response.status === 401) {")
    next_check = source.index("if (!response.ok) {", expired)
    assert "pushTrafficSample(0, 0)" in source[expired:next_check]

    assert "const STATUS_ABORT_TIMEOUT_MS = Math.min(6000, STATUS_POLL_INTERVAL_MS - 1000)" in source
    fetch = source.index("const response = await fetch", try_block)
    assert "STATUS_ABORT_TIMEOUT_MS" in source[try_block:fetch]

    # Once traffic stops, the y ceiling must shrink to the idle range so the
    # floored line stays a visible fraction of the plot after an earlier peak.
    assert "function updateTrafficCeiling(download, upload)" in source
    assert "chart.options.scales.y.max = trafficCeiling" in source
    assert "updateTrafficCeiling(download, upload);" in source
    assert "max: TRAFFIC_MIN_CEILING_MBPS," in source
    assert "TRAFFIC_DROP_FACTOR" in source


def test_dashboard_pauses_polling_in_background_tabs():
    source = text(WEB / "static" / "js" / "dashboard.js")
    # A hidden dashboard should not keep spawning status/packet-loss work.
    assert 'if (document.visibilityState === "hidden") {' in source
    assert "setInterval(refreshPacketLoss, PACKET_LOSS_POLL_INTERVAL_MS)" in source
    assert "setInterval(heartbeat, 20000)" in text(WEB / "static" / "js" / "web-init.js")
    visible = source.index('addEventListener("visibilitychange"')
    section = source[visible : visible + 500]
    assert "refreshStatus();" in section
    assert "refreshPacketLoss();" in section
    assert "lastStatusRequestAt" in section


def test_visibility_refresh_uses_packet_loss_poll_interval():
    source = text(WEB / "static" / "js" / "dashboard.js")
    assert "PACKET_LOSS_POLL_INTERVAL_MS = 180000" in source
    visible = source.index('addEventListener("visibilitychange"')
    section = source[visible : visible + 600]
    assert "lastPacketLossRequestAt >= PACKET_LOSS_POLL_INTERVAL_MS" in section


def test_status_card_has_freshness_badge():
    source = text(WEB / "templates" / "index.html")
    badge = re.search(r'<span[^>]*id="data-freshness"[^>]*>', source)
    assert badge
    assert 'role="status"' in badge.group(0)
    assert 'aria-live="polite"' in badge.group(0)
    assert "Checking data\u2026" in source
    assert not re.search(r"\son[a-z]+\s*=", source, re.I), source


def test_dashboard_js_maps_freshness_states():
    source = text(WEB / "static" / "js" / "dashboard.js")
    assert "data_freshness" in source
    assert "Showing saved data" in source
    assert "Gathering data\u2026" in source
    assert "Limited data \\u00b7 Retrying\\u2026" in source
    assert re.search(r"freshnessBadge\.textContent\s*=", source)


def test_dashboard_js_shows_pending_connectivity_without_claiming_outage():
    source = text(WEB / "static" / "js" / "dashboard.js")
    assert "function pingState(ping)" in source
    assert 'internetState === "pending" ? "Checking\\u2026"' in source
    assert 'gatewayState === "pending" ? "Checking\\u2026"' in source
    assert 'setStatus("internet-dot", internetState)' in source
    assert 'setStatus("gateway-dot", gatewayState)' in source


def test_web_scripts_remove_legacy_diagnostics_and_handler_workarounds():
    dashboard = text(WEB / "static" / "js" / "dashboard.js")
    engine_ui = text(WEB / "static" / "js" / "engine-ui.js")

    assert "/api/diagnostics" not in dashboard
    assert "cloneNode(true)" not in engine_ui
    assert "MutationObserver" not in engine_ui


def test_standalone_dashboard_and_legacy_modules_are_removed():
    for relative_path in ("app.py", "templates", "static", "modules"):
        assert not (ROOT / relative_path).exists(), relative_path

    source_dirs = ("core", "cli", "fixes", "powershell", "scripts", "tests", "web")
    python_files = [*ROOT.glob("*.py")]
    for directory in source_dirs:
        python_files.extend((ROOT / directory).rglob("*.py"))
    legacy_import = re.compile(
        r"^\s*(?:from\s+modules\b|import\s+modules\b|import\s+app\b)",
        re.M,
    )
    for path in python_files:
        assert not legacy_import.search(text(path)), path

    spec = text(ROOT / "NetScope.spec")
    assert '(str(core / "oui_vendors.json"), "core")' in spec
    assert '"modules.' not in spec


def test_project_docs_describe_the_supported_localhost_ui():
    readme = text(ROOT / "README.md").lower()
    run_guide = text(ROOT / "docs" / "run.md").lower()
    manual = text(ROOT / "docs" / "manual-test-checklist.md").lower()
    known = text(ROOT / "docs" / "known-unverified.md").lower()
    changelog = text(ROOT / "docs" / "phaseC-web-ui.md").lower()

    for source in (readme, run_guide, manual):
        assert "python app.py" not in source
        assert "http://<lan-ip>:5000" not in source
    assert "legacy dashboard" not in readme
    assert "legacy `app.py` dashboard is still unauthenticated" not in known
    assert "phase 5 removal note" in changelog
    assert "localhost web ui" in readme


def test_design_tokens_and_breakpoints_are_preserved():
    css = text(WEB / "static" / "css" / "style.css")
    for marker in (
        "--bg:",
        "--accent:",
        "--sidebar-w:",
        ".conn-grid",
        "grid-column: 1 / -1",
        "repeat(4, minmax(0, 1fr))",
        "@media (max-width: 1180px)",
        "prefers-reduced-motion",
        '.top-status[data-live="true"]',
    ):
        assert marker in css, marker


def test_new_engine_components_stay_in_overrides_not_shared_stylesheet():
    shared = text(WEB / "static" / "css" / "style.css")
    overrides = text(WEB / "static" / "css" / "web-overrides.css")
    for selector in (
        ".toast-region",
        ".engine-info-table",
        ".engine-cause-tag",
        ".engine-step",
        ".engine-history-row",
        ".engine-log-row",
        ".engine-progress-track",
        ".layer-status-grid",
        ".layer-status-value",
    ):
        assert selector not in shared, selector
        assert selector in overrides, selector


def test_shell_local_assets_exist():
    names = re.findall(r"filename=['\"]([^'\"]+)['\"]", text(WEB / "templates" / "base.html"))
    assert names
    for name in names:
        assert (WEB / "static" / name).is_file(), name


def test_engine_ui_renders_structured_results_safely():
    source = text(WEB / "static" / "js" / "engine-ui.js")
    for token in (
        "function renderUnresolved",
        "function renderFixOutcome",
        "function renderFixHistory",
        "function renderLogs",
        "function renderFixProgress",
        "function showInfo",
        "function renderLayerStatus",
        "layer-status-grid",
        "state.activeLayers.includes(layer)",
        "SPEED TEST RESULT",
        "function runSpeedTest",
        "createSpeedTestMetrics",
        "/api/tools/speedtest",
        "speed.cloudflare.com",
        "speed-test-metric",
        "engine-info-table",
        "function toast",
        "fix_progress",
    ):
        assert token in source, token
    assert "textContent" in text(WEB / "static" / "js" / "web-init.js")


def test_fix_outcome_copy_is_inset_from_card_edges():
    styles = text(WEB / "static" / "css" / "web-overrides.css")
    rule = re.search(r"\.engine-output\s*>\s*\.diag-desc[^}]*\}", styles, re.S)
    assert rule is not None
    assert "margin-left: 14px" in rule.group(0)
    assert "margin-right: 14px" in rule.group(0)


def test_admin_restart_has_a_branded_progress_dialog():
    source = text(WEB / "static" / "js" / "engine-ui.js")
    styles = text(WEB / "static" / "css" / "web-overrides.css")
    shared_styles = text(WEB / "static" / "css" / "style.css")
    badge_rule = re.search(r"\.elevation-badge\s*\{(.*?)\}", shared_styles, re.S)
    assert badge_rule is not None
    assert "justify-content: center" in badge_rule.group(1)
    for token in (
        "function createElevationDialog",
        "Waiting for Windows approval",
        "Starting administrator session",
        "Switching now...",
        "elevation-dialog-status",
        'window.location.replace(status.url)',
    ):
        assert token in source, token
    for token in (
        ".elevation-dialog",
        ".elevation-dialog-status",
        ".elevation-dialog-spinner",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert token in styles, token


def test_design_changelog_records_phase_c_files():
    doc = ROOT / "docs" / "phaseC-web-ui.md"
    assert doc.is_file()
    changelog = text(doc)
    for token in (
        "web/templates/base.html",
        "web/templates/index.html",
        "web/templates/_page_header.html",
        "web/templates/_status.html",
        "web/templates/_toast.html",
        "web/static/css/web-overrides.css",
        "web/static/js/engine-ui.js",
        "web/static/js/web-init.js",
        "templates/index.html",
        "static/css/style.css",
        "static/js/dashboard.js",
    ):
        assert token in changelog, token
