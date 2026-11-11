(function () {
  const $ = (id) => document.getElementById(id);
  const state = { checks: [], fixes: [], selectedId: null, report: null, jobId: null, busy: false };
  const layers = ["adapter", "services", "ip", "gateway", "lan", "dns", "internet", "stack"];

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
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
    const run = $("run-all-checks");
    if (run) {
      run.disabled = busy;
      run.textContent = busy ? (label || "Running...") : "Run all checks";
    }
    const cancel = $("engine-cancel-job");
    if (cancel) cancel.disabled = !busy || !state.jobId;
    const gateway = $("auto-configure-gateway");
    if (gateway) gateway.disabled = busy;
    if (redraw !== false) render();
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

  function renderRail(container, items, kind) {
    container.replaceChildren();
    if (!items.length) {
      container.appendChild(element("p", "muted", kind === "repair" ? "Repairs appear when a finding has a catalog fix." : "Run a diagnosis to see checks."));
      return;
    }
    items.forEach((item, index) => {
      const button = element("button", `diag-item ${kind} ${statusClass(item.status)}${item.id === state.selectedId ? " selected" : ""}`);
      button.type = "button";
      button.dataset.engineItem = item.id;
      const number = element("span", "diag-item-index", statusClass(item.status) === "success" ? "✓" : statusClass(item.status) === "error" ? "!" : String(index + 1).padStart(2, "0"));
      const text = element("span", "diag-item-text");
      text.append(element("strong", "", resultTitle(item)));
      text.append(element("small", "", item.status || (kind === "repair" ? item.risk : item.layer)));
      button.append(number, text);
      container.append(button);
    });
  }

  function renderEvidence(target, value) {
    if (!value || (typeof value === "object" && !Object.keys(value).length)) return;
    const title = element("p", "diag-command-label", "EVIDENCE");
    const pre = element("pre", "engine-evidence", JSON.stringify(value, null, 2));
    target.append(title, pre);
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

  function renderDetail() {
    const stage = $("diag-stage");
    if (!stage) return;
    stage.replaceChildren();
    const check = state.checks.find((item) => item.id === state.selectedId);
    const fix = state.fixes.find((item) => item.id === state.selectedId);
    const item = check || fix;
    if (!item) {
      stage.append(element("p", "muted", "Choose layers and run a diagnosis to inspect findings."));
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
    title.append(element("p", "diag-desc", check ? (item.message || "No additional detail.") : (item.symptom || item.explanation || "Catalog fix")));
    header.append(title, element("span", `step-status ${statusClass(item.status)}`, item.status || "ready"));
    detail.append(header);

    if (check && item.cause) detail.append(element("p", "step-reason", item.cause));
    if (fix) {
      detail.append(element("p", "step-reason", item.explanation));
      detail.append(element("p", "diag-desc", `Risk: ${fix.risk || "unknown"} | Administrator: ${fix.admin ? "required" : "not required"} | Restart: ${fix.reboot ? "may be required" : "not expected"}`));
    }
    if (check) {
      renderEvidence(detail, item.evidence);
      renderFixActions(detail, item.fix_ids || []);
    }
    stage.append(detail);
    renderToolPanel(stage);
  }

  function render() {
    const checks = $("check-steps");
    const repairs = $("repair-steps");
    if (!checks || !repairs) return;
    renderRail(checks, state.checks, "check");
    renderRail(repairs, state.fixes, "repair");
    renderDetail();
    const total = state.checks.length;
    const complete = state.checks.filter((item) => item.status !== "running").length;
    const summary = $("troubleshoot-summary");
    const percent = $("troubleshoot-percent");
    const fill = $("diag-progress-fill");
    if (summary) summary.textContent = state.busy ? `Running diagnostics (${complete} of ${total})` : `${total} checks in the latest diagnosis`;
    const value = total ? Math.round((complete / total) * 100) : 0;
    if (percent) percent.textContent = `${value}%`;
    if (fill) fill.style.width = `${value}%`;
  }

  function receiveCheck(result) {
    const incoming = Object.assign({ kind: "check", status: "skip", fix_ids: [] }, result);
    const index = state.checks.findIndex((item) => item.id === incoming.id);
    if (index >= 0) state.checks[index] = incoming;
    else state.checks.push(incoming);
    if (!state.selectedId) state.selectedId = incoming.id;
    render();
  }

  function followJob(jobId) {
    return window.NetScopeJobStream.follow(jobId, {
      request: api,
      onEvent(payload) {
        if (payload.type === "check" && payload.result) receiveCheck(payload.result);
        if (payload.type === "result") {
          state.report = payload.result;
          if (state.report && state.report.results) state.report.results.forEach(receiveCheck);
        }
        if (payload.type === "end") state.jobId = null;
      },
      onFallback(job) {
        state.jobId = null;
        if (job.result && job.result.results) {
          state.report = job.result;
          state.checks = [];
          job.result.results.forEach(receiveCheck);
        }
      },
    });
  }

  async function runDiagnosis() {
    if (state.busy) return;
    setBusy(true, "Starting diagnosis...");
    state.checks = [];
    state.fixes = [];
    state.selectedId = null;
    state.report = null;
    const selectedLayers = Array.from(document.querySelectorAll("input[data-engine-layer]:checked"), (input) => input.dataset.engineLayer);
    try {
      const catalog = await api("/api/fixes");
      state.fixes = catalog.fixes || [];
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
    const facts = element("p", "engine-fix-facts", `Admin: ${plan.admin ? "required" : "no"} | Risk: ${plan.risk} | Restart: ${plan.reboot ? "may be required" : "no"}`);
    panel.append(facts);
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
  }

  async function executeFix(plan, dryRun, secondConfirmation) {
    setBusy(true, "Applying fix...", false);
    try {
      const started = await api("/api/fix/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_token: plan.confirmation_token, dry_run: dryRun, second_confirmation: secondConfirmation })
      });
      state.jobId = started.job_id;
      const job = await followJob(state.jobId);
      const stage = $("diag-stage");
      if (stage) {
        showOutput("FIX RESULT", job.result || { error: job.error || job.status });
        if (job.result && job.result.rollback_available) {
          const rollback = element("button", "ghost-button", "Roll back this fix");
          rollback.type = "button";
          rollback.dataset.rollbackId = started.fix_id;
          stage.append(rollback);
        }
      }
      if (job.result && job.result.status === "unresolved") showIsolationQuestion(started.fix_id);
    } catch (error) {
      const stage = $("diag-stage");
      if (stage) stage.append(element("p", "step-reason error", error.message));
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
    } catch (error) {
      const stage = $("diag-stage");
      if (stage) stage.append(element("p", "step-reason error", error.message));
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
      const job = await followJob(state.jobId);
      showOutput("ROLLBACK RESULT", job.result || { error: job.error || job.status });
    } catch (error) {
      showOutput("ROLLBACK ERROR", { error: error.message });
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
        try {
          const response = await api("/api/unresolved/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fix_id: fixId, another_device_works: answer }) });
          box.replaceChildren(element("pre", "engine-evidence", JSON.stringify(response.sections || [], null, 2)));
        } catch (error) {
          box.append(element("p", "step-reason error", error.message));
        }
      });
      box.append(button);
    });
    stage.append(box);
  }

  function showOutput(title, value) {
    const stage = $("diag-stage");
    if (!stage) return;
    stage.replaceChildren(element("h3", "", title), element("pre", "engine-evidence", JSON.stringify(value, null, 2)));
    renderToolPanel(stage);
  }

  async function runTool(name, inputElement, ports, button) {
    const input = inputElement.value.trim();
    const params = {};
    if (["ping", "trace", "mtu", "ports"].includes(name)) params.host = input;
    if (name === "dns") params.name = input;
    if (name === "ports") params.ports = ports;
    if (name === "ping" && !input || name === "trace" && !input || name === "mtu" && !input || name === "ports" && (!input || !ports) || name === "dns" && !input) {
      inputElement.focus();
      return;
    }
    button.disabled = true;
    button.textContent = "Running...";
    setBusy(true, "Running utility...", false);
    try {
      const started = await api(`/api/tools/${encodeURIComponent(name)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
      state.jobId = started.job_id;
      const job = await followJob(state.jobId);
      if (job.status === "error") throw new Error(job.error || "Utility failed.");
      showOutput(`${name.toUpperCase()} RESULT`, job.result);
    } catch (error) {
      showOutput("UTILITY ERROR", { error: error.message });
    } finally {
      state.jobId = null;
      setBusy(false, null, false);
    }
  }

  function renderToolPanel(stage) {
    const panel = element("div", "engine-tools");
    panel.append(element("p", "diag-command-label", "TOOLS"));
    const controls = element("div", "engine-tool-controls");
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Network tool");
    [["ping", "Ping"], ["trace", "Trace route"], ["dns", "DNS lookup"], ["arp", "ARP table"], ["routes", "Routes"], ["ports", "Port check"], ["mtu", "Path MTU"]].forEach(([value, label]) => {
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
      input.hidden = ["arp", "routes"].includes(select.value);
      ports.hidden = select.value !== "ports";
    });
    const run = element("button", "ghost-button", "Run tool");
    run.type = "button";
    run.addEventListener("click", () => runTool(select.value, input, ports.value.trim(), run));
    controls.append(select, input, ports, run);
    panel.append(controls);

    const actions = element("div", "engine-tool-actions");
    const info = element("button", "ghost-button", "Network info");
    info.type = "button";
    info.addEventListener("click", async () => {
      try { showOutput("NETWORK INFO", await api("/api/info")); }
      catch (error) { showOutput("NETWORK INFO ERROR", { error: error.message }); }
    });
    const logs = element("button", "ghost-button", "View logs");
    logs.type = "button";
    logs.addEventListener("click", async () => {
      try { showOutput("RECENT LOGS", await api("/api/logs?tail=100")); }
      catch (error) { showOutput("LOG ERROR", { error: error.message }); }
    });
    const report = element("button", "ghost-button", "Export report");
    report.type = "button";
    report.addEventListener("click", async () => {
      try {
        const data = await api("/api/report?format=json");
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "netscope-report.json";
        link.click();
        URL.revokeObjectURL(link.href);
      } catch (error) { showOutput("REPORT ERROR", { error: error.message }); }
    });
    const history = element("button", "ghost-button", "Fix history");
    history.type = "button";
    history.addEventListener("click", async () => {
      try {
        const data = await api("/api/fix/history");
        showOutput("FIX HISTORY", data);
        const historyList = element("div", "engine-fix-actions");
        (data.history || []).forEach((item) => {
          const rollback = element("button", "ghost-button", `Roll back ${item.fix_id}: ${item.name}`);
          rollback.type = "button";
          rollback.dataset.rollbackId = item.fix_id;
          historyList.append(rollback);
        });
        if (historyList.childElementCount) $("diag-stage").append(historyList);
      } catch (error) { showOutput("FIX HISTORY ERROR", { error: error.message }); }
    });
    actions.append(info, logs, report, history);
    panel.append(actions);
    stage.append(panel);
  }

  function addLayerControls() {
    const actions = document.querySelector(".troubleshoot-actions");
    const run = $("run-all-checks");
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
    const cancel = element("button", "ghost-button", "Cancel run");
    cancel.id = "engine-cancel-job";
    cancel.type = "button";
    cancel.disabled = true;
    cancel.addEventListener("click", cancelJob);
    actions.insertBefore(controls, run);
    actions.insertBefore(cancel, run);
  }

  function loadCatalog() {
    api("/api/fixes").then((payload) => { state.fixes = payload.fixes || []; }).catch(() => { });
  }

  function initialize() {
    if (!$("diag-stage") || !$("run-all-checks")) return;
    addLayerControls();
    loadCatalog();
    $("run-all-checks").addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      runDiagnosis();
    }, true);
    const gateway = $("auto-configure-gateway");
    if (gateway) gateway.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      configureGateway();
    }, true);
    ["check-steps", "repair-steps"].forEach((id) => $(id).addEventListener("click", (event) => {
      const item = event.target.closest("[data-engine-item]");
      if (!item) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      state.selectedId = item.dataset.engineItem;
      render();
    }, true));
    $("diag-stage").addEventListener("click", (event) => {
      const button = event.target.closest("[data-fix-id]");
      const rollback = event.target.closest("[data-rollback-id]");
      if (!button && !rollback) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (button) planFix(button.dataset.fixId);
      else rollbackFix(rollback.dataset.rollbackId);
    }, true);
    render();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
})();
