(function () {
  const $ = (id) => document.getElementById(id);
  const state = { checks: [], fixes: [], selectedId: null, report: null, jobId: null, busy: false, admin: null, libraryId: null, detail: null, adminNotice: "", checksLoaded: false, repairQuery: "", singleCheckId: null, activeLayers: [] };
  const layers = ["adapter", "services", "ip", "gateway", "lan", "dns", "internet", "stack"];
  const layerLabels = {
    adapter: "Adapter",
    services: "Network services",
    ip: "IP configuration",
    gateway: "Gateway",
    lan: "Local network",
    dns: "DNS",
    internet: "Internet",
    stack: "TCP/IP stack",
  };
  const SVG_NS = "http://www.w3.org/2000/svg";

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function svgIcon(paths, size) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    (Array.isArray(paths) ? paths : [paths]).forEach((d) => {
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      svg.append(path);
    });
    if (size) {
      svg.style.width = `${size}px`;
      svg.style.height = `${size}px`;
    }
    return svg;
  }

  function emptyState(title, hint, paths) {
    const box = element("div", "empty-state");
    box.append(svgIcon(paths || ["M12 8v5", "M12 16.5v.01", "M10.3 3.9 2.8 17a1.6 1.6 0 0 0 1.4 2.4h15.6a1.6 1.6 0 0 0 1.4-2.4L13.7 3.9a1.6 1.6 0 0 0-2.8 0z"]));
    box.append(element("h4", "", title));
    box.append(element("p", "", hint));
    return box;
  }

  function fixFact(label, value, modifier) {
    const chip = element("li", ["fix-fact", modifier || ""].filter(Boolean).join(" "));
    chip.append(element("b", "", label), document.createTextNode(value));
    return chip;
  }

  function renderFixFacts(target, admin, risk, reboot) {
    const level = String(risk || "unknown").toLowerCase();
    const facts = element("ul", "engine-fix-facts");
    facts.append(fixFact("Admin", admin ? "Required" : "Not required", admin ? "is-warn" : ""));
    facts.append(fixFact("Risk", String(risk || "unknown"), level === "high" ? "is-danger" : level === "medium" ? "is-warn" : ""));
    facts.append(fixFact("Restart", reboot ? "May be required" : "Not expected", reboot ? "is-warn" : ""));
    target.append(facts);
  }

  function visibleText(value) {
    if (value === null || value === undefined || value === false) return "";
    const text = Array.isArray(value) ? value.join(", ") : String(value);
    return text.trim() ? text : "";
  }

  function setButtonLabel(button, text) {
    const label = button.querySelector(".btn-label");
    if (label) label.textContent = text;
    else button.textContent = text;
  }

  async function waitForSession() {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (window.__netscope && window.__netscope.ready) return;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error("The secure web session is not ready. Reload the page and try again.");
  }

  async function api(url, options) {
    const opts = options || {};
    if (opts.method && opts.method.toUpperCase() !== "GET") await waitForSession();
    const response = await fetch(url, opts);
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        message = body.error && body.error.message ? body.error.message : message;
      } catch (_error) { }
      throw new Error(message);
    }
    return response.json();
  }

  function setBusy(busy, label, redraw) {
    state.busy = busy;
    const run = $("run-engine-diagnosis");
    if (run) {
      run.disabled = busy;
      setButtonLabel(run, busy ? (label || "Running...") : "Run diagnosis");
    }
    const cancel = $("engine-cancel-job");
    if (cancel) cancel.disabled = !busy || !state.jobId;
    const gateway = $("auto-configure-gateway");
    if (gateway) gateway.disabled = busy;
    const adminButton = $("run-as-admin");
    if (adminButton) adminButton.disabled = busy;
    ["check-steps", "repair-steps"].forEach((id) => {
      const rail = $(id);
      if (rail) rail.classList.toggle("engine-busy", busy);
    });
    if (redraw !== false) render();
  }

  function renderAdminState() {
    const elevated = state.admin === true;
    const runAsAdmin = $("run-as-admin");
    const badge = $("admin-mode-badge");
    const hint = $("admin-hint");
    const notice = $("admin-notice");
    const libraryBadge = $("repair-elevation-badge");
    const libraryButton = $("repair-run-as-admin");
    if (runAsAdmin) runAsAdmin.hidden = state.admin !== false;
    if (badge) badge.hidden = !elevated;
    if (hint) hint.hidden = state.admin !== false;
    if (libraryBadge) {
      libraryBadge.hidden = !elevated;
      libraryBadge.textContent = elevated ? "ADMINISTRATOR" : "";
    }
    if (libraryButton) libraryButton.hidden = state.admin !== false;
    if (notice) {
      notice.hidden = !state.adminNotice;
      notice.textContent = state.adminNotice;
    }
  }

  async function loadAdminStatus() {
    try {
      const status = await api("/api/status");
      state.admin = Boolean(status.admin);
    } catch (_error) {
      state.admin = null;
    }
    renderAdminState();
  }

  async function requestElevation() {
    if (state.busy) return;
    if (!window.confirm("Restart NetScope as administrator? Windows will show a UAC prompt and this page will disconnect.")) return;
    state.adminNotice = "Requesting administrator rights...";
    renderAdminState();
    try {
      await api("/api/elevate", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      state.adminNotice = "Restarting as administrator... This page will disconnect.";
    } catch (error) {
      state.adminNotice = error.message;
    }
    renderAdminState();
  }

  function statusClass(status) {
    if (["pass", "resolved", "success", "done"].includes(status)) return "success";
    if (["fail", "error", "warn", "warning", "cancelled"].includes(status)) return "error";
    if (status === "running") return "running";
    return "idle";
  }

  function resultTitle(check) {
    return check.title || check.id || "Diagnostic check";
  }

  function idMatches(resultId, checkId) {
    return resultId === checkId || String(resultId).startsWith(`${checkId}-`);
  }

  function renderRail(container, items, kind) {
    container.replaceChildren();
    if (!items.length) {
      container.append(emptyState(
        kind === "repair" ? "No repairs in this run" : "No checks yet",
        kind === "repair"
          ? "Repairs appear when a diagnosis finds something a catalog fix can address."
          : "Choose layers and run a diagnosis to inspect every check."
      ));
      return;
    }
    items.forEach((item, index) => {
      const running = item.status === "running";
      const status = statusClass(item.status);
      const row = element("div", ["diag-row", running ? "running" : ""].filter(Boolean).join(" "));
      const button = element("button", `diag-item ${kind} ${status}${item.id === state.selectedId ? " selected" : ""}`);
      button.type = "button";
      button.dataset.engineItem = item.id;
      const marker = status === "success" ? "\u2713" : status === "error" ? "\u2715" : status === "running" ? "\u2026" : String(index + 1).padStart(2, "0");
      const number = element("span", "diag-item-index", marker);
      const text = element("span", "diag-item-text");
      text.append(element("strong", "", resultTitle(item)));
      text.append(element("small", "diag-item-desc", item.description || item.status || (kind === "repair" ? item.risk : item.layer)));
      button.append(number, text);
      const runButton = element("button", ["diag-item-run", running ? "running" : ""].filter(Boolean).join(" "));
      runButton.type = "button";
      runButton.dataset.runItem = item.id;
      runButton.textContent = running ? "Running" : "Run";
      runButton.title = running ? "Running this check..." : `Run check: ${resultTitle(item)}`;
      row.append(button, runButton);
      container.append(row);
    });
  }

  function renderEvidence(target, value) {
    if (!value || (typeof value === "object" && !Object.keys(value).length)) return;
    const title = element("p", "diag-command-label", "EVIDENCE");
    const pre = element("pre", "engine-evidence", JSON.stringify(value, null, 2));
    target.append(title, pre);
  }

  function toast(message, kind) {
    if (window.NetScope && typeof window.NetScope.toast === "function") {
      window.NetScope.toast(message, kind);
    }
  }

  function syncCancelState() {
    const cancel = $("engine-cancel-job");
    if (cancel) cancel.disabled = !state.busy || !state.jobId;
  }

  function downloadJson(filename, value) {
    const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 0);
  }

  function cardHead(title, text) {
    const head = element("div", "engine-output-head");
    head.append(element("span", "", title));
    const copy = element("button", "ghost-button engine-copy", "Copy");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        copy.textContent = "Copied";
        toast("Copied to clipboard", "success");
        window.setTimeout(() => { copy.textContent = "Copy"; }, 1800);
      } catch (_error) {
        toast("Clipboard is unavailable in this browser", "error");
      }
    });
    const save = element("button", "ghost-button engine-copy", "Export");
    save.type = "button";
    save.addEventListener("click", () => {
      try {
        downloadJson("netscope-output.json", JSON.parse(text));
        toast("Saved netscope-output.json", "success");
      } catch (_error) {
        toast("This output could not be exported", "error");
      }
    });
    head.append(copy, save);
    return head;
  }

  function renderUnresolved(section, target) {
    if (!section) return null;
    const wrapper = element("div", "engine-unresolved");
    wrapper.append(element("p", "diag-command-label", "IF THIS DID NOT HELP"));
    const card = element("div", "engine-output");
    card.append(element("div", "engine-output-head", "LIKELY CAUSES"));
    if (section.reason) card.append(element("p", "diag-desc", section.reason));
    if (section.wording) card.append(element("p", "muted", section.wording));
    [
      ["this_device", "On this device"],
      ["beyond_device", "Beyond this device"],
    ].forEach(([key, label]) => {
      const causes = section[key] || [];
      if (!causes.length) return;
      const group = element("div", "engine-cause-group");
      group.append(element("p", "diag-command-label", label.toUpperCase()));
      causes.forEach((cause) => {
        const row = element("div", "engine-cause");
        const tag = element("span", `engine-cause-tag ${cause.likelihood === "probable" ? "probable" : ""}`, cause.likelihood || "possible");
        row.append(tag, element("span", "", cause.cause || ""));
        group.append(row);
      });
      card.append(group);
    });
    listSection(card, "NEXT CHECKS", section.next_checks);
    listSection(card, "EVIDENCE TO COLLECT", section.evidence_to_collect);
    wrapper.append(card);
    target.append(wrapper);
    return wrapper;
  }

  function renderFixOutcome(outcome, elapsedMs) {
    const stage = $("diag-stage");
    if (!stage) return;
    outcome = outcome || {};
    stage.replaceChildren();
    const card = element("div", "engine-output");
    card.append(cardHead(`FIX ${String(outcome.status || "result").toUpperCase()}`, JSON.stringify(outcome, null, 2)));
    const meta = element("div", "engine-result-meta");
    meta.append(fixFact("Status", outcome.status || "unknown"));
    meta.append(fixFact("Exit code", String(outcome.exit_code == null ? "\u2014" : outcome.exit_code)));
    if (elapsedMs != null) meta.append(fixFact("Duration", `${(elapsedMs / 1000).toFixed(1)} s`));
    if (outcome.dry_run) meta.append(fixFact("Mode", "Dry run"));
    card.append(meta);
    if (outcome.message) card.append(element("p", "diag-desc", outcome.message));
    if (outcome.error) card.append(element("p", "step-reason error", outcome.error));
    const steps = outcome.steps || [];
    if (steps.length) {
      const section = element("div", "repair-section");
      section.append(element("p", "diag-command-label", "STEPS"));
      steps.forEach((step, index) => {
        const row = element("div", "engine-step");
        const head = element("div", "engine-step-head");
        head.append(element("span", "repair-step-number", String((step.index == null ? index : step.index) + 1).padStart(2, "0")));
        head.append(element("strong", "", step.name || `Step ${index + 1}`));
        head.append(element("span", `engine-step-status ${statusClass(step.status)}`, step.status || ""));
        row.append(head);
        if (step.description) row.append(element("p", "engine-step-desc", step.description));
        (step.commands || []).forEach((command) => row.append(renderCommand(command)));
        if (step.verification) row.append(element("pre", "engine-evidence", JSON.stringify(step.verification, null, 2)));
        section.append(row);
      });
      card.append(section);
    }
    if (outcome.verification) {
      const section = element("div", "repair-section");
      section.append(element("p", "diag-command-label", "RE-CHECK"));
      section.append(element("pre", "engine-evidence", JSON.stringify(outcome.verification, null, 2)));
      card.append(section);
    }
    stage.append(card);
    if (outcome.rollback_available && outcome.fix_id) {
      const rollback = element("button", "ghost-button", "Roll back this fix");
      rollback.type = "button";
      rollback.dataset.rollbackId = outcome.fix_id;
      stage.append(rollback);
    }
    if (outcome.unresolved) renderUnresolved(outcome.unresolved, stage);
    renderToolPanel(stage);
  }

  function formatWhen(value) {
    if (!value) return "\u2014";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  function renderFixHistory(entries) {
    const stage = $("diag-stage");
    if (!stage) return;
    entries = entries || [];
    stage.replaceChildren();
    const card = element("div", "engine-output");
    card.append(cardHead("FIX HISTORY", JSON.stringify({ history: entries }, null, 2)));
    card.append(element(
      "p",
      "diag-desc",
      `${entries.length} saved snapshot${entries.length === 1 ? "" : "s"}. The newest snapshot for each fix is used for rollback.`
    ));
    if (!entries.length) {
      card.append(emptyState(
        "No fixes recorded yet",
        "Run a fix from the Repair Library or Troubleshoot to create a rollback snapshot."
      ));
    } else {
      const list = element("div", "engine-history");
      const seen = new Set();
      entries.forEach((item) => {
        const row = element("div", "engine-history-row");
        row.append(element("span", "engine-history-time", formatWhen(item.captured_at)));
        const body = element("div", "engine-history-body");
        const title = element("div", "engine-history-title");
        title.append(element("span", "engine-history-badge", item.fix_id || "?"));
        title.append(element("strong", "", item.name || item.fix_id || "Saved snapshot"));
        body.append(title);
        body.append(element(
          "span",
          "engine-history-meta",
          item.rollback_available ? "Rollback available" : "Rollback unavailable"
        ));
        row.append(body);
        if (item.fix_id && !seen.has(item.fix_id)) {
          seen.add(item.fix_id);
          const rollback = element("button", "ghost-button engine-history-rollback");
          rollback.type = "button";
          rollback.dataset.rollbackId = item.fix_id;
          rollback.append(svgIcon("M3 12a9 9 0 1 0 2.6-6.3L3 8", 12), element("span", "btn-label", "Roll back"));
          row.append(rollback);
        } else {
          row.append(element("span", "engine-history-older", "older snapshot"));
        }
        list.append(row);
      });
      card.append(list);
    }
    stage.append(card);
    renderToolPanel(stage);
  }

  function logFieldSummary(fields) {
    if (!fields || typeof fields !== "object") return "";
    const keys = ["message", "action", "method", "path", "status", "reason", "error", "fix_id", "step"];
    const parts = [];
    keys.forEach((key) => {
      const value = fields[key];
      if (value !== undefined && value !== null && value !== "") {
        parts.push(`${key}: ${formatValue(value)}`);
      }
    });
    if (parts.length) return parts.join(" \u00b7 ");
    const text = JSON.stringify(fields);
    return text.length > 240 ? `${text.slice(0, 237)}...` : text;
  }

  function renderLogs(payload) {
    const stage = $("diag-stage");
    if (!stage) return;
    const entries = ((payload && payload.entries) || []).slice().reverse();
    stage.replaceChildren();
    const card = element("div", "engine-output");
    card.append(cardHead("RECENT LOGS", JSON.stringify(payload, null, 2)));
    card.append(element(
      "p",
      "diag-desc",
      `${entries.length} recent entr${entries.length === 1 ? "y" : "ies"}${payload && payload.path ? ` \u00b7 ${payload.path}` : ""}`
    ));
    if (!entries.length) {
      card.append(emptyState("No log entries yet", "Actions appear here as you use NetScope."));
    } else {
      const list = element("div", "engine-log-list");
      entries.forEach((entry) => {
        const row = element("div", "engine-log-row");
        const head = element("div", "engine-log-head");
        head.append(element("span", "engine-log-time", formatWhen(entry.ts)));
        const level = String(entry.level || "INFO").toUpperCase();
        head.append(element("span", `engine-log-level ${level.toLowerCase()}`, level));
        head.append(element("strong", "engine-log-event", entry.event || "(event)"));
        head.append(element("span", "engine-log-logger", entry.logger || ""));
        row.append(head);
        const summary = logFieldSummary(entry.fields);
        if (summary) row.append(element("p", "engine-log-fields", summary));
        list.append(row);
      });
      card.append(list);
    }
    stage.append(card);
    renderToolPanel(stage);
  }

  function formatValue(value) {
    if (value == null || value === "") return "\u2014";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function infoTable(target, label, columns, rows) {
    const section = element("div", "repair-section");
    section.append(element("p", "diag-command-label", label));
    if (!rows || !rows.length) {
      section.append(element("p", "engine-info-empty", "None reported."));
      target.append(section);
      return;
    }
    const table = element("table", "engine-info-table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    columns.forEach((column) => headRow.append(element("th", "", column.label)));
    head.append(headRow);
    const body = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      columns.forEach((column) => {
        const value = typeof column.value === "function" ? column.value(row) : formatValue(row[column.key]);
        tr.append(element("td", "", value == null || value === "" ? "\u2014" : value));
      });
      body.append(tr);
    });
    table.append(head, body);
    section.append(table);
    target.append(section);
  }

  function renderInfoBody(target, info) {
    target.replaceChildren();
    const summary = element("div", "info-list");
    [["Hostname", info.hostname], ["Default gateway", info.gateway], ["Captured", info.captured_at]].forEach(([label, value]) => {
      const row = document.createElement("div");
      row.append(element("span", "", label), element("strong", "", formatValue(value)));
      summary.append(row);
    });
    target.append(summary);
    infoTable(target, "NETWORK ADAPTERS", [
      { label: "Adapter", value: (row) => row.name || row.alias },
      { label: "Status", value: (row) => row.status },
      { label: "IPv4", value: (row) => (row.ipv4 || []).map((item) => `${item.address}/${item.prefix}`).join(", ") },
      { label: "Gateway", value: (row) => row.gateway },
      { label: "MAC", value: (row) => row.mac },
      { label: "MTU", value: (row) => row.mtu },
    ], info.adapters);
    infoTable(target, "ROUTES", [
      { label: "Destination", value: (row) => row.DestinationPrefix },
      { label: "Next hop", value: (row) => row.NextHop },
      { label: "Interface", value: (row) => row.InterfaceAlias },
      { label: "Metric", value: (row) => row.RouteMetric },
    ], info.routes);
    infoTable(target, "ARP / NEIGHBORS", [
      { label: "IP", value: (row) => row.ip },
      { label: "MAC", value: (row) => row.mac },
      { label: "Type", value: (row) => row.type },
    ], info.arp);
    infoTable(target, "DNS SERVERS", [
      { label: "Server", value: (row) => row },
    ], info.dns_servers);
    if (info.proxy) {
      const section = element("div", "repair-section");
      section.append(element("p", "diag-command-label", "PROXY"));
      section.append(element("pre", "engine-evidence", JSON.stringify(info.proxy, null, 2)));
      target.append(section);
    }
    infoTable(target, "VPN CONNECTIONS", [
      { label: "Name", value: (row) => row.Name },
      { label: "Server", value: (row) => row.ServerAddress },
      { label: "Status", value: (row) => row.ConnectionStatus },
    ], info.vpn);
    if (info.wifi && Object.keys(info.wifi).length) {
      const section = element("div", "repair-section");
      section.append(element("p", "diag-command-label", "WI-FI"));
      section.append(element("pre", "engine-evidence", JSON.stringify(info.wifi, null, 2)));
      target.append(section);
    }
    if (info.mtu && Object.keys(info.mtu).length) {
      infoTable(target, "MTU", [
        { label: "Interface", value: (row) => row.interface },
        { label: "MTU", value: (row) => row.mtu },
      ], Object.entries(info.mtu).map(([name, mtu]) => ({ interface: name, mtu })));
    }
  }

  function showInfo(info, refresh) {
    const stage = $("diag-stage");
    if (!stage) return;
    stage.replaceChildren();
    const card = element("div", "engine-output");
    const text = JSON.stringify(info, null, 2);
    const head = cardHead("NETWORK INFO", text);
    const refreshButton = element("button", "ghost-button engine-copy", "Refresh");
    refreshButton.type = "button";
    refreshButton.addEventListener("click", () => refresh());
    head.append(refreshButton);
    card.append(head);
    const body = element("div", "engine-info");
    renderInfoBody(body, info);
    card.append(body);
    stage.append(card);
    renderToolPanel(stage);
  }

  function showNetworkInfo() {
    return api("/api/info").then((info) => showInfo(info, showNetworkInfo)).catch((error) => {
      toast("Network info unavailable", "error");
      showOutput("NETWORK INFO ERROR", { error: error.message });
    });
  }

  function renderFixActions(target, ids) {
    const fixes = ids.map((id) => state.fixes.find((fix) => fix.id === id)).filter(Boolean);
    if (!fixes.length) return;
    const group = element("div", "engine-fix-actions");
    group.append(element("p", "diag-command-label", "AVAILABLE FIXES"));
    fixes.forEach((fix) => {
      const button = element("button", "step-run engine-fix-button", `Plan ${fix.id}: ${fix.name}`);
      button.type = "button";
      button.dataset.fixId = fix.id;
      group.append(button);
    });
    target.append(group);
  }

  function renderCommand(command) {
    const box = element("div", "repair-command");
    const kind = command.kind === "powershell" ? "PowerShell" : "Command";
    box.append(element("p", "diag-command-label", `${kind}${command.label ? ` · ${command.label}` : ""}`));
    if (command.script) box.append(element("pre", "engine-evidence", command.script));
    else if (command.args && command.args.length) box.append(element("pre", "engine-evidence", command.args.join(" ")));
    if (command.native && command.native.length) box.append(element("pre", "engine-evidence", `Fallback: ${command.native.join(" ")}`));
    if (command.params && command.params.length) box.append(element("p", "muted", `Parameters: ${command.params.join(", ")}`));
    return box;
  }

  function listSection(target, label, items) {
    if (!items || !items.length) return;
    const section = element("div", "repair-section");
    section.append(element("p", "diag-command-label", label));
    const list = element("ul", "repair-list-points");
    items.forEach((item) => list.append(element("li", "", item)));
    section.append(list);
    target.append(section);
  }

  function renderRepairProcedure() {
    const target = $("repair-library-detail");
    if (!target) return;
    const entry = state.detail;
    target.replaceChildren();
    if (!entry) {
      target.append(emptyState("Select a repair", "Pick a repair from the list to see exactly what it changes, how it is verified, and how to roll it back.", ["M21 12a9 9 0 1 1-9-9", "M12 8v4l2.5 2.5"]));
      return;
    }

    const header = element("div", "diag-detail-head");
    const title = element("div", "diag-detail-title");
    const tags = element("div", "diag-tags");
    tags.append(element("span", "step-kind repair", String(entry.risk || "fix").toUpperCase()));
    if (entry.admin) tags.append(element("span", "admin-tag", "ADMIN"));
    if (entry.detection_only) tags.append(element("span", "admin-tag", "DETECT ONLY"));
    title.append(tags, element("h3", "", `${entry.id}: ${entry.name}`));
    title.append(element("p", "diag-desc", entry.symptom || "Catalog repair"));
    header.append(title);
    target.append(header);

    const explanation = visibleText(entry.explanation);
    if (explanation) target.append(element("p", "step-reason", explanation));
    if (entry.detection_only) {
      target.append(element("p", "step-reason", "This finding is detection-only. NetScope reports it but does not change the system automatically."));
    }
    renderFixFacts(target, entry.admin, entry.risk, entry.reboot);

    if (!entry.detection_only) {
      const steps = element("div", "repair-section");
      steps.append(element("p", "diag-command-label", "WHAT IT DOES"));
      (entry.ladder || []).forEach((step, index) => {
        const box = element("div", "repair-step");
        const head = element("div", "repair-step-head");
        head.append(element("span", "repair-step-number", String(index + 1).padStart(2, "0")), element("strong", "", step.name));
        if (step.optional) head.append(element("span", "repair-step-tag", "OPTIONAL"));
        if (step.risk && String(step.risk).toLowerCase() === "high") head.append(element("span", "repair-step-tag risk", "HIGH RISK"));
        if (step.requires_second_confirmation) head.append(element("span", "repair-step-tag", "CONFIRM"));
        box.append(head);
        if (step.description) box.append(element("p", "repair-step-desc", step.description));
        const commands = element("details", "repair-commands");
        commands.append(element("summary", "", `Exact commands (${(step.commands || []).length})`));
        (step.commands || []).forEach((command) => commands.append(renderCommand(command)));
        box.append(commands);
        steps.append(box);
      });
      target.append(steps);
    }

    listSection(target, "HOW TO VERIFY", (entry.verify || []).map((id) => `Re-run check ${id}`));
    listSection(target, "ROLLBACK", [entry.rollback_notes].filter(Boolean));
    if (entry.rollback && entry.rollback.length) {
      const rollback = element("details", "repair-commands");
      rollback.append(element("summary", "", `Rollback commands (${entry.rollback.length})`));
      entry.rollback.forEach((command) => rollback.append(renderCommand(command)));
      target.append(rollback);
    }
    const unresolved = entry.if_unresolved || {};
    listSection(target, "IF THIS DOES NOT HELP", unresolved.this_device || []);
    listSection(target, "IF THE PROBLEM IS BEYOND THIS DEVICE", unresolved.beyond_device || []);
    listSection(target, "NEXT CHECKS", unresolved.next_checks || []);
    listSection(target, "EVIDENCE TO COLLECT", unresolved.evidence_to_collect || []);

    if (!entry.detection_only) {
      const actions = element("div", "engine-fix-actions");
      const button = element("button", "step-run engine-fix-button", `Plan ${entry.id}: ${entry.name}`);
      button.type = "button";
      button.dataset.fixId = entry.id;
      actions.append(button);
      if (entry.admin && state.admin !== true) {
        actions.append(element("p", "muted", "This repair needs administrator rights. Use Run as administrator first."));
      }
      target.append(actions);
    }
  }

  function repairRow(fix) {
    const row = element("button", `repair-row${fix.id === state.libraryId ? " selected" : ""}`);
    row.type = "button";
    row.dataset.repairId = fix.id;
    const head = element("div", "repair-row-head");
    head.append(element("span", "repair-row-id", fix.id), element("strong", "", fix.name));
    row.append(head);
    row.append(element("p", "repair-row-symptom", fix.symptom || ""));
    const tags = element("div", "repair-row-tags");
    tags.append(element("span", "repair-row-tag", String(fix.risk || "unknown").toUpperCase()));
    if (fix.admin) tags.append(element("span", "repair-row-tag admin", "ADMIN"));
    if (fix.detection_only) tags.append(element("span", "repair-row-tag", "DETECT ONLY"));
    row.append(tags);
    return row;
  }

  function filteredFixes() {
    const query = (state.repairQuery || "").trim().toLowerCase();
    if (!query) return state.fixes;
    return state.fixes.filter((fix) => [fix.id, fix.name, fix.symptom]
      .filter(Boolean)
      .some((text) => String(text).toLowerCase().includes(query)));
  }

  function updateRepairRows(list) {
    list.querySelectorAll(".repair-row, .empty-state").forEach((node) => node.remove());
    const count = list.querySelector(".repair-search-count");
    const fixes = filteredFixes();
    if (count) {
      count.textContent = fixes.length === state.fixes.length
        ? `${fixes.length} repairs`
        : `${fixes.length} of ${state.fixes.length} repairs`;
    }
    if (!fixes.length) {
      list.append(emptyState("No matching repairs", `Nothing matches "${state.repairQuery.trim()}". Try a different name, symptom or ID.`));
      return;
    }
    fixes.forEach((fix) => list.append(repairRow(fix)));
  }

  function renderRepairLibrary() {
    const list = $("repair-library-list");
    if (!list) return;
    list.replaceChildren();
    if (!state.fixes.length) {
      list.append(emptyState("Repair catalog unavailable", "The catalog could not be loaded. Diagnostics keep working; repairs need the catalog."));
      return;
    }
    const search = document.createElement("input");
    search.type = "search";
    search.className = "repair-search";
    search.placeholder = "Search repairs (name, symptom or ID)";
    search.setAttribute("aria-label", "Search repairs");
    search.value = state.repairQuery;
    search.addEventListener("input", () => {
      state.repairQuery = search.value;
      updateRepairRows(list);
    });
    list.append(search, element("p", "repair-search-count", ""));
    updateRepairRows(list);
  }

  function selectRepair(fixId) {
    state.libraryId = fixId;
    renderRepairLibrary();
    const target = $("repair-library-detail");
    if (target) target.replaceChildren(element("p", "muted", "Loading procedure..."));
    api(`/api/fixes/${encodeURIComponent(fixId)}`).then((payload) => {
      state.detail = payload.fix;
      if (payload.admin !== undefined) {
        state.admin = Boolean(payload.admin);
        renderAdminState();
      }
      renderRepairProcedure();
    }).catch((error) => {
      if (target) target.replaceChildren(element("p", "step-reason error", error.message));
    });
  }

  function openRepairLibrary(fixId) {
    const nav = document.querySelector('.nav-item[data-view="repairs"]');
    if (nav) nav.click();
    selectRepair(fixId);
  }

  function renderDetail() {
    const stage = $("diag-stage");
    if (!stage) return;
    stage.replaceChildren();
    const check = state.checks.find((item) => item.id === state.selectedId);
    const fix = state.fixes.find((item) => item.id === state.selectedId);
    const item = check || fix;
    if (!item) {
      stage.append(emptyState("No step selected", "Run a diagnosis, then pick a check or repair from the rail to inspect its findings and evidence."));
      renderToolPanel(stage);
      return;
    }

    const detail = element("div", `diag-detail ${check ? "check" : "repair"}`);
    const header = element("div", "diag-detail-head");
    const title = element("div", "diag-detail-title");
    const tags = element("div", "diag-tags");
    tags.append(element("span", `step-kind ${check ? "check" : "repair"}`, check ? String(item.layer || "check").toUpperCase() : String(item.risk || "fix").toUpperCase()));
    if (item.admin) tags.append(element("span", "admin-tag", "ADMIN"));
    title.append(tags, element("h3", "", resultTitle(item)));
    const message = visibleText(item.message);
    const explanation = visibleText(item.explanation);
    const descText = check
      ? (item.description || (item.pending ? "This check has not run yet. Select layers and run a diagnosis." : (message || "No additional detail.")))
      : (item.symptom || explanation || "Catalog fix");
    title.append(element("p", "diag-desc", descText));
    header.append(title, element("span", `step-status ${statusClass(item.status)}`, item.status || "ready"));
    detail.append(header);

    if (check && !item.pending && message) detail.append(element("p", "step-reason", message));
    const cause = visibleText(item.cause);
    if (check && !item.pending && cause) detail.append(element("p", "step-reason", cause));
    if (fix) {
      if (explanation) detail.append(element("p", "step-reason", explanation));
      renderFixFacts(detail, fix.admin, fix.risk, fix.reboot);
      const procedure = element("button", "ghost-button", "View full procedure");
      procedure.type = "button";
      procedure.dataset.procedureId = fix.id;
      procedure.prepend(svgIcon("m9 6 6 6-6 6"));
      detail.append(procedure);
    }
    if (check && !item.pending) {
      renderEvidence(detail, item.evidence);
      renderFixActions(detail, item.fix_ids || []);
    }
    stage.append(detail);
    renderToolPanel(stage);
  }

  function getProgressStats() {
    const total = state.checks.length;
    const completed = state.checks.filter((item) => !["pending", "running"].includes(item.status)).length;
    const passed = state.checks.filter((item) => ["pass", "resolved", "success", "done"].includes(item.status)).length;
    const failed = state.checks.filter((item) => ["fail", "error", "warn", "warning", "cancelled"].includes(item.status)).length;
    const running = state.checks.filter((item) => item.status === "running").length;
    return { total, completed, passed, failed, running };
  }

  function renderLayerStatus() {
    const grid = $("layer-status-grid");
    if (!grid) return;
    layers.forEach((layer) => {
      const row = grid.querySelector(`[data-layer-status="${layer}"]`);
      if (!row) return;
      const value = row.querySelector(".layer-status-value");
      if (!value) return;

      const results = state.checks.filter((item) => item.layer === layer && !item.pending);
      const counts = { pass: 0, warn: 0, fail: 0, error: 0, skip: 0 };
      results.forEach((item) => {
        const status = String(item.status || "skip").toLowerCase();
        if (Object.prototype.hasOwnProperty.call(counts, status)) counts[status] += 1;
      });

      let status;
      let detail;
      if (state.activeLayers.includes(layer)) {
        status = "running";
        const reported = results.length;
        detail = reported ? `${reported} check${reported === 1 ? "" : "s"} reported` : "Checking";
      } else if (!results.length) {
        status = "idle";
        detail = "Not run";
      } else {
        status = counts.fail ? "fail"
          : counts.error ? "error"
            : counts.warn ? "warn"
              : counts.pass ? "pass"
                : "skip";
        detail = [
          counts.pass && `${counts.pass} pass`,
          counts.warn && `${counts.warn} warn`,
          counts.fail && `${counts.fail} fail`,
          counts.error && `${counts.error} error`,
          counts.skip && `${counts.skip} skip`,
        ].filter(Boolean).join(" · ") || `${results.length} check${results.length === 1 ? "" : "s"}`;
      }

      row.className = `layer-status-row ${status}`;
      value.className = `layer-status-value ${status}`;
      value.textContent = status === "idle" ? detail : status.toUpperCase();
      row.setAttribute("aria-label", `${layerLabels[layer]}: ${status === "idle" ? detail : `${status}, ${detail}`}`);
      row.dataset.detail = detail;
      const name = row.querySelector(".layer-status-name");
      if (name) name.dataset.detail = detail;
    });
  }

  function render() {
    const checks = $("check-steps");
    if (!checks) return;
    renderLayerStatus();
    renderRail(checks, state.checks, "check");
    renderDetail();
    const stats = getProgressStats();
    const summary = $("troubleshoot-summary");
    const percent = $("troubleshoot-percent");
    const fill = $("diag-progress-fill");
    if (summary) {
      if (!stats.total) {
        summary.textContent = "Loading troubleshooting steps...";
      } else if (state.busy) {
        summary.textContent = `${stats.passed} passed • ${stats.failed} failed • ${stats.completed}/${stats.total} checks complete`;
      } else if (stats.completed === stats.total) {
        summary.textContent = `${stats.passed} passed • ${stats.failed} failed • diagnosis complete`;
      } else {
        summary.textContent = `${stats.passed} passed • ${stats.failed} failed • ${stats.completed}/${stats.total} checks complete`;
      }
    }
    const value = stats.total ? Math.round((stats.completed / stats.total) * 100) : 0;
    if (percent) percent.textContent = `${value}%`;
    if (fill) fill.style.width = `${value}%`;
  }

  function resetChecksForRun() {
    state.checks = state.checks.map((item) => ({
      ...item,
      status: "pending",
      pending: true,
      message: "",
      cause: null,
      evidence: {},
      fix_ids: [],
    }));
  }

  function receiveCheck(result) {
    const incoming = Object.assign({ kind: "check", status: "skip", fix_ids: [] }, result);
    const singleId = state.singleCheckId;
    const index = state.checks.findIndex((item) => item.id === incoming.id);
    if (index >= 0) {
      // Results stream without the descriptor text, so keep the planned
      // description available for the detail pane.
      if (!incoming.description) incoming.description = state.checks[index].description || "";
      state.checks[index] = incoming;
    } else if (singleId && idMatches(incoming.id, singleId)) {
      // A single run may expand one planned check into several results
      // (e.g. SVC-04 -> SVC-04-NlaSvc + SVC-04-netprofm). Replace the planned
      // row with the first result, then append the extras.
      const placeholder = state.checks.findIndex((item) => item.id === singleId);
      if (placeholder >= 0) state.checks[placeholder] = incoming;
      else state.checks.push(incoming);
    } else {
      state.checks.push(incoming);
    }
    if (singleId) {
      // Running one check must not discard the other planned rows.
      if (idMatches(incoming.id, singleId)) state.selectedId = incoming.id;
    } else {
      // Keep the checklist visible while checks resolve, and drop only stale
      // pending placeholders from the same layer after real results arrive.
      const hasResultsForLayer = state.checks.some((item) => item.layer === incoming.layer && !item.pending);
      if (hasResultsForLayer) {
        state.checks = state.checks.filter((item) => !(item.pending && item.layer === incoming.layer));
      }
      if (!state.selectedId) state.selectedId = incoming.id;
    }
    render();
  }

  function followJob(jobId, extra) {
    extra = extra || {};
    return window.NetScopeJobStream.follow(jobId, {
      request: api,
      onEvent(payload) {
        if (payload.type === "check" && payload.result) receiveCheck(payload.result);
        if (payload.type === "result") {
          state.report = payload.result;
          if (state.report && state.report.results) state.report.results.forEach(receiveCheck);
        }
        if (payload.type === "end") state.jobId = null;
        if (extra.onEvent) extra.onEvent(payload);
      },
      onFallback(job) {
        state.jobId = null;
        if (job.result && job.result.results) {
          state.report = job.result;
          job.result.results.forEach(receiveCheck);
        }
        if (extra.onFallback) extra.onFallback(job);
      },
    });
  }

  async function runDiagnosis() {
    if (state.busy) return;
    setBusy(true, "Starting diagnosis...");
    if (!state.checks.length) {
      state.checks = [];
      try {
        const catalog = await api("/api/fixes");
        state.fixes = catalog.fixes || [];
      } catch (_error) {
        state.fixes = [];
      }
      const checksPayload = await api("/api/checks");
      const planned = (checksPayload.checks || []).map((c) => ({
        id: c.id,
        layer: c.layer,
        title: c.title,
        description: c.description || "",
        status: "pending",
        pending: true,
        message: "",
        cause: null,
        evidence: {},
        fix_ids: [],
      }));
      state.checks = planned;
      state.checksLoaded = true;
    } else {
      resetChecksForRun();
    }
    state.fixes = state.fixes || [];
    state.selectedId = null;
    state.report = null;
    const selectedLayers = Array.from(document.querySelectorAll("input[data-engine-layer]:checked"), (input) => input.dataset.engineLayer);
    state.activeLayers = selectedLayers;
    renderLayerStatus();
    try {
      const started = await api("/api/diagnose", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ layers: selectedLayers }) });
      state.jobId = started.job_id;
      setBusy(true, "Running diagnostics...");
      const job = await followJob(state.jobId);
      if (job.status === "error") throw new Error(job.error || "Diagnosis failed.");
      if (job.status === "cancelled") state.checks.forEach((item) => { if (item.status === "running") item.status = "skip"; });
    } catch (error) {
      const stage = $("diag-stage");
      if (stage) {
        stage.replaceChildren(element("p", "step-reason error", error.message));
      }
    } finally {
      state.jobId = null;
      state.activeLayers = [];
      setBusy(false);
    }
  }

  async function runSingleCheck(item) {
    if (state.busy) return;
    const layer = item.layer;
    if (!state.fixes.length) {
      try {
        const catalog = await api("/api/fixes");
        state.fixes = catalog.fixes || [];
      } catch (_error) {
        state.fixes = [];
      }
    }
    state.checks = state.checks.map((entry) => (
      entry.id === item.id
        ? { ...entry, status: "running", pending: true, message: "", cause: null, evidence: {}, fix_ids: [] }
        : entry
    ));
    state.selectedId = item.id;
    state.singleCheckId = item.id;
    state.activeLayers = [layer];
    state.report = null;
    setBusy(true, "Running check...");
    try {
      const started = await api("/api/diagnose", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ layers: [layer], checks: [item.id] }) });
      state.jobId = started.job_id;
      setBusy(true, "Running diagnostics...");
      const job = await followJob(state.jobId);
      if (job.status === "error") throw new Error(job.error || "Diagnosis failed.");
      if (job.status === "cancelled") state.checks.forEach((entry) => { if (entry.status === "running") entry.status = "skip"; });
    } catch (error) {
      state.checks = state.checks.map((entry) => (
        entry.id === item.id && entry.status === "running"
          ? { ...entry, status: "error", message: error.message || "This check could not run." }
          : entry
      ));
      render();
      const stage = $("diag-stage");
      if (stage) stage.append(element("p", "step-reason error", error.message));
    } finally {
      state.jobId = null;
      state.singleCheckId = null;
      state.activeLayers = [];
      setBusy(false);
    }
  }

  async function cancelJob() {
    if (!state.jobId) return;
    try {
      await api(`/api/jobs/${encodeURIComponent(state.jobId)}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    } catch (error) {
      const stage = $("diag-stage");
      if (stage) stage.append(element("p", "step-reason error", error.message));
    }
  }

  function makeDialog(plan) {
    const dialog = element("dialog", "engine-confirmation");
    const panel = element("form", "engine-confirmation-panel");
    panel.method = "dialog";
    panel.append(element("p", "eyebrow", "FIX PREVIEW"), element("h2", "", plan.name));
    panel.append(element("p", "diag-desc", plan.explanation || "Review the changes before execution."));
    renderFixFacts(panel, plan.admin, plan.risk, plan.reboot);
    const commands = element("pre", "engine-evidence", (plan.preview || []).join("\n") || "No commands are required.");
    panel.append(commands);
    if (plan.rollback_notes) panel.append(element("p", "muted", `Rollback: ${plan.rollback_notes}`));
    const dryRunLabel = element("label", "engine-toggle");
    const dryRun = document.createElement("input");
    dryRun.type = "checkbox";
    dryRunLabel.append(dryRun, document.createTextNode("Dry run"));
    panel.append(dryRunLabel);
    let typed = null;
    if (String(plan.risk).toLowerCase() === "high") {
      panel.append(element("p", "step-reason error", "High-risk change. Type APPLY HIGH-RISK FIX to confirm."));
      typed = document.createElement("input");
      typed.type = "text";
      typed.autocomplete = "off";
      typed.setAttribute("aria-label", "Type APPLY HIGH-RISK FIX to confirm");
      panel.append(typed);
    }
    const actions = element("div", "engine-dialog-actions");
    const cancel = element("button", "ghost-button", "Cancel");
    cancel.type = "button";
    const execute = element("button", "step-run", "Execute fix");
    execute.type = "button";
    actions.append(cancel, execute);
    panel.append(actions);
    dialog.append(panel);
    document.body.append(dialog);
    cancel.addEventListener("click", () => dialog.close());
    execute.addEventListener("click", async () => {
      if (typed && typed.value.trim() !== "APPLY HIGH-RISK FIX") {
        typed.focus();
        return;
      }
      dialog.close();
      dialog.remove();
      await executeFix(plan, dryRun.checked, Boolean(typed));
    });
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    dialog.showModal();
    if (typed) typed.focus();
  }

  function renderFixProgress(plan) {
    const stage = $("diag-stage");
    if (!stage) return null;
    stage.replaceChildren();
    const card = element("div", "engine-output engine-progress");
    card.append(element("div", "engine-output-head", "APPLYING FIX"));
    card.append(element("p", "diag-desc", plan && plan.name ? plan.name : "Preparing the fix..."));
    const status = element("p", "engine-progress-status", "Starting...");
    const track = element("div", "engine-progress-track");
    const fill = element("div", "engine-progress-fill");
    track.append(fill);
    const list = element("div", "engine-progress-steps");
    card.append(status, track, list);
    stage.append(card);
    renderToolPanel(stage);
    return { status, fill, list, rows: new Map(), total: 0 };
  }

  function setProgressRowStatus(row, status) {
    if (!row) return;
    row.dataset.status = status;
    const chip = row.querySelector(".engine-progress-chip");
    if (chip) {
      chip.textContent = status;
      chip.className = `engine-progress-chip ${status}`;
    }
  }

  function updateFixProgress(view, event) {
    if (!view || !event) return;
    if (event.total) view.total = event.total;
    if (event.phase === "step") {
      view.rows.forEach((row) => {
        if (row.dataset.status === "running" || row.dataset.status === "verifying") setProgressRowStatus(row, "done");
      });
      view.status.textContent = `Step ${event.index} of ${event.total || "?"}: ${event.name || ""}`;
      let row = view.rows.get(event.index);
      if (!row) {
        row = element("div", "engine-progress-step");
        const text = element("span", "engine-progress-text");
        text.append(element("strong", "", event.name || `Step ${event.index}`));
        if (event.description) text.append(element("small", "", event.description));
        row.append(
          element("span", "engine-progress-index", String(event.index).padStart(2, "0")),
          text,
          element("span", "engine-progress-chip running", "running")
        );
        view.rows.set(event.index, row);
        view.list.append(row);
      }
      setProgressRowStatus(row, "running");
      const completed = Math.max(0, event.index - 1);
      view.fill.style.width = `${view.total ? Math.round((completed / view.total) * 100) : 5}%`;
    } else if (event.phase === "verify") {
      view.status.textContent = event.message || "Re-checking...";
      setProgressRowStatus(view.rows.get(event.index), "verifying");
      if (view.total) view.fill.style.width = `${Math.round(((event.index - 0.5) / view.total) * 100)}%`;
    } else {
      if (event.message) view.status.textContent = event.message;
      if (event.phase === "guidance") view.fill.style.width = "100%";
    }
  }

  async function executeFix(plan, dryRun, secondConfirmation) {
    const progressView = renderFixProgress(plan);
    setBusy(true, "Applying fix...", false);
    const started = Date.now();
    try {
      const response = await api("/api/fix/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_token: plan.confirmation_token, dry_run: dryRun, second_confirmation: secondConfirmation })
      });
      state.jobId = response.job_id;
      syncCancelState();
      const job = await followJob(state.jobId, {
        onEvent(payload) {
          if (payload.type === "fix_progress") updateFixProgress(progressView, payload);
        }
      });
      const outcome = job.result || { error: job.error || job.status };
      renderFixOutcome(outcome, Date.now() - started);
      if (outcome.status === "resolved") toast(`${outcome.fix_id || "Fix"} resolved the problem`, "success");
      else if (outcome.status === "dry_run") toast("Dry run complete. No changes were made.", "success");
      else if (outcome.status === "unresolved") toast("The fix ran, but the problem remains.", "error");
      else if (outcome.error) toast(outcome.error, "error");
      if (outcome.unresolved) {
        toast("Review the likely causes below.", "error");
        showIsolationQuestion(String(outcome.fix_id || plan.fix_id || ""));
      }
    } catch (error) {
      const stage = $("diag-stage");
      if (stage) stage.append(element("p", "step-reason error", error.message));
      toast(error.message, "error");
    } finally {
      state.jobId = null;
      setBusy(false, null, false);
    }
  }

  async function configureGateway() {
    setBusy(true, "Configuring gateway...", false);
    try {
      const started = await api("/api/gateway/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      });
      state.jobId = started.job_id;
      syncCancelState();
      const job = await followJob(state.jobId);
      const stage = $("diag-stage");
      if (stage) {
        showOutput("GATEWAY RESULT", job.result || { error: job.error || job.status });
        const outcome = job.result && job.result.outcome;
        if (outcome && outcome.rollback_available) {
          const rollback = element("button", "ghost-button", "Roll back this fix");
          rollback.type = "button";
          rollback.dataset.rollbackId = started.fix_id;
          stage.append(rollback);
        }
      }
      toast("Gateway repair finished", "success");
    } catch (error) {
      const stage = $("diag-stage");
      if (stage) stage.append(element("p", "step-reason error", error.message));
      toast(error.message, "error");
    } finally {
      state.jobId = null;
      setBusy(false, null, false);
    }
  }

  async function planFix(fixId) {
    try {
      const plan = await api("/api/fix/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fix_id: fixId }) });
      if (plan.detection_only) throw new Error("This finding is detection-only and cannot be changed automatically.");
      makeDialog(plan);
    } catch (error) {
      const stage = $("diag-stage");
      if (stage) stage.append(element("p", "step-reason error", error.message));
    }
  }

  async function rollbackFix(fixId) {
    if (!window.confirm(`Restore the saved system state for ${fixId}?`)) return;
    setBusy(true, "Rolling back...", false);
    try {
      const started = await api("/api/fix/rollback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fix_id: fixId, confirmed: true })
      });
      state.jobId = started.job_id;
      syncCancelState();
      const job = await followJob(state.jobId);
      showOutput("ROLLBACK RESULT", job.result || { error: job.error || job.status });
      toast(`${fixId} rolled back`, "success");
    } catch (error) {
      showOutput("ROLLBACK ERROR", { error: error.message });
      toast(error.message, "error");
    } finally {
      state.jobId = null;
      setBusy(false, null, false);
    }
  }

  function showIsolationQuestion(fixId) {
    const stage = $("diag-stage");
    if (!stage) return;
    const box = element("div", "engine-isolation");
    box.append(element("p", "diag-command-label", "DOES ANOTHER DEVICE WORK ON THIS NETWORK?"));
    [["yes", "Yes"], ["no", "No"], ["not-sure", "Not sure"]].forEach(([value, label]) => {
      const button = element("button", "ghost-button", label);
      button.type = "button";
      button.addEventListener("click", async () => {
        const answer = value === "not-sure" ? null : value === "yes";
        button.disabled = true;
        setButtonLabel(button, "Working...");
        try {
          const response = await api("/api/unresolved/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fix_id: fixId, another_device_works: answer }) });
          box.replaceChildren(element("p", "diag-command-label", "IF THIS DID NOT HELP"));
          const section = (response.sections || [])[0];
          if (section) renderUnresolved(section, box);
          else box.append(element("p", "engine-info-empty", "No further guidance is available for this finding."));
          toast("Likely causes re-ranked", "success");
        } catch (error) {
          button.disabled = false;
          setButtonLabel(button, label);
          box.append(element("p", "step-reason error", error.message));
          toast(error.message, "error");
        }
      });
      box.append(button);
    });
    stage.append(box);
  }

  function showOutput(title, value) {
    const stage = $("diag-stage");
    if (!stage) return;
    stage.replaceChildren();
    const text = JSON.stringify(value, null, 2);
    const card = element("div", "engine-output");
    card.append(cardHead(title, text));
    if (title === "SPEED TEST RESULT") {
      card.append(createSpeedTestMetrics(value));
      card.append(element(
        "p",
        "speed-test-details",
        `${value.server} · ${(value.download_bytes / 1048576).toFixed(1)} MiB downloaded · ${(value.upload_bytes / 1048576).toFixed(1)} MiB uploaded`
      ));
    } else {
      card.append(element("pre", "engine-evidence", text));
    }
    stage.append(card);
    renderToolPanel(stage);
  }

  function createSpeedTestMetrics(value) {
    const results = element("div", "speed-test-results");
    [
      ["Latency", value.latency_ms, "ms", "latency"],
      ["Download", value.download_mbps, "Mbps", "download"],
      ["Upload", value.upload_mbps, "Mbps", "upload"],
    ].forEach(([label, number, unit, kind]) => {
      const metric = element("div", `speed-test-metric ${kind}`);
      const reading = element("strong", "", String(number));
      reading.append(element("small", "", unit));
      metric.append(element("span", "", label), reading);
      results.append(metric);
    });
    return results;
  }

  async function runTool(name, inputElement, ports, button) {
    const input = inputElement.value.trim();
    const params = {};
    if (["ping", "trace", "mtu", "ports"].includes(name)) params.host = input;
    if (name === "dns") params.name = input;
    if (name === "ports") params.ports = ports;
    if (name === "speedtest" && !window.confirm("This test contacts speed.cloudflare.com and transfers up to 10 MiB down and 2 MiB up. Continue?")) return;
    if (name === "ping" && !input || name === "trace" && !input || name === "mtu" && !input || name === "ports" && (!input || !ports) || name === "dns" && !input) {
      inputElement.focus();
      return;
    }
    button.disabled = true;
    setButtonLabel(button, "Running...");
    setBusy(true, "Running utility...", false);
    try {
      const started = await api(`/api/tools/${encodeURIComponent(name)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
      state.jobId = started.job_id;
      syncCancelState();
      const job = await followJob(state.jobId);
      if (job.status === "error") throw new Error(job.error || "Utility failed.");
      showOutput(name === "speedtest" ? "SPEED TEST RESULT" : `${name.toUpperCase()} RESULT`, job.result);
    } catch (error) {
      showOutput("UTILITY ERROR", { error: error.message });
      toast(error.message, "error");
    } finally {
      state.jobId = null;
      button.disabled = false;
      setButtonLabel(button, "Run tool");
      setBusy(false, null, false);
    }
  }

  async function runSpeedTest(button) {
    const status = $("speed-test-status");
    const results = $("speed-test-results");
    const details = $("speed-test-details");
    if (!status || !results || !details || state.busy || button.disabled) return;
    if (!window.confirm("This test contacts speed.cloudflare.com and transfers up to 10 MiB down and 2 MiB up. Continue?")) return;

    button.disabled = true;
    setButtonLabel(button, "Testing...");
    status.classList.remove("is-error");
    status.textContent = "Measuring latency, download, and upload...";
    results.hidden = true;
    details.hidden = true;
    try {
      const started = await api("/api/tools/speedtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      state.jobId = started.job_id;
      const job = await followJob(state.jobId);
      if (job.status !== "done" || !job.result) {
        throw new Error(job.error || "Speed test did not complete.");
      }
      const value = job.result;
      $("speed-test-latency").textContent = Number(value.latency_ms).toFixed(1);
      $("speed-test-download").textContent = Number(value.download_mbps).toFixed(2);
      $("speed-test-upload").textContent = Number(value.upload_mbps).toFixed(2);
      results.hidden = false;
      details.textContent =
        `${value.server} · ${(value.download_bytes / 1048576).toFixed(1)} MiB downloaded · ${(value.upload_bytes / 1048576).toFixed(1)} MiB uploaded`;
      details.hidden = false;
      status.textContent = "Test complete";
      toast("Speed test complete", "success");
    } catch (error) {
      status.textContent = `Speed test failed: ${error.message}`;
      status.classList.add("is-error");
      toast(error.message, "error");
    } finally {
      state.jobId = null;
      button.disabled = false;
      setButtonLabel(button, "Run speed test");
    }
  }

  function renderToolPanel(stage) {
    const panel = element("div", "engine-tools");
    panel.append(element("p", "diag-command-label", "TOOLS"));
    const controls = element("div", "engine-tool-controls");
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Network tool");
    [["ping", "Ping"], ["trace", "Trace route"], ["dns", "DNS lookup"], ["arp", "ARP table"], ["routes", "Routes"], ["ports", "Port check"], ["mtu", "Path MTU"], ["speedtest", "Speed test"]].forEach(([value, label]) => {
      const option = element("option", "", label);
      option.value = value;
      select.append(option);
    });
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Host or DNS name";
    input.setAttribute("aria-label", "Host or DNS name");
    const ports = document.createElement("input");
    ports.type = "text";
    ports.placeholder = "Ports (e.g. 80,443)";
    ports.setAttribute("aria-label", "Ports");
    ports.hidden = true;
    select.addEventListener("change", () => {
      input.hidden = ["arp", "routes", "speedtest"].includes(select.value);
      ports.hidden = select.value !== "ports";
    });
    const run = element("button", "ghost-button");
    run.type = "button";
    run.append(svgIcon("M5 3l14 9-14 9V3z", 12), element("span", "btn-label", "Run tool"));
    run.addEventListener("click", () => runTool(select.value, input, ports.value.trim(), run));
    controls.append(select, input, ports, run);
    panel.append(controls);
    panel.append(element("p", "engine-tool-note", "Speed test transfers up to 10 MiB down and 2 MiB up to speed.cloudflare.com."));

    const actions = element("div", "engine-tool-actions");
    const info = element("button", "ghost-button");
    info.type = "button";
    info.append(svgIcon("M12 10v6m0-9.5v.01", 12), element("span", "btn-label", "Network info"));
    info.addEventListener("click", () => {
      showNetworkInfo();
    });
    const logs = element("button", "ghost-button");
    logs.type = "button";
    logs.append(svgIcon("M4 5h16M4 12h16M4 19h10", 12), element("span", "btn-label", "View logs"));
    logs.addEventListener("click", async () => {
      try { renderLogs(await api("/api/logs?tail=100")); }
      catch (error) { showOutput("LOG ERROR", { error: error.message }); }
    });
    const report = element("button", "ghost-button");
    report.type = "button";
    report.append(svgIcon("M12 4v12m0 0 5-5m-5 5-5-5M5 20h14", 12), element("span", "btn-label", "Export report"));
    report.addEventListener("click", async () => {
      try {
        const data = await api("/api/report?format=json");
        downloadJson("netscope-report.json", data);
        toast("Saved netscope-report.json", "success");
      } catch (error) {
        showOutput("REPORT ERROR", { error: error.message });
        toast(error.message, "error");
      }
    });
    const history = element("button", "ghost-button");
    history.type = "button";
    history.append(svgIcon("M3 12a9 9 0 1 0 2.6-6.3L3 8", 12), element("span", "btn-label", "Fix history"));
    history.addEventListener("click", async () => {
      try {
        const data = await api("/api/fix/history");
        renderFixHistory(data.history || []);
      } catch (error) { showOutput("FIX HISTORY ERROR", { error: error.message }); }
    });
    actions.append(info, logs, report, history);
    panel.append(actions);
    stage.append(panel);
  }

  function addLayerControls() {
    const actions = document.querySelector(".troubleshoot-actions");
    const run = $("run-engine-diagnosis");
    if (!actions || !run || $("engine-layer-controls")) return;
    const controls = element("div", "engine-layer-controls");
    controls.id = "engine-layer-controls";
    layers.forEach((layer) => {
      const label = element("label", "engine-layer-option");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = true;
      input.dataset.engineLayer = layer;
      label.append(input, document.createTextNode(layer));
      controls.append(label);
    });
    const cancel = element("button", "ghost-button");
    cancel.id = "engine-cancel-job";
    cancel.type = "button";
    cancel.append(svgIcon("M6 6l12 12M18 6L6 18", 12), element("span", "btn-label", "Cancel run"));
    cancel.disabled = true;
    cancel.addEventListener("click", cancelJob);
    actions.insertBefore(controls, run);
    actions.insertBefore(cancel, run);
  }

  function loadChecks() {
    api("/api/checks").then((payload) => {
      const planned = (payload.checks || []).map((c) => ({
        id: c.id,
        layer: c.layer,
        title: c.title,
        description: c.description || "",
        status: "pending",
        pending: true,
        message: "",
        cause: null,
        evidence: {},
        fix_ids: [],
      }));
      state.checks = planned;
      state.checksLoaded = true;
      render();
    }).catch(() => {
      state.checksLoaded = true;
      state.checks = [];
      render();
    });
  }

  function loadCatalog() {
    api("/api/fixes").then((payload) => {
      state.fixes = payload.fixes || [];
      if (state.libraryId) selectRepair(state.libraryId);
      else if (state.fixes.length) selectRepair(state.fixes[0].id);
      else renderRepairLibrary();
    }).catch(() => { renderRepairLibrary(); });
  }

  function initialize() {
    const speedTest = $("run-speed-test");
    if (speedTest) speedTest.addEventListener("click", () => runSpeedTest(speedTest));

    // Adopt the shared Troubleshoot content: replacing each node with a
    // listener-free clone drops the legacy dashboard handlers that were
    // registered first (registration order at the target beats capture), so a
    // click cannot run both the legacy registry checks and the engine
    // diagnosis at the same time.
    const checks = adopt("check-steps");
    const repairs = adopt("repair-steps");
    const stage = adopt("diag-stage");
    const gateway = adopt("auto-configure-gateway");
    const run = $("run-engine-diagnosis");
    if (!run || !checks || !stage) return;
    addLayerControls();
    loadAdminStatus();
    loadChecks();
    loadCatalog();
    run.addEventListener("click", (event) => {
      event.preventDefault();
      runDiagnosis();
    });
    if (gateway) gateway.addEventListener("click", (event) => {
      event.preventDefault();
      configureGateway();
    });
    if (checks) checks.addEventListener("click", (event) => {
      const runButton = event.target.closest(".diag-item-run");
      if (runButton) {
        event.preventDefault();
        const item = state.checks.find((entry) => entry.id === runButton.dataset.runItem);
        if (item) runSingleCheck(item);
        return;
      }
      const item = event.target.closest("[data-engine-item]");
      if (!item) return;
      event.preventDefault();
      state.selectedId = item.dataset.engineItem;
      render();
    });
    if (repairs) repairs.addEventListener("click", (event) => {
      const item = event.target.closest("[data-engine-item]");
      if (!item) return;
      event.preventDefault();
      state.selectedId = item.dataset.engineItem;
      render();
    });
    stage.addEventListener("click", (event) => {
      const button = event.target.closest("[data-fix-id]");
      const rollback = event.target.closest("[data-rollback-id]");
      const procedure = event.target.closest("[data-procedure-id]");
      if (!button && !rollback && !procedure) return;
      event.preventDefault();
      if (button) planFix(button.dataset.fixId);
      else if (procedure) openRepairLibrary(procedure.dataset.procedureId);
      else rollbackFix(rollback.dataset.rollbackId);
    });
    const libraryList = $("repair-library-list");
    if (libraryList) libraryList.addEventListener("click", (event) => {
      const row = event.target.closest("[data-repair-id]");
      if (!row) return;
      event.preventDefault();
      selectRepair(row.dataset.repairId);
    });
    const libraryDetail = $("repair-library-detail");
    if (libraryDetail) libraryDetail.addEventListener("click", (event) => {
      const button = event.target.closest("[data-fix-id]");
      if (!button) return;
      event.preventDefault();
      planFix(button.dataset.fixId);
    });
    [["run-as-admin", requestElevation], ["repair-run-as-admin", requestElevation]].forEach(([id, handler]) => {
      const button = $(id);
      if (button) button.addEventListener("click", (event) => { event.preventDefault(); handler(); });
    });
    guardLegacyContent(checks, repairs, stage);
    render();
  }

  function adopt(id) {
    const original = $(id);
    if (!original) return null;
    // cloneNode never copies event listeners, but does copy markup/children.
    const adopted = original.cloneNode(true);
    original.replaceWith(adopted);
    return adopted;
  }

  function guardLegacyContent(checks, repairs, stage) {
    if (typeof MutationObserver !== "function") return;
    const observer = new MutationObserver(() => {
      if (
        !checks.childElementCount ||
        (repairs && !repairs.childElementCount) ||
        checks.querySelector(".diag-item:not([data-engine-item])") ||
        (repairs && repairs.querySelector(".diag-item:not([data-engine-item])")) ||
        stage.querySelector("#console-output, #clear-console, .step-run[data-id]")
      ) {
        // The legacy dashboard rendered its registry into the shared stage
        // (late /api/diagnostics response, its error path, or the
        // Troubleshoot nav click); re-assert the engine view.
        render();
      }
    });
    const nodes = [checks, stage];
    if (repairs) nodes.push(repairs);
    nodes.forEach((node) => observer.observe(node, { childList: true, subtree: true }));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
})();
