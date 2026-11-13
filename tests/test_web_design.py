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


def test_shared_stylesheet_matches_legacy_copy():
    assert (WEB / "static" / "css" / "style.css").read_bytes() == (
        ROOT / "static" / "css" / "style.css"
    ).read_bytes()


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
