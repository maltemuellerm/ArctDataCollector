/* verification.js – AROME Arctic NWP verification page
 *
 * Loads /data/arome/verification.json (precomputed by compute_arome_verification.py)
 * and renders:
 *   1. Grouped bar chart: RMSE, MAE, |BIAS| per lead-time bucket
 *   2. Bias line overlay (signed)
 *   3. Summary table
 *   4. Scatter plot: obs vs model coloured by lead-time group
 */

"use strict";

const IS_LOCAL_VRF = location.hostname === "localhost"
                  || location.hostname === "127.0.0.1"
                  || location.protocol === "file:";
const AROME_BASE = IS_LOCAL_VRF
  ? "data/arome"
  : "http://148.230.70.161/data/arome";

// ── Palette for lead-time groups (up to 12 groups for 6 h scheme) ─────────────
const GROUP_COLORS = [
  "#1a6e3c","#2dab6f","#7dcba4","#aee0c8",
  "#2e5fa3","#4a8fcb","#7db9e0","#b3d4ef",
  "#8b3a8b","#c06fcb","#e0aaee","#f3d0f8",
];

// ── Source display names ───────────────────────────────────────────────────────
const SOURCE_LABELS = {
  ships:      "Ships",
  simba:      "SIMBA buoys",
  thermistor: "Thermistor buoys",
  arctsum:    "ArctSum buoys",
  svalmiz:    "SvalMIZ buoys",
  iabp:       "IABP buoys",
};

// ── State ──────────────────────────────────────────────────────────────────────
let _data   = null;   // parsed verification.json
let _source = null;
let _var    = null;
let _grp    = "12h";

// Map state
let _map         = null;
let _dotLayer    = null;
let _domainLayer = null;
let _mapMetric   = "bias";
let _mapLead     = "all";

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
  const statusEl = document.getElementById("vrf-status");
  try {
    const resp = await fetch(`${AROME_BASE}/verification.json`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    _data = await resp.json();
  } catch (err) {
    statusEl.textContent =
      "Verification data not yet available. "
      + "Run compute_arome_verification.py on the server to generate it. "
      + `(${err.message})`;
    return;
  }
  statusEl.style.display = "none";

  _populateSourceSel();
  _wireControls();
  _render();

  document.getElementById("vrf-controls").style.display = "";
  document.getElementById("about-card").style.display = "";
}

// ── UI population ──────────────────────────────────────────────────────────────
function _populateSourceSel() {
  const sel = document.getElementById("src-sel");
  sel.innerHTML = "";
  const sources = Object.keys(_data.stats || {});
  sources.forEach((src) => {
    const opt = document.createElement("option");
    opt.value = src;
    opt.textContent = SOURCE_LABELS[src] || src;
    sel.appendChild(opt);
  });
  _source = sources[0] || null;
}

function _populateVarSel() {
  const sel = document.getElementById("var-sel");
  sel.innerHTML = "";
  if (!_source || !_data.stats[_source]) return;
  const vars = Object.keys(_data.stats[_source]);
  vars.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    const meta = (_data.variables || {})[v] || {};
    opt.textContent = `${meta.label || v} (${meta.units || ""})`;
    sel.appendChild(opt);
  });
  _var = vars[0] || null;
}

function _wireControls() {
  document.getElementById("src-sel").addEventListener("change", (e) => {
    _source = e.target.value;
    _populateVarSel();
    _var = document.getElementById("var-sel").value || _var;
    _render();
  });
  document.getElementById("var-sel").addEventListener("change", (e) => {
    _var = e.target.value;
    _render();
  });
  document.getElementById("grp-btns").addEventListener("click", (e) => {
    const btn = e.target.closest(".vrf-grp-btn");
    if (!btn) return;
    document.querySelectorAll(".vrf-grp-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    _grp = btn.dataset.grp;
    _render();
  });
  document.getElementById("map-metric-sel").addEventListener("change", (e) => {
    _mapMetric = e.target.value;
    const scatter = (_data.scatter[_source] || {})[_var];
    const varMeta = (_data.variables || {})[_var] || {};
    _renderMap(scatter, varMeta);
  });
  document.getElementById("map-lead-sel").addEventListener("change", (e) => {
    _mapLead = e.target.value;
    const scatter = (_data.scatter[_source] || {})[_var];
    const varMeta = (_data.variables || {})[_var] || {};
    _renderMap(scatter, varMeta);
  });
  _populateVarSel();
}

// ── Main render ────────────────────────────────────────────────────────────────
function _render() {
  if (!_source || !_var) return;

  const statsForVar = ((_data.stats[_source] || {})[_var] || {})[_grp];
  const scatterForVar = (_data.scatter[_source] || {})[_var];
  const varMeta = (_data.variables || {})[_var] || {};
  const period = _data.period || {};

  // Summary meta line
  document.getElementById("vrf-meta").textContent =
    `Data period: ${period.start || "?"} → ${period.end || "?"}  •  `
    + `Generated: ${(_data.generated || "").slice(0, 16).replace("T", " ")} UTC`;

  if (!statsForVar) {
    _showNoData("metrics-card");
    _showNoData("table-card");
    _showNoData("scatter-card");
  } else {
    _renderMetricsChart(statsForVar, varMeta);
    _renderTable(statsForVar, varMeta);
    _renderScatter(scatterForVar, varMeta);
  }

  _updateMapLeadSel();
  _renderMap(scatterForVar, varMeta);
}

// ── Metrics bar + bias line chart ──────────────────────────────────────────────
function _renderMetricsChart(buckets, varMeta) {
  const card = document.getElementById("metrics-card");
  card.style.display = "";

  const labels = buckets.map((b) => b.label);
  const rmse   = buckets.map((b) => (b.rmse  != null ? +b.rmse.toFixed(3)  : null));
  const mae    = buckets.map((b) => (b.mae   != null ? +b.mae.toFixed(3)   : null));
  const bias   = buckets.map((b) => (b.bias  != null ? +b.bias.toFixed(3)  : null));
  const ns     = buckets.map((b) => b.n || 0);

  const unitLbl = varMeta.units ? ` (${varMeta.units})` : "";
  const customdata = ns;

  const traces = [
    {
      type: "scatter",
      mode: "lines+markers",
      name: "RMSE",
      x: labels, y: rmse,
      customdata,
      hovertemplate: "RMSE: %{y:.3f}<br>N: %{customdata}<extra></extra>",
      line: { color: "#2e5fa3", width: 2.5 },
      marker: { size: 7, symbol: "circle" },
      yaxis: "y",
    },
    {
      type: "scatter",
      mode: "lines+markers",
      name: "MAE",
      x: labels, y: mae,
      customdata,
      hovertemplate: "MAE: %{y:.3f}<br>N: %{customdata}<extra></extra>",
      line: { color: "#2dab6f", width: 2.5 },
      marker: { size: 7, symbol: "circle" },
      yaxis: "y",
    },
    {
      type: "scatter",
      mode: "lines+markers",
      name: "BIAS",
      x: labels, y: bias,
      customdata,
      hovertemplate: "BIAS: %{y:.3f}<br>N: %{customdata}<extra></extra>",
      line: { color: "#e05c2e", width: 2.5 },
      marker: { size: 7, symbol: "circle" },
      yaxis: "y2",
    },
  ];

  const layout = {
    xaxis: { title: "Lead time", tickfont: { size: 12 } },
    yaxis: {
      title: `Error${unitLbl}`,
      side: "left",
      autorange: true,
      showgrid: true, gridcolor: "#eee",
    },
    yaxis2: {
      title: `BIAS${unitLbl}`,
      side: "right",
      overlaying: "y",
      zeroline: true, zerolinecolor: "#ccc", zerolinewidth: 1.5,
      showgrid: false,
    },
    legend: { orientation: "h", y: -0.2, font: { size: 12 } },
    hovermode: "x unified",
    plot_bgcolor: "#f8fbfc",
    paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 70, b: 60, l: 65 },
    height: 380,
    shapes: [{
      type: "line", xref: "paper", x0: 0, x1: 1,
      yref: "y2", y0: 0, y1: 0,
      line: { color: "#e05c2e", width: 1, dash: "dot" },
    }],
  };

  Plotly.newPlot("metrics-plot", traces, layout,
    { responsive: true, displaylogo: false });
}

// ── Summary table ──────────────────────────────────────────────────────────────
function _renderTable(buckets, varMeta) {
  const card  = document.getElementById("table-card");
  const wrap  = document.getElementById("stats-table");
  card.style.display = "";

  const unitLbl = varMeta.units ? ` (${varMeta.units})` : "";

  let html = `<table class="vrf-table">
    <thead><tr>
      <th>Lead time</th>
      <th>N</th>
      <th>RMSE${unitLbl}</th>
      <th>MAE${unitLbl}</th>
      <th>BIAS${unitLbl}</th>
    </tr></thead><tbody>`;

  buckets.forEach((b) => {
    if (b.n < 2) {
      html += `<tr>
        <td>${b.label}</td>
        <td class="num">${b.n}</td>
        <td colspan="3" class="no-data">— insufficient data —</td>
      </tr>`;
      return;
    }
    const biasClass = b.bias > 0.01 ? "bias-pos" : b.bias < -0.01 ? "bias-neg" : "";
    html += `<tr>
      <td>${b.label}</td>
      <td class="num">${b.n}</td>
      <td class="num">${b.rmse.toFixed(3)}</td>
      <td class="num">${b.mae.toFixed(3)}</td>
      <td class="num ${biasClass}">${b.bias >= 0 ? "+" : ""}${b.bias.toFixed(3)}</td>
    </tr>`;
  });

  html += "</tbody></table>";
  wrap.innerHTML = html;
}

// ── Scatter plot ───────────────────────────────────────────────────────────────
function _renderScatter(scatter, varMeta) {
  const card = document.getElementById("scatter-card");
  if (!scatter || !scatter.obs || scatter.obs.length === 0) {
    card.style.display = "none";
    return;
  }
  card.style.display = "";

  const obs   = scatter.obs;
  const model = scatter.model;
  const leads = scatter.lead;
  const unitLbl = varMeta.units || "";

  // Assign each point to a lead group for colouring
  const buckets = (_data.groupings || {})[_grp] || [];

  // Build one trace per bucket
  const traceMap = new Map();
  buckets.forEach((b, idx) => {
    traceMap.set(b.label, {
      type: "scattergl",
      mode: "markers",
      name: b.label,
      x: [], y: [],
      marker: { color: GROUP_COLORS[idx % GROUP_COLORS.length], size: 5, opacity: 0.65 },
      hovertemplate:
        `Obs: %{x:.2f} ${unitLbl}<br>Model: %{y:.2f} ${unitLbl}<extra>${b.label}</extra>`,
      xaxis: "x", yaxis: "y",
    });
  });

  obs.forEach((o, k) => {
    const lead = leads[k];
    const bucket = buckets.find((b) => lead >= b.lo && lead < b.hi);
    if (!bucket) return;
    const tr = traceMap.get(bucket.label);
    if (tr) { tr.x.push(o); tr.y.push(model[k]); }
  });

  const allVals = [...obs, ...model].filter((v) => v != null);
  const vMin = Math.min(...allVals);
  const vMax = Math.max(...allVals);
  const pad  = (vMax - vMin) * 0.05;
  const axMin = vMin - pad;
  const axMax = vMax + pad;

  const traces = [...traceMap.values(), {
    type: "scatter",
    mode: "lines",
    name: "1:1",
    x: [axMin, axMax], y: [axMin, axMax],
    line: { color: "#888", width: 1.5, dash: "dash" },
    hoverinfo: "skip",
    showlegend: false,
  }];

  const layout = {
    xaxis: { title: `Observed ${unitLbl}`, range: [axMin, axMax],
             showgrid: true, gridcolor: "#eee" },
    yaxis: { title: `AROME ${unitLbl}`,    range: [axMin, axMax],
             showgrid: true, gridcolor: "#eee" },
    legend: { orientation: "h", y: -0.22, font: { size: 11 } },
    hovermode: "closest",
    plot_bgcolor: "#f8fbfc",
    paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 25, b: 70, l: 65 },
    height: 440,
  };

  Plotly.newPlot("scatter-plot", traces, layout,
    { responsive: true, displaylogo: false });
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function _showNoData(cardId) {
  const card = document.getElementById(cardId);
  card.style.display = "";
  const target = card.querySelector(".vrf-plot, .vrf-table-wrap");
  if (target) target.innerHTML =
    `<div class="vrf-nodata">No data available for this source / variable.</div>`;
}

// ── Map: colour scale helpers ──────────────────────────────────────────────────
function _lerp(a, b, t) { return Math.round(a + (b - a) * t); }

function _valToColor(val, vmin, vmax, isDivergent) {
  if (val == null || !isFinite(val)) return "#aaa";
  const t = Math.max(0, Math.min(1, (vmax === vmin) ? 0.5 : (val - vmin) / (vmax - vmin)));
  if (isDivergent) {
    // blue → white → red
    if (t <= 0.5) {
      const s = t * 2;
      return `rgb(${_lerp(44,255,s)},${_lerp(123,255,s)},${_lerp(182,255,s)})`;
    } else {
      const s = (t - 0.5) * 2;
      return `rgb(255,${_lerp(255,69,s)},${_lerp(255,0,s)})`;
    }
  } else {
    // white → dark red
    return `rgb(255,${_lerp(255,0,t)},${_lerp(250,0,t)})`;
  }
}

function _renderLegend(vmin, vmax, isDivergent, units) {
  const el = document.getElementById("map-legend");
  const steps = 200;
  let bars = "";
  for (let i = 0; i < steps; i++) {
    const v = vmin + (i / (steps - 1)) * (vmax - vmin);
    const c = _valToColor(v, vmin, vmax, isDivergent);
    bars += `<span style="background:${c}"></span>`;
  }
  const fmt = (v) => (v >= 0 ? "+" : "") + v.toFixed(2);
  const mid  = isDivergent ? `<span>0 ${units}</span>` : "";
  el.innerHTML =
    `<div class="vrf-legend-bar">${bars}</div>
     <div class="vrf-legend-labels">
       <span>${fmt(vmin)} ${units}</span>${mid}<span>${fmt(vmax)} ${units}</span>
     </div>`;
}

// ── Map: lead-time selector population ────────────────────────────────────────
function _updateMapLeadSel() {
  const sel = document.getElementById("map-lead-sel");
  if (!_data || !sel) return;
  const buckets = (_data.groupings || {})[_grp] || [];
  const cur = sel.value;
  sel.innerHTML = `<option value="all">All lead times</option>`;
  buckets.forEach((b) => {
    const opt = document.createElement("option");
    opt.value = b.label;
    opt.textContent = b.label;
    sel.appendChild(opt);
  });
  // Restore previous selection if still valid
  if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
  _mapLead = sel.value;
}

// ── Map: init + render ─────────────────────────────────────────────────────────
function _initMap() {
  if (_map) return;
  _map = L.map("obs-map", { center: [78, 15], zoom: 3 });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "\u00a9 <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    maxZoom: 10,
  }).addTo(_map);
}

function _renderMap(scatter, varMeta) {
  const card = document.getElementById("map-card");
  card.style.display = "";
  _initMap();
  // Force Leaflet to recalculate size after card becomes visible
  setTimeout(() => _map.invalidateSize(), 50);

  // Domain polygon (AROME Arctic boundary)
  if (_domainLayer) { _map.removeLayer(_domainLayer); _domainLayer = null; }
  const domain = _data.domain || [];
  if (domain.length > 3) {
    _domainLayer = L.polygon(domain, {
      color: "#0b6b8a", weight: 2, fill: false,
      dashArray: "8 5", opacity: 0.9,
    }).addTo(_map);
  }

  // Clear previous dots
  if (_dotLayer) { _map.removeLayer(_dotLayer); _dotLayer = null; }
  document.getElementById("map-legend").innerHTML = "";
  document.getElementById("map-hint").textContent = "";

  const lats = (scatter || {}).lat || [];
  if (!lats.length || lats.every((v) => v == null)) {
    document.getElementById("map-hint").textContent =
      "Location data not yet available \u2014 re-run compute_arome_verification.py to generate it.";
    return;
  }

  const obs   = scatter.obs   || [];
  const model = scatter.model || [];
  const leads = scatter.lead  || [];
  const lons  = scatter.lon   || [];
  const isDivergent = _mapMetric === "bias";
  const units = varMeta.units || "";

  // Find active bucket
  const buckets = (_data.groupings || {})[_grp] || [];
  const activeBucket = _mapLead === "all"
    ? null
    : buckets.find((b) => b.label === _mapLead);

  // Collect filtered points
  const pts = [];
  for (let k = 0; k < obs.length; k++) {
    if (lats[k] == null || lons[k] == null) continue;
    if (activeBucket && !(leads[k] >= activeBucket.lo && leads[k] < activeBucket.hi)) continue;
    const err = model[k] - obs[k];
    const v   = isDivergent ? err : Math.abs(err);
    if (isFinite(v)) pts.push({ lat: lats[k], lon: lons[k], v, lead: leads[k] });
  }

  if (!pts.length) {
    document.getElementById("map-hint").textContent = "No observations in selected lead-time window.";
    return;
  }

  const vals = pts.map((p) => p.v);
  let vmin, vmax;
  if (isDivergent) {
    const absmax = Math.max(...vals.map(Math.abs));
    vmin = -absmax; vmax = absmax;
  } else {
    vmin = 0; vmax = Math.max(...vals);
  }

  const markers = pts.map(({ lat, lon, v, lead }) => {
    const color = _valToColor(v, vmin, vmax, isDivergent);
    const sign  = isDivergent && v >= 0 ? "+" : "";
    return L.circleMarker([lat, lon], {
      radius: 5,
      color: "rgba(0,0,0,0.25)", weight: 0.5,
      fillColor: color, fillOpacity: 0.85,
    }).bindTooltip(
      `${varMeta.label || _var}: ${sign}${v.toFixed(2)} ${units}<br>Lead: ${lead}\u202ah`
    );
  });
  _dotLayer = L.layerGroup(markers).addTo(_map);
  document.getElementById("map-hint").textContent =
    `${pts.length} observation${pts.length !== 1 ? "s" : ""} shown`;
  _renderLegend(vmin, vmax, isDivergent, units);
}

// ── Bootstrap ──────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);
