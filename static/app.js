// ==========================================================================
// LAB ACCESS — dashboard frontend
//
// Polls the Flask backend once a second for /api/status and /api/logs and
// re-renders the page. No WebSockets, no build step - simple polling is
// plenty fast for a hackathon demo.
// ==========================================================================

const POLL_MS = 1000;

const el = {
  arduinoDot: document.getElementById("arduinoDot"),
  arduinoText: document.getElementById("arduinoText"),

  capacityCurrent: document.getElementById("capacityCurrent"),
  capacityMax: document.getElementById("capacityMax"),
  occupancyPercent: document.getElementById("occupancyPercent"),
  progressFill: document.getElementById("progressFill"),

  cameraCard: document.getElementById("cameraCard"),
  cameraEyebrow: document.getElementById("cameraEyebrow"),
  cameraStatusText: document.getElementById("cameraStatusText"),
  cameraDesc: document.getElementById("cameraDesc"),

  tempValue: document.getElementById("tempValue"),
  tempDot: document.getElementById("tempDot"),
  tempStatusText: document.getElementById("tempStatusText"),
  tempMarker: document.getElementById("tempMarker"),

  airValue: document.getElementById("airValue"),
  airDot: document.getElementById("airDot"),
  airStatusText: document.getElementById("airStatusText"),
  airMarker: document.getElementById("airMarker"),

  activityList: document.getElementById("activityList"),

  demoCheckin: document.getElementById("demoCheckin"),
  demoCheckout: document.getElementById("demoCheckout"),
};

// Must mirror the safe-range constants in app.py (TEMPERATURE_SAFE_MAX_C,
// AIR_QUALITY_SAFE_MAX_PPM) and the gauge domains used for the zone widths
// hardcoded in index.html.
const TEMP_DOMAIN_MIN = 15;
const TEMP_DOMAIN_MAX = 45;
const AIR_DOMAIN_MIN = 0;
const AIR_DOMAIN_MAX = 150;

function updateSensorGauge({ dotEl, textEl, markerEl, value, domainMin, domainMax, safe }) {
  dotEl.classList.remove("dot-good", "dot-bad");
  dotEl.classList.add(safe ? "dot-good" : "dot-bad");
  textEl.textContent = safe ? "SAFE" : "NOT SAFE";

  const fraction = Math.min(1, Math.max(0, (value - domainMin) / (domainMax - domainMin)));
  markerEl.style.left = `${fraction * 100}%`;
}

function updateStatus(data) {
  // Arduino connection pill
  if (data.arduinoConnected) {
    el.arduinoDot.classList.remove("dot-bad");
    el.arduinoDot.classList.add("dot-good");
    el.arduinoText.textContent = "ARDUINO CONNECTED";
  } else {
    el.arduinoDot.classList.remove("dot-good");
    el.arduinoDot.classList.add("dot-bad");
    el.arduinoText.textContent = "ARDUINO DISCONNECTED";
  }

  // Occupancy card
  const pct = data.maxCapacity > 0
    ? Math.round((data.capacity / data.maxCapacity) * 100)
    : 0;

  el.capacityCurrent.textContent = data.capacity;
  el.capacityMax.textContent = data.maxCapacity;
  el.occupancyPercent.textContent = `${pct}% OCCUPIED`;
  el.progressFill.style.width = `${Math.min(100, pct)}%`;
  el.progressFill.classList.toggle("full", pct >= 90);

  // Privacy / camera card - camera tracks occupancy, not a timed blip:
  // on while the lab has anyone checked in, off the moment it's empty.
  el.cameraEyebrow.textContent = "PRIVACY MODE";
  if (data.cameraActive) {
    el.cameraCard.classList.add("active");
    el.cameraStatusText.textContent = "CAMERA ACTIVE";
    el.cameraDesc.textContent =
      "The lab is currently occupied, so video monitoring is active.";
  } else {
    el.cameraCard.classList.remove("active");
    el.cameraStatusText.textContent = "CAMERA INACTIVE";
    el.cameraDesc.textContent =
      "Video monitoring stays off while the lab is empty.";
  }

  // Environmental sensors (simulated)
  el.tempValue.textContent = data.temperatureC.toFixed(1);
  updateSensorGauge({
    dotEl: el.tempDot,
    textEl: el.tempStatusText,
    markerEl: el.tempMarker,
    value: data.temperatureC,
    domainMin: TEMP_DOMAIN_MIN,
    domainMax: TEMP_DOMAIN_MAX,
    safe: data.temperatureSafe,
  });

  el.airValue.textContent = Math.round(data.airQualityPpm);
  updateSensorGauge({
    dotEl: el.airDot,
    textEl: el.airStatusText,
    markerEl: el.airMarker,
    value: data.airQualityPpm,
    domainMin: AIR_DOMAIN_MIN,
    domainMax: AIR_DOMAIN_MAX,
    safe: data.airQualitySafe,
  });
}

function formatDurationShort(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

function renderActivityRow(entry) {
  const isCheckin = entry.action === "CHECK_IN";
  const row = document.createElement("div");
  row.className = `activity-row ${isCheckin ? "checkin" : "checkout"}`;

  const statsHtml = isCheckin
    ? `
      <div class="stat">
        <div class="stat-label">CAPACITY</div>
        <div class="stat-value">${entry.capacity} / ${document.getElementById("capacityMax").textContent}</div>
      </div>
    `
    : `
      <div class="stat">
        <div class="stat-label">SESSION DURATION</div>
        <div class="stat-value">${formatDurationShort(entry.duration_seconds || 0)}</div>
      </div>
      <div class="stat">
        <div class="stat-label">CAPACITY</div>
        <div class="stat-value">${entry.capacity} / ${document.getElementById("capacityMax").textContent}</div>
      </div>
    `;

  row.innerHTML = `
    <div class="activity-time">${entry.timestamp}</div>
    <div class="activity-main">
      <div class="activity-title">STUDENT ${entry.student_id} — ${isCheckin ? "CHECKED IN" : "LAB COMPLETED"}</div>
      <p class="activity-message">${entry.message}</p>
    </div>
    <div class="activity-stats">${statsHtml}</div>
  `;

  return row;
}

function updateLogs(logs) {
  if (!logs.length) {
    el.activityList.innerHTML =
      '<div class="empty-state">No activity yet. Waiting for a student to check in…</div>';
    return;
  }

  el.activityList.innerHTML = "";
  for (const entry of logs) {
    el.activityList.appendChild(renderActivityRow(entry));
  }
}

async function pollStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    updateStatus(await res.json());
  } catch (err) {
    // Backend unreachable - leave the last known UI in place instead of crashing.
    console.error("status poll failed", err);
  }
}

async function pollLogs() {
  try {
    const res = await fetch("/api/logs");
    if (!res.ok) return;
    updateLogs(await res.json());
  } catch (err) {
    console.error("logs poll failed", err);
  }
}

el.demoCheckin.addEventListener("click", () => {
  fetch("/api/demo/checkin", { method: "POST" }).catch((e) => console.error(e));
});

el.demoCheckout.addEventListener("click", () => {
  fetch("/api/demo/checkout", { method: "POST" }).catch((e) => console.error(e));
});

pollStatus();
pollLogs();
setInterval(pollStatus, POLL_MS);
setInterval(pollLogs, POLL_MS);
