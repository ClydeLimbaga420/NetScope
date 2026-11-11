(function () {
  const $ = (id) => document.getElementById(id);
  const state = { checks: [], fixes: [], selectedId: null, report: null, jobId: null, busy: false, admin: null, libraryId: null, detail: null, adminNotice: "", checksLoaded: false };
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
    const run = $("run-engine-diagnosis");
    if (run) {
      run.disabled = busy;
      run.textContent = busy ? (label || "Running...") : "Run diagnosis";
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

  function renderRail(container, items, kind) {
    container.replaceChildren();
    if (!items.length) {
      container.appendChild(element("p", "muted", kind === "repair" ? "Repairs appear when a finding has a catalog fix." : "Run a diagnosis to see checks."));
      return;
    }
    items.forEach((item, index) => {
      const running = item.status === "running";
      const row = element("div", ["diag-row", running ? "running" : ""].filter(Boolean).join(" "));
      const button = element("button", `diag-item ${kind} ${statusClass(item.status)}${item.id === state.selectedId ? " selected" : ""}`);
      button.type = "button";
      button.dataset.engineItem = item.id;
      const number = element("span", "diag-item-index", statusClass(item.status) === "success" ? "✓" : statusClass(item.status) === "error" ? "!" : String(index + 1).padStart(2, "0"));
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
      target.append(element("p", "muted", "Select a repair to see what it does."));
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

    if (entry.explanation) target.append(element("p", "step-reason", entry.explanation));
    if (entry.detection_only) {
      target.append(element("p", "step-reason", "This finding is detection-only. NetScope reports it but does not change the system automatically."));
    }
    target.append(element("p", "engine-fix-facts", `Admin: ${entry.admin ? "required" : "not required"} | Risk: ${entry.risk} | Restart: ${entry.reboot ? "may be required" : "not expected"}`));

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

  function renderRepairLibrary() {
    const list = $("repair-library-list");
    if (!list) return;
    list.replaceChildren();
    if (!state.fixes.length) {
      list.append(element("p", "muted", "Repair catalog is not loaded."));
      return;
    }
    state.fixes.forEach((fix) => {
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
      list.append(row);
    });
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
    const descText = check && item.pending ? "This check has not run yet. Select layers and run a diagnosis." : (check ? (item.message || "No additional detail.") : (item.symptom || item.explanation || "Catalog fix"));
    title.append(element("p", "diag-desc", descText));
    header.append(title, element("span", `step-status ${statusClass(item.status)}`, item.status || "ready"));
    detail.append(header);

    if (check && item.cause && !item.pending) detail.append(element("p", "step-reason", item.cause));
    if (fix) {
      detail.append(element("p", "step-reason", item.explanation));
      detail.append(element("p", "diag-desc", `Risk: ${fix.risk || "unknown"} | Administrator: ${fix.admin ? "required" : "not required"} | Restart: ${fix.reboot ? "may be required" : "not expected"}`));
      const procedure = element("button", "ghost-button", "View full procedure");
      procedure.type = "button";
      procedure.dataset.procedureId = fix.id;
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

  function render() {
    const checks = $("check-steps");
    if (!checks) return;
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
    const index = state.checks.findIndex((item) => item.id === incoming.id);
    if (index >= 0) state.checks[index] = incoming;
    else state.checks.push(incoming);
    // Keep the checklist visible while checks resolve, and drop only stale
    // pending placeholders from the same layer after real results arrive.
    const hasResultsForLayer = state.checks.some((item) => item.layer === incoming.layer && !item.pending);
    if (hasResultsForLayer) {
      state.checks = state.checks.filter((item) => !(item.pending && item.layer === incoming.layer));
    }
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
          job.result.results.forEach(receiveCheck);
        }
      },
    });
  }

  async function runDiagnosis() {
    if (state.busy) return;
    setBusy(true, "Starting diagnosis...");
    if (!state.checks.length) {
      state.checks = [];
      const selectedLayers = Array.from(document.querySelectorAll("input[data-engine-layer]:checked"), (input) => input.dataset.engineLayer);
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
      entry.layer === layer
        ? { ...entry, status: "running", pending: true, message: "", cause: null, evidence: {}, fix_ids: [] }
        : entry
    ));
    state.selectedId = item.id;
    state.report = null;
    setBusy(true, "Running check...");
    try {
      const started = await api("/api/diagnose", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ layers: [layer] }) });
      state.jobId = started.job_id;
      setBusy(true, "Running diagnostics...");
      const job = await followJob(state.jobId);
      if (job.status === "error") throw new Error(job.error || "Diagnosis failed.");
      if (job.status === "cancelled") state.checks.forEach((entry) => { if (entry.status === "running") entry.status = "skip"; });
    } catch (error) {
      state.checks = state.checks.map((entry) => (
        entry.layer === layer && entry.status === "running"
          ? { ...entry, status: "error", message: error.message || "This check could not run." }
          : entry
      ));
      render();
      const stage = $("diag-stage");
      if (stage) stage.append(element("p", "step-reason error", error.message));
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
    const cancel = element("button", "ghost-button", "Cancel run");
    cancel.id = "engine-cancel-job";
    cancel.type = "button";
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
    // Adopt the shared troubleshoot content: replacing each node with a
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
