/* verification.js – unified NWP verification page (AROME / IFS / AIFS)
 *
 * Loads three verification JSONs in parallel and renders:
 *   – Map with model toggle (AROME | IFS | AIFS)
 *   – Bias & MAE chart (all three models, 6 h buckets)
 *   – RMSE chart (all three models, 6 h buckets)
 *   – Scatter plot (per-model checkboxes)
 *   – Error-vs-obs plot (per-model checkboxes)
 */

"use strict";

const IS_LOCAL = location.hostname === "localhost"
              || location.hostname === "127.0.0.1"
              || location.protocol === "file:";

const BASE = IS_LOCAL ? "" : "http://148.230.70.161";

const MODELS = [
  { key: "arome", label: "AROME",    url: `${BASE}/data/arome/verification.json` },
  { key: "ifs",   label: "IFS HRES", url: `${BASE}/data/ecmwf/verification_ifs.json` },
  { key: "aifs",  label: "AIFS",     url: `${BASE}/data/ecmwf/verification_aifs.json` },
];

// Line styles per model
const MODEL_STYLE = {
  arome: { color: "#2e5fa3" },
  ifs:   { color: "#c44b27" },
  aifs:  { color: "#2dab6f" },
};

// ── Palette for scatter lead-time groups ──────────────────────────────────────
const GROUP_COLORS = [
  "#1a6e3c","#2dab6f","#7dcba4","#aee0c8",
  "#2e5fa3","#4a8fcb","#7db9e0","#b3d4ef",
  "#8b3a8b","#c06fcb","#e0aaee","#f3d0f8",
];

const SOURCE_LABELS = {
  ships:      "Ships",
  simba:      "SIMBA buoys",
  thermistor: "Thermistor buoys",
  arctsum:    "ArctSum buoys",
  svalmiz:    "SvalMIZ buoys",
  iabp:       "IABP buoys",
};

// ── State ──────────────────────────────────────────────────────────────────────
const _datasets = {};          // { arome: {...}, ifs: {...}, aifs: {...} }
let _source = null;
let _var    = null;
const _metricsGrp = "6h";
const _scatterGrp = "24h";
let _lead        = "all";
let _mapModel    = "arome";
let _mapMetric   = "bias";
let _map         = null;
let _dotLayer    = null;
let _domainLayer = null;

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
  const statusEl = document.getElementById("vrf-status");
  statusEl.textContent = "Loading verification data\u2026";

  await Promise.allSettled(
    MODELS.map((m) =>
      fetch(m.url)
        .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then((d) => { _datasets[m.key] = d; })
    )
  );

  const loaded = MODELS.filter((m) => _datasets[m.key]);
  if (!loaded.length) {
    statusEl.textContent = "No verification data available. Run the verification scripts on the server.";
    return;
  }
  const failed = MODELS.filter((m) => !_datasets[m.key]).map((m) => m.label);
  if (failed.length) console.warn("Missing verification data for:", failed.join(", "));

  statusEl.style.display = "none";
  _populateSourceSel();
  _wireControls();
  _render();
  document.getElementById("vrf-controls").style.display = "";
  document.getElementById("about-card").style.display   = "";
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function _refData() {
  return _datasets.arome || _datasets.ifs || _datasets.aifs;
}

function _populateSourceSel() {
  const sel = document.getElementById("src-sel");
  sel.innerHTML = "";
  const sources = Object.keys(_refData().stats || {});
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
  if (!_source) return;
  const varSet = new Set();
  for (const m of MODELS) {
    const d = _datasets[m.key];
    if (!d) continue;
    Object.keys((d.stats || {})[_source] || {}).forEach((v) => varSet.add(v));
  }
  [...varSet].forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    const meta = (_refData().variables || {})[v] || {};
    opt.textContent = `${meta.label || v} (${meta.units || ""})`;
    sel.appendChild(opt);
  });
  _var = sel.value || [...varSet][0] || null;
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
  document.getElementById("map-metric-sel").addEventListener("change", (e) => {
    _mapMetric = e.target.value;
    _renderMap();
  });
  document.getElementById("lead-sel").addEventListener("change", (e) => {
    _lead = e.target.value;
    _renderMap();
    _renderScatter();
    _renderErrorVsObs();
  });

  // Map model toggle buttons
  document.getElementById("map-model-btns").addEventListener("click", (e) => {
    const btn = e.target.closest(".vrf-grp-btn");
    if (!btn) return;
    _mapModel = btn.dataset.model;
    document.querySelectorAll("#map-model-btns .vrf-grp-btn").forEach((b) =>
      b.classList.toggle("active", b === btn));
    _renderMap();
  });

  // Scatter / errvsobs model checkboxes
  ["chk-arome","chk-ifs","chk-aifs"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => _renderScatter());
  });
  ["chk-arome-e","chk-ifs-e","chk-aifs-e"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => _renderErrorVsObs());
  });

  _populateVarSel();
}

// ── Main render ───────────────────────────────────────────────────────────────
function _render() {
  if (!_source || !_var) return;

  const periods = MODELS
    .filter((m) => _datasets[m.key])
    .map((m) => {
      const p = _datasets[m.key].period || {};
      return `${m.label}: ${p.start || "?"}\u2013${p.end || "?"}`;
    }).join("   \u2022   ");
  document.getElementById("vrf-meta").textContent = `Periods: ${periods}`;

  _renderBiasMAE();
  _renderRMSE();
  _updateMapLeadSel();
  _renderMap();
  _renderScatter();
  _renderErrorVsObs();
}

function _getBuckets(modelKey) {
  const d = _datasets[modelKey];
  if (!d) return null;
  return ((d.stats[_source] || {})[_var] || {})[_metricsGrp] || null;
}

function _getScatter(modelKey) {
  const d = _datasets[modelKey];
  if (!d) return null;
  return (d.scatter[_source] || {})[_var] || null;
}

function _varMeta() {
  return (_refData().variables || {})[_var] || {};
}

// ── Bias & MAE chart ──────────────────────────────────────────────────────────
function _renderBiasMAE() {
  const card    = document.getElementById("biasmae-card");
  const varMeta = _varMeta();
  const unitLbl = varMeta.units ? ` (${varMeta.units})` : "";
  const traces  = [];

  for (const m of MODELS) {
    const buckets = _getBuckets(m.key);
    if (!buckets) continue;
    const { color } = MODEL_STYLE[m.key];
    const labels = buckets.map((b) => b.label);
    const ns     = buckets.map((b) => b.n || 0);

    traces.push({
      type: "scatter", mode: "lines+markers", name: `${m.label} Bias`,
      x: labels, y: buckets.map((b) => b.bias != null ? +b.bias.toFixed(3) : null),
      customdata: ns,
      hovertemplate: `${m.label} Bias: %{y:.3f}<br>N: %{customdata}<extra></extra>`,
      line: { color, width: 2.5, dash: "dash" }, marker: { size: 6, symbol: "circle" },
    });
    traces.push({
      type: "scatter", mode: "lines+markers", name: `${m.label} MAE`,
      x: labels, y: buckets.map((b) => b.mae != null ? +b.mae.toFixed(3) : null),
      customdata: ns,
      hovertemplate: `${m.label} MAE: %{y:.3f}<br>N: %{customdata}<extra></extra>`,
      line: { color, width: 2.5, dash: "dot" }, marker: { size: 6, symbol: "diamond" },
    });
  }

  if (!traces.length) { card.style.display = "none"; return; }
  card.style.display = "";

  Plotly.newPlot("biasmae-plot", traces, {
    xaxis: { title: "Lead time", tickfont: { size: 11 } },
    yaxis: { title: `Bias / MAE${unitLbl}`, autorange: true,
             showgrid: true, gridcolor: "#eee",
             zeroline: true, zerolinecolor: "#bbb", zerolinewidth: 1.5 },
    legend: { orientation: "h", y: -0.28, font: { size: 11 } },
    hovermode: "x unified",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 25, b: 90, l: 65 }, height: 340,
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1,
               yref: "y", y0: 0, y1: 0,
               line: { color: "#999", width: 1, dash: "dot" } }],
  }, { responsive: true, displaylogo: false });
}

// ── RMSE chart ────────────────────────────────────────────────────────────────
function _renderRMSE() {
  const card    = document.getElementById("rmse-card");
  const varMeta = _varMeta();
  const unitLbl = varMeta.units ? ` (${varMeta.units})` : "";
  const traces  = [];

  for (const m of MODELS) {
    const buckets = _getBuckets(m.key);
    if (!buckets) continue;
    const { color } = MODEL_STYLE[m.key];
    traces.push({
      type: "scatter", mode: "lines+markers", name: m.label,
      x: buckets.map((b) => b.label),
      y: buckets.map((b) => b.rmse != null ? +b.rmse.toFixed(3) : null),
      customdata: buckets.map((b) => b.n || 0),
      hovertemplate: `${m.label} RMSE: %{y:.3f}<br>N: %{customdata}<extra></extra>`,
      line: { color, width: 2.5 }, marker: { size: 7 },
    });
  }

  if (!traces.length) { card.style.display = "none"; return; }
  card.style.display = "";

  Plotly.newPlot("rmse-plot", traces, {
    xaxis: { title: "Lead time", tickfont: { size: 11 } },
    yaxis: { title: `RMSE${unitLbl}`, autorange: true,
             showgrid: true, gridcolor: "#eee" },
    legend: { orientation: "h", y: -0.28, font: { size: 11 } },
    hovermode: "x unified",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 25, b: 90, l: 65 }, height: 340,
  }, { responsive: true, displaylogo: false });
}

// ── Scatter plot ──────────────────────────────────────────────────────────────
function _renderScatter() {
  const card    = document.getElementById("scatter-card");
  const varMeta = _varMeta();
  const unitLbl = varMeta.units || "";

  const activeModels = MODELS.filter((m) => {
    const chk = document.getElementById(`chk-${m.key}`);
    return chk && chk.checked && _getScatter(m.key);
  });

  if (!activeModels.length) { card.style.display = "none"; return; }
  card.style.display = "";

  const buckets = (_refData().groupings || {})[_scatterGrp] || [];
  const traces  = [];
  const allVals = [];

  for (const m of activeModels) {
    const sc = _getScatter(m.key);
    if (!sc || !sc.obs) continue;
    const { color } = MODEL_STYLE[m.key];

    const traceMap = new Map();
    buckets.forEach((b, idx) => {
      const opacity = 0.25 + 0.6 * (idx / Math.max(1, buckets.length - 1));
      traceMap.set(b.label, {
        type: "scattergl", mode: "markers",
        name: `${m.label} ${b.label}`,
        legendgroup: m.key, showlegend: idx === 0,
        x: [], y: [],
        marker: { color, opacity, size: 4 },
        hovertemplate:
          `${m.label} ${b.label}<br>Obs: %{x:.2f} ${unitLbl}<br>Model: %{y:.2f} ${unitLbl}<extra></extra>`,
      });
    });

    sc.obs.forEach((o, k) => {
      const bucket = buckets.find((b) => sc.lead[k] >= b.lo && sc.lead[k] < b.hi);
      if (!bucket) return;
      const tr = traceMap.get(bucket.label);
      if (tr) { tr.x.push(o); tr.y.push(sc.model[k]); allVals.push(o, sc.model[k]); }
    });
    traces.push(...traceMap.values());
  }

  if (!traces.length) { card.style.display = "none"; return; }

  const vMin = Math.min(...allVals), vMax = Math.max(...allVals);
  const pad  = (vMax - vMin) * 0.05;
  traces.push({
    type: "scatter", mode: "lines", name: "1:1",
    x: [vMin - pad, vMax + pad], y: [vMin - pad, vMax + pad],
    line: { color: "#888", width: 1.5, dash: "dash" },
    hoverinfo: "skip", showlegend: false,
  });

  Plotly.newPlot("scatter-plot", traces, {
    xaxis: { title: `Observed ${unitLbl}`, range: [vMin - pad, vMax + pad],
             showgrid: true, gridcolor: "#eee" },
    yaxis: { title: `Model ${unitLbl}`,    range: [vMin - pad, vMax + pad],
             showgrid: true, gridcolor: "#eee" },
    legend: { orientation: "h", y: -0.22, font: { size: 11 } },
    hovermode: "closest",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 25, b: 70, l: 65 }, height: 420,
  }, { responsive: true, displaylogo: false });
}

// ── Error vs. observed ────────────────────────────────────────────────────────
function _renderErrorVsObs() {
  const card    = document.getElementById("errvsobs-card");
  const varMeta = _varMeta();
  const unitLbl = varMeta.units ? ` (${varMeta.units})` : "";

  const activeModels = MODELS.filter((m) => {
    const chk = document.getElementById(`chk-${m.key}-e`);
    return chk && chk.checked && _getScatter(m.key);
  });

  if (!activeModels.length) { card.style.display = "none"; return; }
  card.style.display = "";

  const buckets      = (_refData().groupings || {})[_scatterGrp] || [];
  const activeBucket = _lead === "all"
    ? null : buckets.find((b) => b.label === _lead);

  const traces = [];
  const allObs = [], allErrs = [];

  for (const m of activeModels) {
    const sc = _getScatter(m.key);
    if (!sc || !sc.obs) continue;
    const { color } = MODEL_STYLE[m.key];

    const obs = [], errs = [];
    sc.obs.forEach((o, k) => {
      const lead = sc.lead[k];
      if (activeBucket && !(lead >= activeBucket.lo && lead < activeBucket.hi)) return;
      obs.push(o); errs.push(+(sc.model[k] - o).toFixed(4));
    });
    if (!obs.length) continue;
    allObs.push(...obs); allErrs.push(...errs);

    traces.push({
      type: "scattergl", mode: "markers", name: m.label,
      legendgroup: m.key, showlegend: true,
      x: obs, y: errs,
      marker: { color, size: 4, opacity: 0.45 },
      hovertemplate:
        `${m.label}<br>Obs: %{x:.2f} ${varMeta.units || ""}<br>Error: %{y:+.2f} ${varMeta.units || ""}<extra></extra>`,
    });

    // Trend line per model
    const n     = obs.length;
    const meanX = obs.reduce((s, v) => s + v, 0) / n;
    const meanY = errs.reduce((s, v) => s + v, 0) / n;
    const num   = obs.reduce((s, v, k) => s + (v - meanX) * (errs[k] - meanY), 0);
    const den   = obs.reduce((s, v)    => s + (v - meanX) ** 2, 0);
    if (den !== 0) {
      const slope = num / den;
      const ic    = meanY - slope * meanX;
      const xMin  = Math.min(...obs), xMax = Math.max(...obs);
      traces.push({
        type: "scatter", mode: "lines",
        name: `${m.label} trend (${slope >= 0 ? "+" : ""}${slope.toFixed(3)})`,
        legendgroup: m.key, showlegend: false,
        x: [xMin, xMax], y: [slope * xMin + ic, slope * xMax + ic],
        line: { color, width: 2, dash: "dash" }, hoverinfo: "skip",
      });
    }
  }

  if (!traces.length) { card.style.display = "none"; return; }

  const errPad = (Math.max(...allErrs.map(Math.abs)) || 1) * 0.08;
  const obsPad = ((Math.max(...allObs) - Math.min(...allObs)) || 1) * 0.03;

  Plotly.newPlot("errvsobs-plot", traces, {
    xaxis: { title: `Observed${unitLbl}`,
             range: [Math.min(...allObs) - obsPad, Math.max(...allObs) + obsPad],
             showgrid: true, gridcolor: "#eee" },
    yaxis: { title: `Error (model\u2212obs)${unitLbl}`,
             zeroline: true, zerolinecolor: "#888", zerolinewidth: 1.5,
             showgrid: true, gridcolor: "#eee",
             range: [Math.min(...allErrs) - errPad, Math.max(...allErrs) + errPad] },
    legend: { orientation: "h", y: -0.22, font: { size: 11 } },
    hovermode: "closest",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 25, b: 70, l: 70 }, height: 420,
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1,
               yref: "y", y0: 0, y1: 0,
               line: { color: "#888", width: 1, dash: "dot" } }],
  }, { responsive: true, displaylogo: false });
}

// ── Map ───────────────────────────────────────────────────────────────────────
function _updateMapLeadSel() {
  const sel     = document.getElementById("lead-sel");
  const buckets = (_refData().groupings || {})[_scatterGrp] || [];
  const cur     = sel.value;
  sel.innerHTML = `<option value="all">All lead times</option>`;
  buckets.forEach((b) => {
    const opt = document.createElement("option");
    opt.value = b.label; opt.textContent = b.label;
    sel.appendChild(opt);
  });
  if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
  _lead = sel.value;
}

function _initMap() {
  if (_map) return;
  _map = L.map("obs-map", { center: [78, 15], zoom: 3 });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "\u00a9 <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    maxZoom: 10,
  }).addTo(_map);
}

function _renderMap() {
  const card = document.getElementById("map-card");
  card.style.display = "";
  _initMap();
  setTimeout(() => _map.invalidateSize(), 50);

  if (_domainLayer) { _map.removeLayer(_domainLayer); _domainLayer = null; }
  if (_dotLayer)    { _map.removeLayer(_dotLayer);    _dotLayer    = null; }
  document.getElementById("map-legend").innerHTML = "";
  document.getElementById("map-hint").textContent = "";

  const d = _datasets[_mapModel];
  if (!d) {
    document.getElementById("map-hint").textContent =
      `No data available for ${MODELS.find((m) => m.key === _mapModel)?.label}.`;
    return;
  }

  const domain = d.domain || [];
  if (domain.length > 3) {
    _domainLayer = L.polygon(domain, {
      color: "#0b6b8a", weight: 2, fill: false, dashArray: "8 5", opacity: 0.9,
    }).addTo(_map);
  }

  const scatter  = (d.scatter[_source] || {})[_var];
  const varMeta  = _varMeta();
  const lats     = (scatter || {}).lat || [];
  if (!lats.length || lats.every((v) => v == null)) {
    document.getElementById("map-hint").textContent = "Location data not available.";
    return;
  }

  const obs          = scatter.obs   || [];
  const model        = scatter.model || [];
  const leads        = scatter.lead  || [];
  const lons         = scatter.lon   || [];
  const isDivergent  = _mapMetric === "bias";
  const units        = varMeta.units || "";
  const buckets      = (d.groupings || {})[_scatterGrp] || [];
  const activeBucket = _lead === "all"
    ? null : buckets.find((b) => b.label === _lead);

  const rawPts = [];
  for (let k = 0; k < obs.length; k++) {
    if (lats[k] == null || lons[k] == null) continue;
    if (activeBucket && !(leads[k] >= activeBucket.lo && leads[k] < activeBucket.hi)) continue;
    const err = model[k] - obs[k];
    const v   = isDivergent ? err : Math.abs(err);
    if (isFinite(v)) rawPts.push({ lat: lats[k], lon: lons[k], v });
  }

  if (!rawPts.length) {
    document.getElementById("map-hint").textContent = "No observations in selected lead-time window.";
    return;
  }

  const locAgg = new Map();
  for (const p of rawPts) {
    const key = `${p.lat.toFixed(2)},${p.lon.toFixed(2)}`;
    if (!locAgg.has(key)) locAgg.set(key, { lat: p.lat, lon: p.lon, sum: 0, n: 0 });
    const e = locAgg.get(key); e.sum += p.v; e.n++;
  }
  const pts  = [...locAgg.values()].map((e) => ({ lat: e.lat, lon: e.lon, v: e.sum / e.n, n: e.n }));
  const vals = pts.map((p) => p.v);

  let vmin, vmax;
  if (isDivergent) {
    if (_var === "air_temp" || _var === "sea_surface_temp") { vmin = -5; vmax = 5; }
    else { const a = Math.max(...vals.map(Math.abs)); vmin = -a; vmax = a; }
  } else { vmin = 0; vmax = Math.max(...vals); }

  const markers = pts.map(({ lat, lon, v, n }) => {
    const color = _valToColor(v, vmin, vmax, isDivergent);
    const sign  = isDivergent && v >= 0 ? "+" : "";
    return L.circleMarker([lat, lon], {
      radius: 5, color: "rgba(0,0,0,0.25)", weight: 0.5,
      fillColor: color, fillOpacity: 0.85,
    }).bindTooltip(
      `${varMeta.label || _var}: ${sign}${v.toFixed(2)} ${units}<br>n\u202a=\u202a${n}`
    );
  });
  _dotLayer = L.layerGroup(markers).addTo(_map);
  document.getElementById("map-hint").textContent =
    `${MODELS.find((m) => m.key === _mapModel)?.label}  \u2022  `
    + `${pts.length} location${pts.length !== 1 ? "s" : ""} (${rawPts.length} pairs)`;
  _renderLegend(vmin, vmax, isDivergent, units);
}

// ── Colour helpers ────────────────────────────────────────────────────────────
function _lerp(a, b, t) { return Math.round(a + (b - a) * t); }

function _valToColor(val, vmin, vmax, isDivergent) {
  if (val == null || !isFinite(val)) return "#aaa";
  const t = Math.max(0, Math.min(1, vmax === vmin ? 0.5 : (val - vmin) / (vmax - vmin)));
  if (isDivergent) {
    if (t <= 0.5) {
      const s = t * 2;
      return `rgb(${_lerp(44,255,s)},${_lerp(123,255,s)},${_lerp(182,255,s)})`;
    }
    const s = (t - 0.5) * 2;
    return `rgb(255,${_lerp(255,69,s)},${_lerp(255,0,s)})`;
  }
  return `rgb(255,${_lerp(255,0,t)},${_lerp(250,0,t)})`;
}

function _renderLegend(vmin, vmax, isDivergent, units) {
  let bars = "";
  for (let i = 0; i < 200; i++) {
    const v = vmin + (i / 199) * (vmax - vmin);
    bars += `<span style="background:${_valToColor(v, vmin, vmax, isDivergent)}"></span>`;
  }
  const fmt = (v) => (v >= 0 ? "+" : "") + v.toFixed(2);
  const mid  = isDivergent ? `<span>0 ${units}</span>` : "";
  document.getElementById("map-legend").innerHTML =
    `<div class="vrf-legend-bar">${bars}</div>
     <div class="vrf-legend-labels">
       <span>${fmt(vmin)} ${units}</span>${mid}<span>${fmt(vmax)} ${units}</span>
     </div>`;
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);
