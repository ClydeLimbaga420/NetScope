const $ = (id) => document.getElementById(id);

const labels = [];
const downloads = [];
const uploads = [];

// Real (unfloored) rates, kept in sync with the plotted arrays so tooltips keep
// reporting the true speed while the line stays visible at zero traffic.
const realDownloads = [];
const realUploads = [];

// A flat zero trace is drawn on top of the x-axis and looks like the chart
// disappeared when the internet drops. Plot a tiny floor and reserve a minimum
// y-axis ceiling so an idle line sits just above the baseline instead.
const TRAFFIC_FLOOR_MBPS = 0.05;
const TRAFFIC_MIN_CEILING_MBPS = 1;

// Let each chart animation run for the whole gap between samples so the line
// slides continuously instead of jumping and then sitting still. A five-second
// cadence also gives slow /api/status responses time to finish: overlapping
// refreshes used to interrupt the animation and make the trace disappear after
// the dashboard had been open a while.
const STATUS_POLL_INTERVAL_MS = 5000;
const TRAFFIC_HISTORY_LENGTH = 60; // five minutes at the five-second cadence
const SMOOTHING_FACTOR = 0.28;
const TRAFFIC_DROP_FACTOR = 0.7;
// Finish a stalled poll before the next interval fires; an abort at exactly
// the poll interval used to produce a ten-second gap and a frozen animation.
const STATUS_ABORT_TIMEOUT_MS = STATUS_POLL_INTERVAL_MS - 1000;

const REDUCED_MOTION =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let statusInFlight = false;
let smoothedDownload = null;
let smoothedUpload = null;
let trafficCeiling = TRAFFIC_MIN_CEILING_MBPS;
let lastTrafficDownload = 0;
let lastTrafficUpload = 0;
let lastTrafficSampleAt = 0;


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


function visibleTraffic(value) {

    return Math.max(Number.isFinite(value) ? value : 0, TRAFFIC_FLOOR_MBPS);

}


// Chart.js auto-scales to the largest value in the whole 60-sample window, so
// after a burst the 0.05 idle floor becomes sub-pixel and the trace looks gone.
// Drive the y ceiling from the current rate instead: grow immediately for a
// burst, ease back down when traffic stops, and snap to the small idle range
// once the line reaches the floor.
function updateTrafficCeiling(download, upload) {

    const current = Math.max(visibleTraffic(download), visibleTraffic(upload));
    const target = Math.max(TRAFFIC_MIN_CEILING_MBPS, current * 1.25);

    if (current <= TRAFFIC_FLOOR_MBPS + 0.001) {
        trafficCeiling = TRAFFIC_MIN_CEILING_MBPS;
    }
    else {
        const factor = target > trafficCeiling ? 1 : 0.5;
        trafficCeiling += (target - trafficCeiling) * factor;
    }

    if (chart) chart.options.scales.y.max = trafficCeiling;

}


// Every poll contributes a sample, including failed/disconnected ones, so the
// trace never freezes or vanishes. Only the plotted value is floored; the real
// rate lives in the parallel arrays for tooltips.
function pushTrafficSample(download, upload) {

    const now = new Date().toLocaleTimeString();

    lastTrafficDownload = download;
    lastTrafficUpload = upload;
    lastTrafficSampleAt = Date.now();
    labels.push(now);
    realDownloads.push(download);
    realUploads.push(upload);
    downloads.push(visibleTraffic(download));
    uploads.push(visibleTraffic(upload));

    if (labels.length > TRAFFIC_HISTORY_LENGTH) {

        labels.shift();
        realDownloads.shift();
        realUploads.shift();
        downloads.shift();
        uploads.shift();

    }

    updateTrafficCeiling(download, upload);

    if (chart) chart.update();

}


function chartTheme() {
    const light = document.documentElement.getAttribute("data-theme") === "light";
    return light ? {
        download: "#2f6fd6",
        upload: "#1f9d68",
        legend: "#4f6385",
        tick: "#6b7f9e",
        grid: "rgba(47, 79, 126, 0.12)",
        tooltipBg: "rgba(255, 255, 255, 0.98)",
        tooltipBorder: "rgba(47, 79, 126, 0.18)",
        tooltipTitle: "#17233b",
        tooltipBody: "#4f6385",
        pointBorder: "#ffffff"
    } : {
        download: "#62a7ff",
        upload: "#39d6a0",
        legend: "#aab7ce",
        tick: "#71819e",
        grid: "rgba(34, 49, 77, 0.55)",
        tooltipBg: "rgba(8, 13, 25, 0.94)",
        tooltipBorder: "rgba(126, 164, 228, 0.22)",
        tooltipTitle: "#eaf1ff",
        tooltipBody: "#aab7ce",
        pointBorder: "#0b1020"
    };
}

function areaFill(context, color) {
    const base = color || "#62a7ff";
    return `${base}26`;
}

function applyChartTheme() {
    if (!chart) return;
    const t = chartTheme();
    if (chart.data && chart.data.datasets && chart.data.datasets[0]) {
        chart.data.datasets[0].borderColor = t.download;
        chart.data.datasets[0].backgroundColor = (context) => areaFill(context, t.download);
        chart.data.datasets[0].pointHoverBackgroundColor = t.download;
        chart.data.datasets[0].pointHoverBorderColor = t.pointBorder;
    }
    if (chart.data && chart.data.datasets && chart.data.datasets[1]) {
        chart.data.datasets[1].borderColor = t.upload;
        chart.data.datasets[1].backgroundColor = (context) => areaFill(context, t.upload);
        chart.data.datasets[1].pointHoverBackgroundColor = t.upload;
        chart.data.datasets[1].pointHoverBorderColor = t.pointBorder;
    }
    if (chart.options && chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
        chart.options.plugins.legend.labels.color = t.legend;
    }
    if (chart.options && chart.options.plugins && chart.options.plugins.tooltip) {
        chart.options.plugins.tooltip.backgroundColor = t.tooltipBg;
        chart.options.plugins.tooltip.borderColor = t.tooltipBorder;
        chart.options.plugins.tooltip.titleColor = t.tooltipTitle;
        chart.options.plugins.tooltip.bodyColor = t.tooltipBody;
    }
    if (chart.options && chart.options.scales) {
        if (chart.options.scales.x && chart.options.scales.x.ticks) chart.options.scales.x.ticks.color = t.tick;
        if (chart.options.scales.y && chart.options.scales.y.ticks) chart.options.scales.y.ticks.color = t.tick;
        if (chart.options.scales.y && chart.options.scales.y.grid) chart.options.scales.y.grid.color = t.grid;
    }
}

window.NetScope = window.NetScope || {};
window.NetScope.refreshChartTheme = function () {
    applyChartTheme();
    if (chart) chart.update("none");
};


// Draws a soft halo and a bright leading dot on the newest sample of each
// series, like the glowing tip of a monitor trace. Chart.js keeps the actual
// line/point rendering (pointRadius stays 0); this only adds the live tip.
const livePointPlugin = {
    id: "livePoint",
    afterDatasetsDraw(instance) {
        const context = instance.ctx;
        const theme = chartTheme();

        instance.data.datasets.forEach((dataset, index) => {
            const meta = instance.getDatasetMeta(index);
            if (meta.hidden) return;

            const points = meta.data;
            const tip = points[points.length - 1];
            if (!tip || !Number.isFinite(tip.x) || !Number.isFinite(tip.y)) return;

            const color = index === 0 ? theme.download : theme.upload;

            context.save();

            context.beginPath();
            context.arc(tip.x, tip.y, 6, 0, Math.PI * 2);
            context.fillStyle = color;
            context.globalAlpha = 0.16;
            context.fill();

            context.beginPath();
            context.arc(tip.x, tip.y, 2.6, 0, Math.PI * 2);
            context.globalAlpha = 1;
            context.shadowColor = color;
            context.shadowBlur = 10;
            context.fillStyle = color;
            context.fill();

            context.restore();
        });
    }
};



// =====================================
// TRAFFIC CHART
// =====================================

let chart = null;
try { chart = new Chart(
    $("traffic-chart"),
    {
        type: "line",

        plugins: [livePointPlugin],

        data: {
            labels: labels,

            datasets: [

                {
                    label: "Download",

                    data: downloads,

                    borderColor: chartTheme().download,

                    backgroundColor: context =>
                        areaFill(context, chartTheme().download),

                    fill: true,

                    tension: 0.4,

                    cubicInterpolationMode: "monotone",

                    pointRadius: 0,

                    pointHoverRadius: 4,

                    pointHoverBackgroundColor: chartTheme().download,

                    pointHoverBorderColor: chartTheme().pointBorder,

                    pointHoverBorderWidth: 2,

                    borderWidth: 2,

                    borderCapStyle: "round",

                    borderJoinStyle: "round"
                },

                {
                    label: "Upload",

                    data: uploads,

                    borderColor: chartTheme().upload,

                    backgroundColor: context =>
                        areaFill(context, chartTheme().upload),

                    fill: true,

                    tension: 0.4,

                    cubicInterpolationMode: "monotone",

                    pointRadius: 0,

                    pointHoverRadius: 4,

                    pointHoverBackgroundColor: chartTheme().upload,

                    pointHoverBorderColor: chartTheme().pointBorder,

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
                duration: REDUCED_MOTION ? 0 : STATUS_POLL_INTERVAL_MS,
                easing: "linear"
            },

            transitions: {
                active: {
                    animation: {
                        duration: 400
                    }
                },
                resize: {
                    animation: {
                        duration: 400
                    }
                }
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

                    // Keep at least one series visible: hiding both made the
                    // whole plot look like it had vanished.
                    onClick: (_event, item, legend) => {
                        const instance = legend.chart;
                        const meta = instance.getDatasetMeta(item.datasetIndex);
                        const visible = instance.data.datasets.filter(
                            (_dataset, index) =>
                                !instance.getDatasetMeta(index).hidden
                        ).length;
                        if (!meta.hidden && visible <= 1) return;
                        meta.hidden = !meta.hidden;
                        instance.update();
                    },

                    labels: {
                        color: chartTheme().legend,
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

                    backgroundColor: chartTheme().tooltipBg,

                    borderColor: chartTheme().tooltipBorder,
                    borderWidth: 1,

                    cornerRadius: 10,
                    padding: 11,

                    titleColor: chartTheme().tooltipTitle,
                    bodyColor: chartTheme().tooltipBody,

                    displayColors: true,
                    usePointStyle: true,
                    boxPadding: 4,

                    callbacks: {

                        label: context => {
                            const values = context.datasetIndex === 0
                                ? realDownloads
                                : realUploads;
                            return `${context.dataset.label}: ` +
                                `${formatSpeed(values[context.dataIndex])} Mbps`;
                        }

                    }

                }

            },

            scales: {

                x: {

                    border: {
                        display: false
                    },

                    ticks: {
                        color: chartTheme().tick,
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

                    // Keep some headroom when traffic is zero so the idle line
                    // is not glued to the bottom edge of the chart. pushTrafficSample()
                    // replaces max with a rate-driven ceiling after each poll.
                    suggestedMax: TRAFFIC_MIN_CEILING_MBPS,

                    max: TRAFFIC_MIN_CEILING_MBPS,

                    grace: "10%",

                    border: {
                        display: false
                    },

                    ticks: {

                        color: chartTheme().tick,
                        padding: 8,

                        font: {
                            size: 10
                        },

                        callback: value =>
                            `${formatSpeed(value)} Mbps`
                    },

                    grid: {
                        color: chartTheme().grid,
                        drawTicks: false
                    }

                }

            }

        }

    }
); } catch (e) { console.error('chart init failed', e); chart = null; }

if (chart) applyChartTheme();


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

    if (document.visibilityState === "hidden") {
        return;
    }

    // Never let a slow request overlap the next poll: two concurrent updates
    // would push duplicate samples and cancel each other's chart animations.
    if (statusInFlight) {
        return;
    }

    statusInFlight = true;
    let statusTimeout = null;

    // Everything that can throw lives inside the try so the guard and timer
    // are always released in finally; an early throw used to freeze the chart
    // for the rest of the session.
    try {

        // Bound the request so a stalled localhost fetch cannot hold the guard
        // forever and freeze the trace after a long uptime. Keep the timeout
        // shorter than the poll interval so an abort and the next poll cannot
        // collide into a ten-second animation gap.
        const controller =
            typeof AbortController === "function" ? new AbortController() : null;

        statusTimeout = controller
            ? window.setTimeout(
                () => controller.abort(),
                STATUS_ABORT_TIMEOUT_MS
            )
            : null;

        const options = controller ? { signal: controller.signal } : undefined;

        const response = await fetch("/api/status", options);

        if (response.status === 401) {
            $("internet-status").textContent = "Session expired";
            $("gateway-status").textContent = "Session expired";
            const topStatus = $("top-status");
            if (topStatus) topStatus.dataset.live = "false";
            console.error("NetScope session expired; reopen via 'netscope gui'.");
            // A plain return here used to skip the sample and leave the trace
            // frozen forever once the session token changed.
            pushTrafficSample(0, 0);
            return;
        }

        if (!response.ok) {
            throw new Error("API request failed");
        }

        const data = await response.json() || {};

        const freshness = data.data_freshness || {};
        const freshnessBadge = $("data-freshness");

        if (freshnessBadge) {

            if (freshness.state === "fresh") {
                freshnessBadge.hidden = true;
                freshnessBadge.classList.remove("is-stale");
            } else {
                freshnessBadge.hidden = false;
                freshnessBadge.classList.add("is-stale");
                if (freshness.state === "stale") {
                    freshnessBadge.textContent = "Showing saved data · Gathering fresh data…";
                } else if (freshness.state === "unavailable") {
                    freshnessBadge.textContent = "Data unavailable";
                } else {
                    freshnessBadge.textContent = "Gathering data…";
                }
            }

        }

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

        // Ease upward slowly but fall quickly: after a disconnection a slow
        // decay keeps the y ceiling high and the idle line invisible for too
        // long.
        smoothedDownload =
            smoothedDownload === null
                ? nextDownload
                : smoothedDownload +
                  (nextDownload - smoothedDownload) *
                  (nextDownload < smoothedDownload
                      ? TRAFFIC_DROP_FACTOR
                      : SMOOTHING_FACTOR);

        smoothedUpload =
            smoothedUpload === null
                ? nextUpload
                : smoothedUpload +
                  (nextUpload - smoothedUpload) *
                  (nextUpload < smoothedUpload
                      ? TRAFFIC_DROP_FACTOR
                      : SMOOTHING_FACTOR);

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
                const dot = document.createElement("span");
                dot.className = "adapter-dot " + (adapter.is_up ? "up" : "down");
                const body = document.createElement("div");
                body.className = "adapter-body";
                const strong = document.createElement("strong");
                strong.textContent = String(adapter.name || "Adapter");
                const span = document.createElement("span");
                const speed = adapter.speed_mbps ? " \u00b7 " + adapter.speed_mbps + " Mbps" : "";
                span.textContent = String(adapter.ipv4 || "No IPv4 address") + speed;
                body.appendChild(strong);
                body.appendChild(span);
                const state = document.createElement("span");
                state.className = "adapter-state " + (adapter.is_up ? "up" : "down");
                state.textContent = adapter.is_up ? "Up" : "Down";
                item.appendChild(dot);
                item.appendChild(body);
                item.appendChild(state);
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

        const topStatus = $("top-status");

        if (topStatus) {

            topStatus.dataset.live = "true";

        }

        $("footer-time").textContent =
            `Last refresh ${now}`;


        // UPDATE CHART

        pushTrafficSample(smoothedDownload, smoothedUpload);

    }

    catch (error) {

        $("internet-status").textContent = "API error";

        setStatus("internet-dot", false);

        $("gateway-status").textContent = "API error";

        setStatus("gateway-dot", false);

        const topStatus = $("top-status");

        if (topStatus) {

            topStatus.dataset.live = "false";

        }

        // Keep the trace alive through a failed/disconnected poll: a flat
        // sample is far better than a line that stops or vanishes.
        pushTrafficSample(0, 0);

        console.error(error);

    }

    finally {

        if (statusTimeout !== null) window.clearTimeout(statusTimeout);

        statusInFlight = false;

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

let devicesLoading = false;


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


function setRefreshDevicesBusy(busy) {

    const refreshButton = $("refresh-devices");

    if (!refreshButton) {
        return;
    }

    refreshButton.disabled = busy;

    const label = refreshButton.querySelector(".btn-label");

    if (label) {
        label.textContent = busy ? "Scanning..." : "Refresh devices";
    }

}


function renderDeviceMessage(message) {

    const body = $("device-rows");
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "empty";
    td.textContent = message;
    tr.appendChild(td);
    body.replaceChildren(tr);

}


async function refreshDevices({ retry = true, silent = false, force = false } = {}) {

    const body = $("device-rows");

    let missingNames = false;

    devicesLoading = true;

    setRefreshDevicesBusy(true);

    if (!silent) {
        renderDeviceMessage("Scanning local network and resolving names...");
    }

    try {

        const response = await fetch(force ? "/api/devices?force=1" : "/api/devices");

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
            cancelPendingSectionAlign();
            setRefreshDevicesBusy(false);
            return;
        }


        const data = await response.json() || {};
        if (response.status === 202 && data.state === "pending") {
            renderDeviceMessage("Scanning local network and resolving names...");
            updateDeviceCount(null);
            applyDeviceScrollHeight();
            alignPendingSection();
            setRefreshDevicesBusy(false);
            scheduleDeviceNameRetry();
            return;
        }
        if (!response.ok) {
            throw new Error(
                (data.error && data.error.message) ||
                "Could not retrieve device list."
            );
        }
        if (!Array.isArray(data.devices)) {
            throw new Error("Device list response was invalid.");
        }
        const devices = data.devices;

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

        alignPendingSection();

        setRefreshDevicesBusy(false);

        if (retry && missingNames) {
            scheduleDeviceNameRetry();
        }

    }

    catch (error) {
        renderDeviceMessage(
            error instanceof Error && error.message
                ? error.message
                : "Could not retrieve device list."
        );

        updateDeviceCount(null);
        applyDeviceScrollHeight();
        alignPendingSection();
        setRefreshDevicesBusy(false);
        console.error(error);
    }

    finally {
        devicesLoading = false;
    }

}


// =====================================
// EVENT LISTENERS
// =====================================

const refreshDevicesEl = $("refresh-devices");
if (refreshDevicesEl) refreshDevicesEl.addEventListener(
    "click",
    () => refreshDevices({ force: true })
);


window.addEventListener(
    "resize",
    applyDeviceScrollHeight
);


// Background tabs throttle timers; redraw and refresh as soon as the dashboard
// is visible again so the live tip does not look frozen after a long idle.
document.addEventListener("visibilitychange", () => {

    if (document.visibilityState !== "visible") {
        return;
    }

    if (chart) {
        chart.resize();
        chart.update("none");
    }

    refreshStatus();
    refreshPacketLoss();

});



$("device-rows").addEventListener(
    "dblclick",
    async (event) => {

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

        const name = window.NetScope && window.NetScope.promptDialog
            ? await window.NetScope.promptDialog({
                title: "Rename device",
                eyebrow: "DEVICE",
                label: "Device name",
                message: "Set a friendly name for this device (saved in this browser).",
                value: current,
                placeholder: "Device name",
                confirmLabel: "Save",
                cancelLabel: "Cancel"
            })
            : null;

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

let uiSettled = false;

function settleUi() {

    if (uiSettled) {
        return;
    }

    uiSettled = true;

    document.body.classList.add('ui-settled');

}

let pendingSectionAlign = null;

function cancelPendingSectionAlign() {

    pendingSectionAlign = null;

}

function alignPendingSection() {

    const section = pendingSectionAlign;

    pendingSectionAlign = null;

    if (!section) {
        return;
    }

    const target = document.getElementById(section);
    const item = document.querySelector(
        `.nav-item[data-view="main"][data-scroll="${section}"]`
    );

    if (!target || !item || !item.classList.contains("active")) {
        return;
    }

    target.scrollIntoView({ behavior: "instant", block: "start" });

}

["wheel", "touchstart", "pointerdown", "keydown"].forEach(eventName => {

    window.addEventListener(
        eventName,
        cancelPendingSectionAlign,
        { passive: true }
    );

});

function showView(viewName, options = {}) {

    const { updateHash = true, scrollToId = null } = options;

    const mainSection = viewName === 'main'
        ? (scrollToId === 'devices' || scrollToId === 'traffic'
            ? scrollToId
            : 'overview-top')
        : null;

    pendingSectionAlign = (
        viewName === 'main' &&
        mainSection === 'devices' &&
        devicesLoading
    )
        ? 'devices'
        : null;

    document.querySelectorAll('.page-view[data-view]').forEach(page => {
        page.classList.toggle('active', page.dataset.view === viewName);
    });

    document.querySelectorAll('.nav-item[data-view]').forEach(item => {
        const itemSection = item.dataset.scroll || 'overview-top';
        const active = item.dataset.view === viewName &&
            (viewName !== 'main' || itemSection === mainSection);
        item.classList.toggle('active', active);
        if (active) {
            item.setAttribute('aria-current', 'page');
        }
        else {
            item.removeAttribute('aria-current');
        }
    });

    if (updateHash) {
        const hash = viewName === 'troubleshoot'
            ? '#troubleshoot'
            : viewName === 'repairs'
                ? '#repairs'
                : mainSection === 'devices'
                    ? '#devices'
                    : mainSection === 'traffic'
                        ? '#traffic'
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
        window.requestAnimationFrame(() => {
            if (mainSection !== 'overview-top') {
                const target = document.getElementById(mainSection);
                if (target) {
                    target.scrollIntoView({ behavior: 'instant', block: 'start' });
                    return;
                }
            }
            window.scrollTo({ top: 0, behavior: 'instant' });
        });
    }
    else {
        window.scrollTo({ top: 0, behavior: 'instant' });
    }

}

document.querySelectorAll('.nav-item[data-view]').forEach(item => {

    item.addEventListener('click', event => {
        event.preventDefault();
        const view = item.dataset.view;
        const scrollToId = item.dataset.scroll || null;
        settleUi();
        showView(view, { scrollToId });
    });

});


// =====================================
// PACKET LOSS MONITORING
// =====================================

let packetLossInFlight = false;

async function refreshPacketLoss() {

    if (document.visibilityState === "hidden") {
        return;
    }

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
        const data = await response.json();
        if (response.status === 202 && data.state === "pending") {
            value.textContent = "\u2014";
            detail.textContent = "Packet loss test is still running...";
            return;
        }
        if (!response.ok) {
            throw new Error(
                (data.error && data.error.message) ||
                "Packet loss request failed"
            );
        }
        if (!data.internet || !data.gateway) {
            throw new Error("Packet-loss response was invalid.");
        }
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
        value.textContent = "\u2014";
        detail.textContent =
            error instanceof Error && error.message
                ? error.message
                : "Could not measure packet loss.";
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

window.setTimeout(settleUi, 900);

refreshStatus();

refreshDevices();

refreshPacketLoss();




// SAMPLE TRAFFIC OFTEN ENOUGH FOR A CONTINUOUS, HEARTBEAT-LIKE TRACE

setInterval(refreshStatus, STATUS_POLL_INTERVAL_MS);
setInterval(refreshPacketLoss, 60000);

// Keep the chart moving when a status poll is skipped, a stall timeout loses
// a cycle, or a request remains in flight beyond one interval. This repeats the
// last known real rate so the UI does not appear frozen while recovery occurs.
setInterval(() => {
    if (document.visibilityState === "hidden") {
        return;
    }
    if (Date.now() - lastTrafficSampleAt >= STATUS_POLL_INTERVAL_MS - 500) {
        pushTrafficSample(lastTrafficDownload, lastTrafficUpload);
    }
}, STATUS_POLL_INTERVAL_MS);

