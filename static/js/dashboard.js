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

let deviceNameRetryTimer = null;


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


// UPDATE EVERY 2 SECONDS

setInterval(refreshStatus, 2000);