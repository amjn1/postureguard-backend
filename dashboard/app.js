/**
 * app.js — PostureGuard Dashboard
 *
 * Plain ES2020 JavaScript — no build step, no framework.
 * Runs directly in the browser after index.html loads it.
 *
 * Architecture:
 *   • API key is stored in localStorage after the user enters it once.
 *   • Every API call sends "X-API-Key" in the request header.
 *   • Three polling intervals keep the page live:
 *       – Every  3 s: live tile (GET /api/session/current)
 *       – Every 30 s: desk station (GET /api/desk/current)
 *       – Every 60 s: session chart + daily summary
 *       – Every  5 min: 7-day history bar chart
 *
 * Security note:
 *   The API key is stored in localStorage and sent in a request header.
 *   Anyone who opens DevTools on this page can read it. For a single-user
 *   college project this is an acceptable trade-off — the key still prevents
 *   anonymous Internet traffic from writing to the database.
 */

"use strict";

// ─── State ────────────────────────────────────────────────────────────────────

let API_KEY = localStorage.getItem("postureguard_api_key") || "";
let sessionChart = null;
let historyChart = null;

// ─── API key management ───────────────────────────────────────────────────────

function showKeyOverlay() {
  document.getElementById("key-overlay").classList.remove("hidden");
}

function hideKeyOverlay() {
  document.getElementById("key-overlay").classList.add("hidden");
}

function saveKey() {
  const input = document.getElementById("key-input");
  const key = input.value.trim();
  if (!key) {
    input.focus();
    return;
  }
  localStorage.setItem("postureguard_api_key", key);
  API_KEY = key;
  hideKeyOverlay();
  startPolling();
}

function changeKey() {
  document.getElementById("key-input").value = "";
  showKeyOverlay();
}

// Allow Enter key to submit the key form
document.getElementById("key-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") saveKey();
});

// ─── Fetch helper ─────────────────────────────────────────────────────────────

/**
 * Fetch a JSON endpoint with the API key header.
 * Returns null on 401 (bad key — shows overlay again) or any other error.
 */
async function apiFetch(path) {
  try {
    const resp = await fetch(path, {
      headers: { "X-API-Key": API_KEY },
    });

    if (resp.status === 401) {
      // Key is wrong — prompt the user to re-enter it.
      localStorage.removeItem("postureguard_api_key");
      API_KEY = "";
      showKeyOverlay();
      return null;
    }

    if (!resp.ok) {
      console.warn(`API error ${resp.status} for ${path}`);
      return null;
    }

    return resp.json();
  } catch (err) {
    console.warn(`Network error for ${path}:`, err);
    return null;
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Format minutes as "Xh Ym" or "Ym" */
function fmtMinutes(min) {
  if (min == null) return "—";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/** Format a datetime string as HH:MM (local time) */
function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Return CSS class + label for a posture/activity state */
function stateStyle(postureState, activityState) {
  if (!postureState) return { cls: "badge-off", label: "Offline" };
  if (activityState === "WALKING")    return { cls: "badge-walk",  label: "🚶 Walking" };
  if (activityState === "TRANSITION") return { cls: "badge-trans", label: "↕ Transitioning" };
  if (postureState === "GOOD")        return { cls: "badge-good",  label: "✓ Good posture" };
  if (postureState === "SLOUCH")      return { cls: "badge-slouch", label: "⚠ Slouching" };
  return { cls: "badge-off", label: postureState };
}

/** Pick the live-tile border colour class */
function tileClass(postureState, activityState) {
  if (!postureState)                  return "";
  if (activityState === "WALKING" || activityState === "TRANSITION") return "walk";
  if (postureState === "GOOD")   return "good";
  if (postureState === "SLOUCH") return "slouch";
  return "";
}

/** Colour a % good posture number */
function pctClass(pct) {
  if (pct == null)  return "metric-muted";
  if (pct >= 75)    return "metric-good";
  if (pct >= 50)    return "metric-warn";
  return "metric-slouch";
}

// ─── Live tile update ─────────────────────────────────────────────────────────

async function fetchLive() {
  const data = await apiFetch("/api/session/current");
  const dot  = document.getElementById("conn-dot");

  if (!data || !data.posture_state) {
    // Device offline
    dot.className = "dot offline";
    document.getElementById("phi-val").textContent = "—";
    document.getElementById("state-badge").className = "state-badge badge-off";
    document.getElementById("state-badge").textContent = "Offline";
    document.getElementById("alert-dot").style.display = "none";
    document.getElementById("activity-meta").textContent = "Device not connected";
    document.getElementById("session-meta").textContent  = "";
    document.getElementById("baseline-meta").textContent = "";
    const card = document.getElementById("live-card");
    card.className = "card live-tile";
    return;
  }

  dot.className = "dot online";

  // φ value
  document.getElementById("phi-val").textContent = data.phi.toFixed(1);

  // State badge
  const { cls, label } = stateStyle(data.posture_state, data.activity_state);
  const badge = document.getElementById("state-badge");
  badge.className = `state-badge ${cls}`;
  badge.textContent = label;

  // Alert flash dot
  document.getElementById("alert-dot").style.display =
    data.alert_fired ? "inline-block" : "none";

  // Live-tile border colour
  const card = document.getElementById("live-card");
  card.className = `card live-tile ${tileClass(data.posture_state, data.activity_state)}`;

  // Meta row
  document.getElementById("activity-meta").textContent = data.activity_state || "—";
  document.getElementById("session-meta").textContent =
    data.session_start
      ? `Session: since ${fmtTime(data.session_start)} (${fmtMinutes(data.session_duration_min)})`
      : "No active session";
  document.getElementById("baseline-meta").textContent =
    data.phi_baseline != null ? `Baseline: ${data.phi_baseline.toFixed(1)}°` : "";
}

// ─── Session chart ────────────────────────────────────────────────────────────

async function fetchSessionChart() {
  const data = await apiFetch("/api/session/current/chart");
  if (!data) return;

  const ctx = document.getElementById("session-chart").getContext("2d");

  // Build datasets
  const phiData       = data.points.map(p => ({ x: new Date(p.timestamp), y: p.phi }));
  const baselineData  = data.points.map(p => ({ x: new Date(p.timestamp), y: data.phi_baseline }));
  const threshData    = data.points.map(p => ({ x: new Date(p.timestamp), y: data.alert_threshold }));

  if (sessionChart) {
    // Update existing chart (avoids full re-render flicker)
    sessionChart.data.datasets[0].data = phiData;
    sessionChart.data.datasets[1].data = baselineData;
    sessionChart.data.datasets[2].data = threshData;
    sessionChart.update("none"); // no animation on update
    return;
  }

  sessionChart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
        {
          label: "φ (flexion)",
          data: phiData,
          borderColor: "#3b82f6",
          backgroundColor: "rgba(59,130,246,.08)",
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: true,
          order: 0,
        },
        {
          label: "Baseline",
          data: baselineData,
          borderColor: "#22c55e",
          borderWidth: 1.5,
          borderDash: [6, 4],
          pointRadius: 0,
          fill: false,
          order: 1,
        },
        {
          label: "Alert threshold",
          data: threshData,
          borderColor: "#f59e0b",
          borderWidth: 1.5,
          borderDash: [6, 4],
          pointRadius: 0,
          fill: false,
          order: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}°`,
          },
        },
      },
      scales: {
        x: {
          type: "time",
          time: {
            displayFormats: { minute: "HH:mm", hour: "HH:mm" },
            tooltipFormat: "HH:mm:ss",
          },
          grid: { color: "rgba(0,0,0,.04)" },
          ticks: { color: "#64748b", font: { size: 11 }, maxTicksLimit: 8 },
        },
        y: {
          title: { display: false },
          grid: { color: "rgba(0,0,0,.04)" },
          ticks: {
            color: "#64748b",
            font: { size: 11 },
            callback: (v) => `${v}°`,
          },
        },
      },
    },
  });
}

// ─── Daily summary ────────────────────────────────────────────────────────────

async function fetchDailySummary() {
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  const data  = await apiFetch(`/api/session/${today}`);
  if (!data) return;

  const pct  = data.pct_good_posture;
  const rate = data.slouch_events_per_hour;
  const sit  = data.total_sitting_minutes;

  const goodEl = document.getElementById("s-good");
  goodEl.textContent = pct != null ? `${pct.toFixed(0)}%` : "—";
  goodEl.className   = `metric-big ${pctClass(pct)}`;

  const rateEl = document.getElementById("s-rate");
  rateEl.textContent = rate != null ? rate.toFixed(1) : "—";
  rateEl.className   = `metric-big ${rate == null ? "metric-muted" : rate <= 3 ? "metric-good" : rate <= 6 ? "metric-warn" : "metric-slouch"}`;

  document.getElementById("s-sit").textContent  =
    sit != null ? `${fmtMinutes(sit)} sitting` : "No sitting data";
  document.getElementById("s-sess").textContent =
    `${data.session_count} session${data.session_count !== 1 ? "s" : ""}`;
}

// ─── 7-day history bar chart ──────────────────────────────────────────────────

async function fetchHistory() {
  const data = await apiFetch("/api/history?range=7d");
  if (!data || !data.history) return;

  const labels = data.history.map(d => {
    const dt = new Date(d.date + "T00:00:00");
    return dt.toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" });
  });
  const values = data.history.map(d => d.pct_good_posture);

  // Colour each bar based on the percentage
  const barColors = values.map(v => {
    if (v == null) return "rgba(203,213,225,.5)"; // no-data grey
    if (v >= 75)   return "rgba(34,197,94,.7)";    // green
    if (v >= 50)   return "rgba(245,158,11,.7)";   // amber
    return "rgba(239,68,68,.7)";                   // red
  });

  const ctx = document.getElementById("history-chart").getContext("2d");

  if (historyChart) {
    historyChart.data.labels              = labels;
    historyChart.data.datasets[0].data   = values;
    historyChart.data.datasets[0].backgroundColor = barColors;
    historyChart.update();
    return;
  }

  historyChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "% Good posture",
          data: values,
          backgroundColor: barColors,
          borderRadius: 6,
          borderSkipped: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) =>
              ctx.parsed.y != null ? `${ctx.parsed.y.toFixed(1)}% good posture` : "No data",
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#64748b", font: { size: 11 } },
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: "rgba(0,0,0,.04)" },
          ticks: {
            color: "#64748b",
            font: { size: 11 },
            callback: (v) => `${v}%`,
          },
        },
      },
    },
  });
}

// ─── Desk station ─────────────────────────────────────────────────────────────

async function fetchDesk() {
  const data = await apiFetch("/api/desk/current");
  const el   = document.getElementById("desk-content");

  if (!data || data.timestamp == null) {
    el.innerHTML = '<div class="offline-msg">No desk data received yet</div>';
    return;
  }

  // Determine flag labels
  const distFlag = data.flags.too_close
    ? '<span class="flag-bad">⚠ Too close</span>'
    : '<span class="flag-ok">✓ OK</span>';
  const luxFlag = data.flags.too_dark
    ? '<span class="flag-bad">⚠ Too dark</span>'
    : '<span class="flag-ok">✓ OK</span>';

  el.innerHTML = `
    <div class="desk-grid">
      <div class="desk-cell">
        <div class="desk-value ${data.flags.too_close ? "flag-bad" : ""}">
          ${data.screen_distance_cm != null ? data.screen_distance_cm.toFixed(0) + " cm" : "—"}
        </div>
        <div class="desk-label">Screen distance ${distFlag}</div>
      </div>
      <div class="desk-cell">
        <div class="desk-value ${data.flags.too_dark ? "flag-bad" : ""}">
          ${data.lux != null ? Math.round(data.lux) + " lx" : "—"}
        </div>
        <div class="desk-label">Illuminance ${luxFlag}</div>
      </div>
      <div class="desk-cell">
        <div class="desk-value">
          ${data.temperature_c != null ? data.temperature_c.toFixed(1) + "°C" : "—"}
        </div>
        <div class="desk-label">Temperature</div>
      </div>
      <div class="desk-cell">
        <div class="desk-value">
          ${data.humidity_pct != null ? Math.round(data.humidity_pct) + "%" : "—"}
        </div>
        <div class="desk-label">Humidity</div>
      </div>
    </div>
    <div style="margin-top:.75rem;font-size:.72rem;color:var(--muted)">
      Last updated: ${fmtTime(data.timestamp)}
    </div>
  `;
}

// ─── Polling orchestration ────────────────────────────────────────────────────

function startPolling() {
  // Immediate first fetch
  fetchLive();
  fetchSessionChart();
  fetchDailySummary();
  fetchDesk();
  fetchHistory();

  // Continuous polls
  setInterval(fetchLive,         3_000);   // live tile: every 3 s
  setInterval(fetchDesk,        30_000);   // desk:      every 30 s
  setInterval(() => {
    fetchSessionChart();
    fetchDailySummary();
  },                            60_000);   // chart + summary: every 60 s
  setInterval(fetchHistory,    300_000);   // history bar: every 5 min
}

// ─── Initialise ───────────────────────────────────────────────────────────────

if (API_KEY) {
  // Key already in localStorage → go straight to the dashboard
  hideKeyOverlay();
  startPolling();
} else {
  // No key stored → show setup overlay (user must enter key before data loads)
  showKeyOverlay();
}
