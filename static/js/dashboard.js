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
        return "—";
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

const chart = new Chart(
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
);


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

        if (!response.ok) {
            throw new Error("API request failed");
        }

        const data = await response.json();

        const network = data.network;
        const traffic = data.traffic;
        const ping = data.internet_ping;


        // INTERNET STATUS

        $("internet-status").textContent =
            ping.online ? "Connected" : "Unavailable";

        setStatus("internet-dot", ping.online);

        $("internet-host").textContent =
            `Target: ${ping.host || "1.1.1.1"}`;


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
            ping.latency_ms === null
                ? "—"
                : ping.latency_ms.toFixed(1);


        // NETWORK INFORMATION

        $("hostname").textContent =
            network.hostname || "—";

        $("local-ip").textContent =
            network.local_ip || "—";

        $("gateway").textContent =
            network.gateway || "Not detected";

        $("interface-count").textContent =
            network.interface_count;


        // NETWORK ADAPTERS

        $("interfaces").innerHTML =
            network.interfaces.length

                ? network.interfaces.map(adapter => `

                    <div class="adapter">

                        <strong>
                            ${escapeHtml(adapter.name)}
                            ${adapter.is_up ? "· Up" : "· Down"}
                        </strong>

                        <span>
                            ${escapeHtml(adapter.ipv4)}

                            ${
                                adapter.speed_mbps
                                    ? " · " + adapter.speed_mbps + " Mbps"
                                    : ""
                            }
                        </span>

                    </div>

                `).join("")

                : '<span class="muted">No active IPv4 adapters found.</span>';


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

        chart.update();

    }

    catch (error) {

        $("internet-status").textContent = "API error";

        setStatus("internet-dot", false);

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

        body.innerHTML = `

            <tr>
                <td colspan="5" class="empty">
                    Scanning local network and resolving names...
                </td>
            </tr>

        `;

    }

    try {

        const response = await fetch("/api/devices");

        const data = await response.json();

        const aliases = loadDeviceAliases();

        if (data.devices.length > 0) {

            missingNames = data.devices.some(
                device => !(aliases[device.mac] || device.name)
            );

            body.innerHTML = data.devices.map(device => {

                const name =
                    aliases[device.mac] ||
                    device.name;

                const label = name || "Unnamed device";

                const nameClass = name
                    ? "device-name"
                    : "device-name unnamed";

                const vendorLabel = device.vendor || "Unknown";

                const vendorClass = device.vendor === "Private MAC"
                    ? "device-brand private"
                    : device.vendor
                        ? "device-brand"
                        : "device-brand unknown";

                const vendorTitle = device.vendor === "Private MAC"
                    ? "Randomized or locally administered MAC address"
                    : "Vendor derived from the MAC address";

                return `

                    <tr>

                        <td>
                            <span
                                class="${nameClass}"
                                data-mac="${escapeHtml(device.mac)}"
                                title="Double-click to rename">
                                ${escapeHtml(label)}
                            </span>
                        </td>

                        <td>
                            <span
                                class="${vendorClass}"
                                title="${vendorTitle}">
                                ${escapeHtml(vendorLabel)}
                            </span>
                        </td>

                        <td>
                            ${escapeHtml(device.ip)}
                        </td>

                        <td>
                            ${escapeHtml(device.mac)}
                        </td>

                        <td>
                            ${escapeHtml(device.type)}
                        </td>

                    </tr>

                `;

            }).join("");

        }

        else {

            body.innerHTML = `

                <tr>

                    <td colspan="5" class="empty">

                        No devices found.

                        Make sure you are connected to a local network,
                        then refresh devices.

                    </td>

                </tr>

            `;

        }

        updateDeviceCount(data.devices.length);

        applyDeviceScrollHeight();

        if (retry && missingNames) {
            scheduleDeviceNameRetry();
        }

    }

    catch (error) {

        body.innerHTML = `

            <tr>

                <td colspan="5" class="empty">

                    Could not retrieve device list.

                </td>

            </tr>

        `;

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
        summary += ` · ${failed} failed`;
    }

    if (repairs.length > 0) {
        summary += ` · ${completedRepairs} of ${repairs.length} repairs applied`;
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
        return "✓";
    }

    if (status === "error") {
        return "!";
    }

    if (status === "running") {
        return "…";
    }

    return String(index + 1).padStart(2, "0");

}


function renderRailGroup(steps, container) {

    if (!steps.length) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = steps.map(step => {

        const index = diagnosticSteps.indexOf(step);

        const status =
            (diagnosticStates[step.id] || {}).status || "idle";

        const selected =
            step.id === selectedDiagnosticId ? "selected" : "";

        const unavailable =
            !step.supported || !step.available;

        return `

            <button
                class="diag-item ${step.kind} ${status} ${selected} ${
                    unavailable ? "unavailable" : ""
                }"
                type="button"
                data-id="${escapeHtml(step.id)}">

                <span class="diag-item-index">
                    ${stepMarker(step, status, index)}
                </span>

                <span class="diag-item-text">
                    <strong>${escapeHtml(step.title)}</strong>
                    <small>${statusLabel(step, status)}</small>
                </span>

            </button>

        `;

    }).join("");

}


function consoleMarkup(step, state) {

    if (!state || !state.result) {

        return `

            <span class="console-placeholder">
                Run this step to see its command output here.
            </span>

        `;

    }

    const result = state.result;

    const success = Boolean(result.success);

    const statusClass = success ? "success" : "error";

    const command = (result.commands && result.commands.length)

        ? result.commands.join("  &&  ")

        : step.command;

    const duration = Number.isFinite(result.duration_ms)
        ? `${result.duration_ms} ms`
        : "";

    return `

        <div class="console-entry">

            <div class="console-entry-head">

                <span class="console-command">
                    ${escapeHtml(command)}
                </span>

                <span class="console-meta">

                    <span class="console-status ${statusClass}">
                        ${success ? "Success" : "Failed"}
                    </span>

                    ${duration
                        ? `<span class="console-time">${duration}</span>`
                        : ""}

                </span>

            </div>

            <pre class="console-text">${escapeHtml(
                result.output || "No output."
            )}</pre>

        </div>

    `;

}


function renderDetail() {

    const stage = $("diag-stage");

    if (!diagnosticSteps.length) {

        stage.innerHTML = `
            <p class="muted">No troubleshooting steps are available.</p>
        `;

        return;

    }

    const step = diagnosticSteps.find(
        item => item.id === selectedDiagnosticId
    ) || diagnosticSteps[0];

    if (!selectedDiagnosticId) {
        selectedDiagnosticId = step.id;
    }

    const state = diagnosticStates[step.id] || {};

    const status = state.status || "idle";

    const disabled =
        !step.supported ||
        !step.available ||
        status === "running";

    const kindLabel =
        step.kind === "repair" ? "REPAIR" : "CHECK";

    const runLabel =
        step.kind === "repair" ? "Run repair" : "Run check";

    const admin = step.requires_admin
        ? '<span class="admin-tag">ADMIN</span>'
        : "";

    const unavailable =
        step.reason && (!step.supported || !step.available)

            ? `<p class="step-reason">${escapeHtml(step.reason)}</p>`

            : "";

    const hint = status === "running"

        ? "Running the predefined command..."

        : step.kind === "repair"

            ? "This repair changes your network settings."

            : "Read-only check. Nothing on your system is changed.";

    stage.innerHTML = `

        <div class="diag-detail ${step.kind} ${status}">

            <div class="diag-detail-head">

                <div class="diag-detail-title">

                    <div class="diag-tags">

                        <span class="step-kind ${step.kind}">
                            ${kindLabel}
                        </span>

                        ${admin}

                    </div>

                    <h3>${escapeHtml(step.title)}</h3>

                    <p class="diag-desc">
                        ${escapeHtml(step.description)}
                    </p>

                </div>

                <span class="step-status ${status}">
                    ${statusLabel(step, status)}
                </span>

            </div>

            <div class="diag-command">

                <span class="diag-command-label">
                    PREDEFINED COMMAND
                </span>

                <code>${escapeHtml(step.command)}</code>

            </div>

            ${unavailable}

            <div class="diag-detail-actions">

                <span class="diag-detail-hint">${hint}</span>

                <button
                    class="step-run"
                    type="button"
                    data-id="${escapeHtml(step.id)}"
                    ${disabled ? "disabled" : ""}>
                    ${
                        status === "running"
                            ? "Running..."
                            : runLabel
                    }
                </button>

            </div>

            <div class="console-panel">

                <div class="console-head">

                    <span class="console-title">COMMAND OUTPUT</span>

                    <span class="console-actions">

                        <span class="console-time">
                            ${step.kind === "repair"
                                ? "Changes system settings"
                                : "Read-only"}
                        </span>

                        <button
                            class="ghost-button"
                            id="clear-console"
                            type="button">
                            Clear
                        </button>

                    </span>

                </div>

                <div class="console" id="console-output">
                    ${consoleMarkup(step, state)}
                </div>

            </div>

        </div>

    `;

    const consoleBox = $("console-output");

    if (consoleBox) {
        consoleBox.scrollTop = consoleBox.scrollHeight;
    }

}


function renderDiagnostics() {

    if (!diagnosticSteps.length) {

        $("check-steps").innerHTML = "";
        $("repair-steps").innerHTML = "";

        $("diag-stage").innerHTML = `
            <p class="muted">No troubleshooting steps are available.</p>
        `;

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
    button.textContent = "Running checks...";

    for (const step of checks) {

        selectedDiagnosticId = step.id;

        renderDiagnostics();

        await runDiagnostic(step);

    }

    button.disabled = false;
    button.textContent = "Run all checks";

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

        $("check-steps").innerHTML = "";
        $("repair-steps").innerHTML = "";

        $("diag-stage").innerHTML =
            '<p class="muted">Could not load troubleshooting steps.</p>';

        $("troubleshoot-summary").textContent =
            "Troubleshooting is unavailable.";

        console.error(error);

    }

}


// =====================================
// EVENT LISTENERS
// =====================================

$("refresh-devices").addEventListener(
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


$("check-steps").addEventListener(
    "click",
    selectDiagnosticStep
);


$("repair-steps").addEventListener(
    "click",
    selectDiagnosticStep
);


$("diag-stage").addEventListener(
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
// INITIALIZATION
// =====================================

refreshStatus();

refreshDevices();

loadDiagnostics();


// UPDATE EVERY 2 SECONDS

setInterval(refreshStatus, 2000);