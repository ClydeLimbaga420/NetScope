const $ = (id) => document.getElementById(id);

const labels = [];
const downloads = [];
const uploads = [];

const SMOOTHING_FACTOR = 0.34;

let smoothedDownload = null;
let smoothedUpload = null;


// =====================================
// HELPERS
// =====================================

function formatSpeed(value) {

    if (!Number.isFinite(value)) {
        return "\u2014";
    }

    if (value === 0) {
        return "0.00";
    }

    if (value < 0.01) {
        return value.toFixed(3);
    }

    if (value < 10) {
        return value.toFixed(2);
    }

    if (value < 100) {
        return value.toFixed(1);
    }

    return value.toFixed(0);

}


function areaGradient(context, color) {

    const { chartArea, ctx } = context.chart;

    if (!chartArea) {
        return "transparent";
    }

    const gradient = ctx.createLinearGradient(
        0,
        chartArea.top,
        0,
        chartArea.bottom
    );

    gradient.addColorStop(0, `${color}59`);
    gradient.addColorStop(0.55, `${color}14`);
    gradient.addColorStop(1, `${color}00`);

    return gradient;

}



// =====================================
// TRAFFIC CHART
// =====================================

let chart = null;
try { chart = new Chart(
    $("traffic-chart"),
    {
        type: "line",

        data: {
            labels: labels,

            datasets: [

                {
                    label: "Download",

                    data: downloads,

                    borderColor: "#62a7ff",

                    backgroundColor: context =>
                        areaGradient(context, "#62a7ff"),

                    fill: true,

                    tension: 0.4,

                    cubicInterpolationMode: "monotone",

                    pointRadius: 0,

                    pointHoverRadius: 4,

                    pointHoverBackgroundColor: "#62a7ff",

                    pointHoverBorderColor: "#0b1020",

                    pointHoverBorderWidth: 2,

                    borderWidth: 2,

                    borderCapStyle: "round",

                    borderJoinStyle: "round"
                },

                {
                    label: "Upload",

                    data: uploads,

                    borderColor: "#39d6a0",

                    backgroundColor: context =>
                        areaGradient(context, "#39d6a0"),

                    fill: true,

                    tension: 0.4,

                    cubicInterpolationMode: "monotone",

                    pointRadius: 0,

                    pointHoverRadius: 4,

                    pointHoverBackgroundColor: "#39d6a0",

                    pointHoverBorderColor: "#0b1020",

                    pointHoverBorderWidth: 2,

                    borderWidth: 2,

                    borderCapStyle: "round",

                    borderJoinStyle: "round"
                }

            ]
        },

        options: {

            responsive: true,

            maintainAspectRatio: false,

            animation: {
                duration: 700,
                easing: "easeOutQuart"
            },

            resizeDelay: 120,

            interaction: {
                intersect: false,
                mode: "index"
            },

            layout: {
                padding: {
                    top: 6,
                    right: 4
                }
            },

            plugins: {

                legend: {

                    position: "top",
                    align: "end",

                    labels: {
                        color: "#aab7ce",
                        usePointStyle: true,
                        pointStyle: "circle",
                        boxWidth: 6,
                        boxHeight: 6,
                        padding: 16,

                        font: {
                            size: 11,
                            family: "Inter, 'Segoe UI', sans-serif"
                        }
                    }

                },

                tooltip: {

                    backgroundColor: "rgba(8, 13, 25, 0.94)",

                    borderColor: "rgba(126, 164, 228, 0.22)",
                    borderWidth: 1,

                    cornerRadius: 10,
                    padding: 11,

                    titleColor: "#eaf1ff",
                    bodyColor: "#aab7ce",

                    displayColors: true,
                    usePointStyle: true,
                    boxPadding: 4,

                    callbacks: {

                        label: context =>
                            `${context.dataset.label}: ` +
                            `${formatSpeed(context.parsed.y)} Mbps`

                    }

                }

            },

            scales: {

                x: {

                    border: {
                        display: false
                    },

                    ticks: {
                        color: "#71819e",
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 6,

                        font: {
                            size: 10
                        }
                    },

                    grid: {
                        display: false
                    }

                },

                y: {

                    beginAtZero: true,

                    grace: "10%",

                    border: {
                        display: false
                    },

                    ticks: {

                        color: "#71819e",
                        padding: 8,

                        font: {
                            size: 10
                        },

                        callback: value =>
                            `${formatSpeed(value)} Mbps`
                    },

                    grid: {
                        color: "rgba(34, 49, 77, 0.55)",
                        drawTicks: false
                    }

                }

            }

        }

    }
); } catch (e) { console.error('chart init failed', e); chart = null; }


// =====================================
// STATUS INDICATOR
// =====================================

function setStatus(element, online) {

    $(element).className =
        `status-dot ${online ? "online" : "offline"}`;

}


// =====================================
// REFRESH NETWORK INFORMATION
// =====================================

async function refreshStatus() {

    try {

        const response = await fetch("/api/status");

        if (response.status === 401) {
            $("internet-status").textContent = "Session expired";
            $("gateway-status").textContent = "Session expired";
            console.error("NetScope session expired; reopen via 'netscope gui'.");
            return;
        }

        if (!response.ok) {
            throw new Error("API request failed");
        }

        const data = await response.json() || {};

        const network = data.network || {};
        const traffic = data.traffic || {};
        const ping = data.internet_ping || {};
        const gatewayPing = data.gateway_ping || {};
        const problems = Array.isArray(data.problems) ? data.problems : [];


        // INTERNET STATUS

        $("internet-status").textContent =
            ping.online ? "Connected" : "Unavailable";

        setStatus("internet-dot", ping.online);

        $("internet-host").textContent =
            `Internet \u00b7 ${ping.host || "1.1.1.1"}`;

        const internetReason = $("internet-reason");

        if (internetReason) {
            const internetProblem = problems.find(
                problem => problem.source === "internet"
            ) || (!ping.online && ping.reason ? { message: ping.reason } : null);

            if (internetProblem && internetProblem.message) {
                internetReason.textContent = internetProblem.message;
                internetReason.hidden = false;
            }
            else {
                internetReason.textContent = "";
                internetReason.hidden = true;
            }
        }


        // GATEWAY STATUS

        $("gateway-status").textContent =
            gatewayPing.online ? "Connected" : "Unavailable";

        setStatus("gateway-dot", gatewayPing.online);

        $("gateway-host").textContent =
            `Gateway \u00b7 ${
                gatewayPing.host ||
                network.gateway ||
                "Not detected"
            }`;

        const gatewayReason = $("gateway-reason");

        if (gatewayReason) {
            const gatewayProblem = problems.find(
                problem => problem.source === "gateway"
            ) || (!gatewayPing.online && gatewayPing.reason
                ? { message: gatewayPing.reason }
                : null);

            if (gatewayProblem && gatewayProblem.message) {
                gatewayReason.textContent = gatewayProblem.message;
                gatewayReason.hidden = false;
            }
            else {
                gatewayReason.textContent = "";
                gatewayReason.hidden = true;
            }
        }


        // BANDWIDTH

        const rawDownload = Number(traffic.download_mbps);
        const rawUpload = Number(traffic.upload_mbps);

        const nextDownload =
            Number.isFinite(rawDownload)
                ? Math.max(rawDownload, 0)
                : 0;

        const nextUpload =
            Number.isFinite(rawUpload)
                ? Math.max(rawUpload, 0)
                : 0;

        smoothedDownload =
            smoothedDownload === null
                ? nextDownload
                : smoothedDownload +
                  (nextDownload - smoothedDownload) *
                  SMOOTHING_FACTOR;

        smoothedUpload =
            smoothedUpload === null
                ? nextUpload
                : smoothedUpload +
                  (nextUpload - smoothedUpload) *
                  SMOOTHING_FACTOR;

        $("download-speed").textContent =
            formatSpeed(smoothedDownload);

        $("upload-speed").textContent =
            formatSpeed(smoothedUpload);


        // LATENCY

        $("latency").textContent =
            ping.latency_ms == null
                ? "\u2014"
                : ping.latency_ms.toFixed(1);


        // NETWORK INFORMATION

        $("hostname").textContent =
            network.hostname || "\u2014";

        $("local-ip").textContent =
            network.local_ip || "\u2014";

        $("gateway").textContent =
            network.gateway || "Not detected";

        $("interface-count").textContent =
            network.interface_count;

        const connectionReason = $("connection-reason");

        if (connectionReason) {
            const diagnosisIssues =
                (network.diagnosis && network.diagnosis.issues) || [];
            const gatewayProblem = problems.find(
                problem => problem.source === "gateway"
            );
            const configProblem = diagnosisIssues.find(
                issue =>
                    issue.id === "wrong-gateway-subnet" ||
                    issue.id === "apipa-address" ||
                    issue.id === "missing-gateway"
            );

            const message =
                (gatewayProblem && gatewayProblem.message) ||
                (configProblem && configProblem.message) ||
                "";

            if (message) {
                connectionReason.textContent = message;
                connectionReason.hidden = false;
            }
            else {
                connectionReason.textContent = "";
                connectionReason.hidden = true;
            }
        }


        // NETWORK ADAPTERS

        const interfacesEl = $("interfaces");
        interfacesEl.replaceChildren();
        if (network.interfaces && network.interfaces.length) {
            network.interfaces.forEach(adapter => {
                const item = document.createElement("div");
                item.className = "adapter";
                const strong = document.createElement("strong");
                strong.textContent = String(adapter.name || "") + (adapter.is_up ? " \u00b7 Up" : " \u00b7 Down");
                const span = document.createElement("span");
                const speed = adapter.speed_mbps ? " \u00b7 " + adapter.speed_mbps + " Mbps" : "";
                span.textContent = String(adapter.ipv4 || "") + speed;
                item.appendChild(strong);
                item.appendChild(span);
                interfacesEl.appendChild(item);
            });
        } else {
            const span = document.createElement("span");
            span.className = "muted";
            span.textContent = "No active IPv4 adapters found.";
            interfacesEl.appendChild(span);
        }


        // TIMESTAMP

        const now = new Date().toLocaleTimeString();

        $("last-updated").textContent = now;

        $("footer-time").textContent =
            `Last refresh ${now}`;


        // UPDATE CHART

        labels.push(now);

        downloads.push(smoothedDownload);

        uploads.push(smoothedUpload);


        // KEEP ONLY LAST 30 READINGS

        if (labels.length > 30) {

            labels.shift();

            downloads.shift();

            uploads.shift();

        }

        if (chart) chart.update();

    }

    catch (error) {

        $("internet-status").textContent = "API error";

        setStatus("internet-dot", false);

        $("gateway-status").textContent = "API error";

        setStatus("gateway-dot", false);

        console.error(error);

    }

}


// =====================================
// HTML ESCAPING
// =====================================

function escapeHtml(value) {

    return String(value).replace(
        /[&<>"']/g,

        character => ({

            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"

        }[character])

    );

}


// =====================================
// DEVICE DISCOVERY
// =====================================

const DEVICE_ALIAS_KEY = "netscope.device-aliases";

const DEVICE_VISIBLE_ROWS = 8;

let deviceNameRetryTimer = null;


function applyDeviceScrollHeight() {

    const wrap = $("device-table-wrap");

    if (!wrap) {
        return;
    }

    const head = wrap.querySelector("thead");
    const rows = wrap.querySelectorAll("tbody tr");

    if (
        !head ||
        rows.length <= DEVICE_VISIBLE_ROWS
    ) {
        wrap.style.maxHeight = "";
        return;
    }

    const horizontalScrollbar = Math.max(
        0,
        wrap.offsetHeight - wrap.clientHeight
    );

    let height = head.offsetHeight + horizontalScrollbar;

    for (
        let index = 0;
        index < DEVICE_VISIBLE_ROWS;
        index += 1
    ) {
        height += rows[index].offsetHeight;
    }

    wrap.style.maxHeight = `${height}px`;

}


function updateDeviceCount(count) {

    const element = $("device-count");

    if (!element) {
        return;
    }

    if (!Number.isFinite(count)) {
        element.textContent = "";
        return;
    }

    element.textContent =
        `${count} device${count === 1 ? "" : "s"}`;

}


function loadDeviceAliases() {

    try {

        const stored = window.localStorage.getItem(
            DEVICE_ALIAS_KEY
        );

        const aliases = stored ? JSON.parse(stored) : {};

        return (
            aliases &&
            typeof aliases === "object" &&
            !Array.isArray(aliases)
        )
            ? aliases
            : {};

    }

    catch {

        return {};

    }

}


function saveDeviceAlias(mac, name) {

    const aliases = loadDeviceAliases();

    if (name) {
        aliases[mac] = name;
    }

    else {
        delete aliases[mac];
    }

    try {

        window.localStorage.setItem(
            DEVICE_ALIAS_KEY,
            JSON.stringify(aliases)
        );

    }

    catch {

        return;

    }

}


function scheduleDeviceNameRetry() {

    if (deviceNameRetryTimer !== null) {
        return;
    }

    deviceNameRetryTimer = window.setTimeout(
        () => {

            deviceNameRetryTimer = null;

            refreshDevices({ retry: false, silent: true });

        },
        6000
    );

}


async function refreshDevices({ retry = true, silent = false } = {}) {

    const body = $("device-rows");

    let missingNames = false;

    if (!silent) {
        body.replaceChildren();
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 6;
        td.className = "empty";
        td.textContent = "Scanning local network and resolving names...";
        tr.appendChild(td);
        body.appendChild(tr);
    }

    try {

        const response = await fetch("/api/devices");

        if (response.status === 401) {
            body.replaceChildren();
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 6;
            td.className = "empty";
            td.textContent = "Session expired. Reopen NetScope via 'netscope gui'."
            tr.appendChild(td);
            body.appendChild(tr);
            updateDeviceCount(null);
            return;
        }


        const data = await response.json() || {};
        const devices = Array.isArray(data.devices) ? data.devices : [];

        const aliases = loadDeviceAliases();

        if (devices.length > 0) {

            missingNames = data.devices.some(
                device => !(aliases[device.mac] || device.name)
            );

            body.replaceChildren();
            devices.forEach(device => {
                const name = aliases[device.mac] || device.name;
                const label = name || "Unnamed device";
                const nameClass = name ? "device-name" : "device-name unnamed";
                const vendorLabel = device.vendor || "Unknown";
                const vendorClass = device.vendor === "Private MAC"
                    ? "device-brand private"
                    : device.vendor ? "device-brand" : "device-brand unknown";
                const vendorTitle = device.vendor === "Private MAC"
                    ? "Randomized or locally administered MAC address"
                    : "Vendor derived from the MAC address";

                const tr = document.createElement("tr");

                const tdName = document.createElement("td");
                const nameSpan = document.createElement("span");
                nameSpan.className = nameClass;
                nameSpan.dataset.mac = String(device.mac || "");
                nameSpan.title = "Double-click to rename";
                nameSpan.textContent = String(label);
                tdName.appendChild(nameSpan);

                const tdBrand = document.createElement("td");
                const brandSpan = document.createElement("span");
                brandSpan.className = vendorClass;
                brandSpan.title = vendorTitle;
                brandSpan.textContent = String(vendorLabel);
                tdBrand.appendChild(brandSpan);

                const tdIp = document.createElement("td");
                tdIp.textContent = String(device.ip || "");
                const tdMac = document.createElement("td");
                const macSpan = document.createElement("span");
                macSpan.className = "device-mac";
                macSpan.title = String(device.mac_note || "");
                macSpan.textContent = String(
                    device.hardware_mac || device.mac || ""
                );
                tdMac.appendChild(macSpan);
                if (device.mac_randomized) {
                    const macBadge = document.createElement("span");
                    macBadge.className = "device-mac-badge";
                    macBadge.title = String(
                        device.mac_note ||
                        "Hardware MAC hidden by this device"
                    );
                    macBadge.textContent = "randomized";
                    tdMac.appendChild(macBadge);
                }
                const tdConnection = document.createElement("td");
                const connectionSpan = document.createElement("span");
                const connectionLabel = String(device.connection || "Unknown");
                connectionSpan.className = "device-connection " +
                    connectionLabel.toLowerCase().replace(/\s+/g, "-");
                connectionSpan.title = String(device.connection_detail || "");
                connectionSpan.textContent = connectionLabel;
                tdConnection.appendChild(connectionSpan);
                const tdType = document.createElement("td");
                tdType.textContent = String(device.type || "");

                tr.appendChild(tdName);
                tr.appendChild(tdBrand);
                tr.appendChild(tdIp);
                tr.appendChild(tdMac);
                tr.appendChild(tdConnection);
                tr.appendChild(tdType);
                body.appendChild(tr);
            });

        }

        else {
            body.replaceChildren();
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.colSpan = 6;
            td.className = "empty";
            td.textContent = "No devices found. Make sure you are connected to a local network, then refresh devices.";
            tr.appendChild(td);
            body.appendChild(tr);
        }

        updateDeviceCount(devices.length);

        applyDeviceScrollHeight();

        if (retry && missingNames) {
            scheduleDeviceNameRetry();
        }

    }

    catch (error) {
        body.replaceChildren();
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 6;
        td.className = "empty";
        td.textContent = "Could not retrieve device list.";
        tr.appendChild(td);
        body.appendChild(tr);

        updateDeviceCount(null);
        applyDeviceScrollHeight();
        console.error(error);
    }

}


// =====================================
// TROUBLESHOOTING
// =====================================

let diagnosticSteps = [];

let diagnosticElevated = false;

const diagnosticStates = {};

let selectedDiagnosticId = null;


function statusLabel(step, status) {

    if (status === "running") {
        return "Running";
    }

    if (status === "success") {
        return step.kind === "repair" ? "Completed" : "Passed";
    }

    if (status === "error") {
        return "Failed";
    }

    return "Not run";

}


function updateDiagnosticsSummary() {

    const checks = diagnosticSteps.filter(
        step => step.kind === "check"
    );

    const repairs = diagnosticSteps.filter(
        step => step.kind === "repair"
    );

    const passed = checks.filter(
        step => (diagnosticStates[step.id] || {}).status === "success"
    ).length;

    const failed = checks.filter(
        step => (diagnosticStates[step.id] || {}).status === "error"
    ).length;

    const completedRepairs = repairs.filter(
        step => (diagnosticStates[step.id] || {}).status === "success"
    ).length;

    let summary = `${passed} of ${checks.length} checks passed`;

    if (failed > 0) {
        summary += ` \u00b7 ${failed} failed`;
    }

    if (repairs.length > 0) {
        summary += ` \u00b7 ${completedRepairs} of ${repairs.length} repairs applied`;
    }

    $("troubleshoot-summary").textContent = summary;

    const percent = checks.length
        ? Math.round(((passed + failed) / checks.length) * 100)
        : 0;

    $("troubleshoot-percent").textContent = `${percent}%`;

    const fill = $("diag-progress-fill");

    if (fill) {
        fill.style.width = `${percent}%`;
    }

}


function stepMarker(step, status, index) {

    if (status === "success") {
        return "\u2713";
    }

    if (status === "error") {
        return "!";
    }

    if (status === "running") {
        return "\u2026";
    }

    return String(index + 1).padStart(2, "0");

}


function renderRailGroup(steps, container) {
    container.replaceChildren();
    if (!steps.length) {
        return;
    }
    steps.forEach(step => {
        const index = diagnosticSteps.indexOf(step);
        const status = (diagnosticStates[step.id] || {}).status || "idle";
        const selected = step.id === selectedDiagnosticId ? "selected" : "";
        const unavailable = !step.supported || !step.available;

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = ["diag-item", step.kind, status, selected, unavailable ? "unavailable" : ""].filter(Boolean).join(" ");
        btn.dataset.id = String(step.id || "");

        const idx = document.createElement("span");
        idx.className = "diag-item-index";
        idx.textContent = String(stepMarker(step, status, index));

        const textWrap = document.createElement("span");
        textWrap.className = "diag-item-text";
        const strong = document.createElement("strong");
        strong.textContent = String(step.title || "");
        const small = document.createElement("small");
        small.textContent = String(statusLabel(step, status));
        textWrap.appendChild(strong);
        textWrap.appendChild(small);

        btn.appendChild(idx);
        btn.appendChild(textWrap);
        container.appendChild(btn);
    });
}


function renderConsole(container, step, state) {
    container.replaceChildren();
    if (!state || !state.result) {
        const ph = document.createElement("span");
        ph.className = "console-placeholder";
        ph.textContent = "Run this step to see its command output here.";
        container.appendChild(ph);
        return;
    }

    const result = state.result;
    const success = Boolean(result.success);
    const statusClass = success ? "success" : "error";
    const command = (result.commands && result.commands.length)
        ? result.commands.join("  &&  ")
        : (step.command || "");

    const entry = document.createElement("div");
    entry.className = "console-entry";

    const head = document.createElement("div");
    head.className = "console-entry-head";

    const cmd = document.createElement("span");
    cmd.className = "console-command";
    cmd.textContent = String(command);

    const meta = document.createElement("span");
    meta.className = "console-meta";

    const st = document.createElement("span");
    st.className = "console-status " + statusClass;
    st.textContent = success ? "Success" : "Failed";
    meta.appendChild(st);

    if (Number.isFinite(result.duration_ms)) {
        const t = document.createElement("span");
        t.className = "console-time";
        t.textContent = result.duration_ms + " ms";
        meta.appendChild(t);
    }

    head.appendChild(cmd);
    head.appendChild(meta);
    entry.appendChild(head);

    if (result.reason) {
        const r = document.createElement("p");
        r.className = "console-reason " + statusClass;
        r.textContent = String(result.reason);
        entry.appendChild(r);
    }

    const pre = document.createElement("pre");
    pre.className = "console-text";
    pre.textContent = result.output || "No output.";
    entry.appendChild(pre);

    container.appendChild(entry);
}


function renderDetail() {
    const stage = $("diag-stage");
    if (!stage) return;

    if (!diagnosticSteps.length) {
        stage.replaceChildren();
        const p = document.createElement("p");
        p.className = "muted";
        p.textContent = "No troubleshooting steps are available.";
        stage.appendChild(p);
        return;
    }

    const step = diagnosticSteps.find(item => item.id === selectedDiagnosticId) || diagnosticSteps[0];
    if (!selectedDiagnosticId) {
        selectedDiagnosticId = step.id;
    }

    const state = diagnosticStates[step.id] || {};
    const status = state.status || "idle";
    const disabled = !step.supported || !step.available || status === "running";
    const kindLabel = step.kind === "repair" ? "REPAIR" : "CHECK";
    const runLabel = step.kind === "repair" ? "Run repair" : "Run check";

    const hint = status === "running"
        ? "Running the predefined command..."
        : step.kind === "repair"
            ? "This repair changes your network settings."
            : "Read-only check. Nothing on your system is changed.";

    stage.replaceChildren();

    const detail = document.createElement("div");
    detail.className = ["diag-detail", step.kind, status].filter(Boolean).join(" ");

    const head = document.createElement("div");
    head.className = "diag-detail-head";

    const titleWrap = document.createElement("div");
    titleWrap.className = "diag-detail-title";

    const tags = document.createElement("div");
    tags.className = "diag-tags";
    const kind = document.createElement("span");
    kind.className = "step-kind " + (step.kind || "check");
    kind.textContent = kindLabel;
    tags.appendChild(kind);
    if (step.requires_admin) {
        const admin = document.createElement("span");
        admin.className = "admin-tag";
        admin.textContent = "ADMIN";
        tags.appendChild(admin);
    }
    titleWrap.appendChild(tags);

    const h3 = document.createElement("h3");
    h3.textContent = String(step.title || "");
    titleWrap.appendChild(h3);

    const desc = document.createElement("p");
    desc.className = "diag-desc";
    desc.textContent = String(step.description || "");
    titleWrap.appendChild(desc);

    head.appendChild(titleWrap);

    const statusEl = document.createElement("span");
    statusEl.className = "step-status " + status;
    statusEl.textContent = statusLabel(step, status);
    head.appendChild(statusEl);

    detail.appendChild(head);

    const cmdBox = document.createElement("div");
    cmdBox.className = "diag-command";
    const cmdLabel = document.createElement("span");
    cmdLabel.className = "diag-command-label";
    cmdLabel.textContent = "PREDEFINED COMMAND";
    const code = document.createElement("code");
    code.textContent = String(step.command || "");
    cmdBox.appendChild(cmdLabel);
    cmdBox.appendChild(code);
    detail.appendChild(cmdBox);

    if (step.reason && (!step.supported || !step.available)) {
        const p = document.createElement("p");
        p.className = "step-reason";
        p.textContent = String(step.reason);
        detail.appendChild(p);
    }
    if (state.result && state.result.reason && step.supported && step.available) {
        const p = document.createElement("p");
        p.className = "step-reason" + (status === "error" ? " error" : "");
        p.textContent = String(state.result.reason);
        detail.appendChild(p);
    }

    const actions = document.createElement("div");
    actions.className = "diag-detail-actions";
    const hintEl = document.createElement("span");
    hintEl.className = "diag-detail-hint";
    hintEl.textContent = hint;
    const runBtn = document.createElement("button");
    runBtn.className = "step-run";
    runBtn.type = "button";
    runBtn.dataset.id = String(step.id || "");
    runBtn.disabled = Boolean(disabled);
    runBtn.textContent = status === "running" ? "Running..." : runLabel;
    actions.appendChild(hintEl);
    actions.appendChild(runBtn);
    detail.appendChild(actions);

    const consolePanel = document.createElement("div");
    consolePanel.className = "console-panel";

    const consoleHead = document.createElement("div");
    consoleHead.className = "console-head";
    const consoleTitle = document.createElement("span");
    consoleTitle.className = "console-title";
    consoleTitle.textContent = "COMMAND OUTPUT";
    const consoleActions = document.createElement("span");
    consoleActions.className = "console-actions";
    const consoleTime = document.createElement("span");
    consoleTime.className = "console-time";
    consoleTime.textContent = step.kind === "repair" ? "Changes system settings" : "Read-only";
    const clearBtn = document.createElement("button");
    clearBtn.className = "ghost-button";
    clearBtn.id = "clear-console";
    clearBtn.type = "button";
    clearBtn.textContent = "Clear";
    consoleActions.appendChild(consoleTime);
    consoleActions.appendChild(clearBtn);
    consoleHead.appendChild(consoleTitle);
    consoleHead.appendChild(consoleActions);

    const consoleBox = document.createElement("div");
    consoleBox.className = "console";
    consoleBox.id = "console-output";
    renderConsole(consoleBox, step, state);

    consolePanel.appendChild(consoleHead);
    consolePanel.appendChild(consoleBox);
    detail.appendChild(consolePanel);

    stage.appendChild(detail);

    if (consoleBox) {
        consoleBox.scrollTop = consoleBox.scrollHeight;
    }
}


function renderDiagnostics() {

    if (!diagnosticSteps.length) {
        $("check-steps").replaceChildren();
        $("repair-steps").replaceChildren();
        const stage = $("diag-stage");
        stage.replaceChildren();
        const p = document.createElement("p");
        p.className = "muted";
        p.textContent = "No troubleshooting steps are available.";
        stage.appendChild(p);
        return;
    }

    renderRailGroup(
        diagnosticSteps.filter(step => step.kind === "check"),
        $("check-steps")
    );

    renderRailGroup(
        diagnosticSteps.filter(step => step.kind === "repair"),
        $("repair-steps")
    );

    renderDetail();

}


async function runDiagnostic(step) {

    if ((diagnosticStates[step.id] || {}).status === "running") {
        return;
    }

    if (step.kind === "repair") {

        const adminWarning =
            step.requires_admin && !diagnosticElevated

                ? "NetScope is not running as administrator, " +
                  "so this repair may fail.\n\n"

                : "";

        const confirmed = window.confirm(
            adminWarning +
            `${step.title} will change this computer's ` +
            "network settings.\n\nContinue?"
        );

        if (!confirmed) {
            return;
        }

    }

    selectedDiagnosticId = step.id;

    diagnosticStates[step.id] = { status: "running" };

    renderDiagnostics();
    updateDiagnosticsSummary();

    try {

        const response = await fetch(
            `/api/diagnostics/${encodeURIComponent(step.id)}/run`,
            { method: "POST" }
        );

        if (!response.ok) {
            throw new Error("Diagnostic request failed");
        }

        const result = await response.json();

        diagnosticStates[step.id] = {
            status: result.success ? "success" : "error",
            result: result
        };

    }

    catch (error) {

        diagnosticStates[step.id] = {
            status: "error",
            result: {
                success: false,
                commands: [],
                output: `Could not run this step: ${error.message}`,
                duration_ms: null
            }
        };

        console.error(error);

    }

    finally {

        renderDiagnostics();
        updateDiagnosticsSummary();

    }

}


async function runAllChecks() {

    const button = $("run-all-checks");
    const engineButton = $("run-engine-diagnosis");

    const checks = diagnosticSteps.filter(
        step =>
            step.kind === "check" &&
            step.supported &&
            step.available
    );

    if (!checks.length) {
        return;
    }

    button.disabled = true;
    if (engineButton) engineButton.disabled = true;
    button.textContent = "Running checks 1–7...";

    for (const step of checks) {

        selectedDiagnosticId = step.id;

        renderDiagnostics();

        await runDiagnostic(step);

    }

    button.disabled = false;
    if (engineButton) engineButton.disabled = false;
    button.textContent = "Run all checks (1–7)";

}


async function loadDiagnostics() {

    try {

        const response = await fetch("/api/diagnostics");

        if (!response.ok) {
            throw new Error("Could not load diagnostics");
        }

        const data = await response.json();

        diagnosticSteps = data.steps || [];

        diagnosticElevated = Boolean(data.elevated);

        if (
            !selectedDiagnosticId &&
            diagnosticSteps.length > 0
        ) {
            selectedDiagnosticId = diagnosticSteps[0].id;
        }

        const badge = $("elevation-badge");

        if (badge) {

            badge.textContent = diagnosticElevated
                ? "ADMIN MODE"
                : "STANDARD USER";

            badge.className = diagnosticElevated
                ? "elevation-badge elevated"
                : "elevation-badge";

            badge.hidden = false;

        }

        renderDiagnostics();
        updateDiagnosticsSummary();

    }

    catch (error) {
        $("check-steps").replaceChildren();
        $("repair-steps").replaceChildren();
        const stage = $("diag-stage");
        stage.replaceChildren();
        const p = document.createElement("p");
        p.className = "muted";
        p.textContent = "Could not load troubleshooting steps.";
        stage.appendChild(p);
        $("troubleshoot-summary").textContent = "Troubleshooting is unavailable.";
        console.error(error);
    }

}


// =====================================
// EVENT LISTENERS
// =====================================

const refreshDevicesEl = $("refresh-devices");
if (refreshDevicesEl) refreshDevicesEl.addEventListener(
    "click",
    () => refreshDevices()
);


window.addEventListener(
    "resize",
    applyDeviceScrollHeight
);


function selectDiagnosticStep(event) {

    const item = event.target.closest(".diag-item");

    if (!item) {
        return;
    }

    selectedDiagnosticId = item.dataset.id;

    renderDiagnostics();

}


const checkStepsEl = $("check-steps");
if (checkStepsEl) checkStepsEl.addEventListener(
    "click",
    selectDiagnosticStep
);


const repairStepsEl = $("repair-steps");
if (repairStepsEl) repairStepsEl.addEventListener(
    "click",
    selectDiagnosticStep
);


const diagStageEl = $("diag-stage");
if (diagStageEl) diagStageEl.addEventListener(
    "click",
    event => {

        const runButton = event.target.closest(".step-run");

        if (runButton) {

            const step = diagnosticSteps.find(
                item => item.id === runButton.dataset.id
            );

            if (step) {
                runDiagnostic(step);
            }

            return;

        }

        const clearButton = event.target.closest("#clear-console");

        if (clearButton) {

            const step = diagnosticSteps.find(
                item => item.id === selectedDiagnosticId
            );

            if (step) {

                delete diagnosticStates[step.id];

                renderDiagnostics();
                updateDiagnosticsSummary();

            }

        }

    }
);


$("run-all-checks").addEventListener(
    "click",
    runAllChecks
);


$("device-rows").addEventListener(
    "dblclick",
    event => {

        const cell = event.target.closest(".device-name");

        if (!cell) {
            return;
        }

        const mac = cell.dataset.mac;

        const aliases = loadDeviceAliases();

        const displayed = cell.textContent.trim();

        const current =
            aliases[mac] ||
            (displayed === "Unnamed device" ? "" : displayed);

        const name = window.prompt("Device name", current);

        if (name === null) {
            return;
        }

        saveDeviceAlias(mac, name.trim());

        refreshDevices();

    }
);


// =====================================
// PAGE NAVIGATION
// =====================================

function showView(viewName, options = {}) {

    const { updateHash = true, scrollToId = null } = options;

    document.querySelectorAll('.page-view[data-view]').forEach(page => {
        page.classList.toggle('active', page.dataset.view === viewName);
    });

    document.querySelectorAll('.nav-item[data-view]').forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewName);
    });

    if (updateHash) {
        const hash = viewName === 'troubleshoot'
            ? '#troubleshoot'
            : viewName === 'repairs'
                ? '#repairs'
                : '#overview';
        if (window.location.hash !== hash) {
            window.history.replaceState(null, '', hash);
        }
    }

    if (viewName === 'main') {
        window.requestAnimationFrame(() => {
            applyDeviceScrollHeight();
            if (typeof chart !== 'undefined') {
                if (chart) chart.resize();
                if (chart) chart.update();
            }
        });
        if (scrollToId) {
            window.requestAnimationFrame(() => {
                const target = document.getElementById(scrollToId);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
                else {
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }
            });
        }
        else {
            window.scrollTo({ top: 0, behavior: 'auto' });
        }
    }
    else if (viewName === 'troubleshoot') {
        window.requestAnimationFrame(() => {
            renderDiagnostics();
            updateDiagnosticsSummary();
        });
        window.scrollTo({ top: 0, behavior: 'auto' });
    }
    else if (viewName === 'repairs') {
        window.scrollTo({ top: 0, behavior: 'auto' });
    }

}

document.querySelectorAll('.nav-item[data-view]').forEach(item => {

    item.addEventListener('click', event => {
        event.preventDefault();
        const view = item.dataset.view;
        const scrollToId = item.dataset.scroll || null;
        showView(view, { scrollToId });
    });

});


// =====================================
// PACKET LOSS MONITORING
// =====================================

let packetLossInFlight = false;

async function refreshPacketLoss() {

    if (packetLossInFlight) {
        return;
    }

    packetLossInFlight = true;

    const value = $("packet-loss");
    const detail = $("packet-loss-detail");

    if (!value || !detail) {
        packetLossInFlight = false;
        return;
    }

    try {

        const response = await fetch("/api/packet-loss");

        if (!response.ok) {
            throw new Error("Packet loss request failed");
        }

        const data = await response.json();
        const internet = data.internet || {};
        const gateway = data.gateway || {};
        const internetLoss = internet.packet_loss_percent;
        const gatewayLoss = gateway.packet_loss_percent;

        if (Number.isFinite(internetLoss)) {
            value.textContent = internetLoss.toFixed(internetLoss % 1 === 0 ? 0 : 1);
        }
        else {
            value.textContent = "\u2014";
        }

        const parts = [
            Number.isFinite(internetLoss)
                ? `Internet: ${internetLoss.toFixed(internetLoss % 1 === 0 ? 0 : 1)}% (${internet.packets_received || 0}/${internet.packets_sent || data.count || 0})`
                : "Internet: unavailable"
        ];

        if (gateway.host) {
            if (Number.isFinite(gatewayLoss)) {
                parts.push(`Gateway: ${gatewayLoss.toFixed(gatewayLoss % 1 === 0 ? 0 : 1)}%`);
            }
            else {
                parts.push("Gateway: unavailable");
            }
        }
        else {
            parts.push("Gateway: not detected");
        }

        detail.textContent = parts.join(" \u00b7 ");

    }

    catch (error) {

        detail.textContent = "Could not measure packet loss.";
        console.error(error);

    }

    finally {

        packetLossInFlight = false;

    }

}

// =====================================
// INITIALIZATION
// =====================================

const initialHash = (window.location.hash || "#overview").replace("#", "");
if (initialHash === "troubleshoot") {
    showView("troubleshoot");
}
else if (initialHash === "repairs") {
    showView("repairs");
}
else if (initialHash === "devices" || initialHash === "traffic") {
    showView("main", { scrollToId: initialHash });
}
else {
    showView("main", { scrollToId: "overview-top" });
}

refreshStatus();

refreshDevices();

refreshPacketLoss();


loadDiagnostics();


// UPDATE EVERY 2 SECONDS

setInterval(refreshStatus, 2000);
setInterval(refreshPacketLoss, 30000);
