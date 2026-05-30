/* verification_ecmwf.js – ECMWF IFS / AIFS verification page
 *
 * Loads /data/ecmwf/verification_{ifs|aifs}.json and renders the same
 * charts as the AROME verification page, with a model selector at the top.
 */

"use strict";

const IS_LOCAL = location.hostname === "localhost"
              || location.hostname === "127.0.0.1"
              || location.protocol === "file:";
const ECMWF_BASE = IS_LOCAL
  ? "data/ecmwf"
  : "http://148.230.70.161/data/ecmwf";

const MODEL_META = {
  ifs:      { label: "IFS HRES",              shortLabel: "IFS",      steps: "hourly 0–72 h",   res: "0.1°" },
  aifs:     { label: "AIFS",                  shortLabel: "AIFS",     steps: "6-hourly 0–72 h", res: "0.1°" },
  ifs_exp:  { label: "IFS experimental",      shortLabel: "IFS exp",  steps: "hourly 0–72 h",   res: "0.1°" },
  aifs_exp: { label: "AIFS experimental",     shortLabel: "AIFS exp", steps: "6-hourly 0–72 h", res: "0.1°" },
};

const GROUP_COLORS = [
  "#1a6e3c","#2dab6f","#7dcba4","#aee0c8",
  "#2e5fa3","#4a8fcb","#7db9e0","#b3d4ef",
  "#8b3a8b","#c06fcb","#e0aaee","#f3d0f8",
];

const SOURCE_LABELS = {
  _land_all:    "Land-based weather (all)",
  _land_arome:  "Land-based weather (AROME Arctic domain)",
  svalbard:     "Svalbard & Jan Mayen",
  north_norway: "Northern Norway",
  offshore:     "Offshore platforms",
  greenland:    "Greenland (DMI)",
  canada:       "Canada (ECCC)",
  alaska:       "Alaska (NWS)",
  russia:       "Russia / FJL / NZ",
  iceland:      "Iceland (IMO)",
  finland:      "Finland (FMI)",
  sweden:       "Sweden (SMHI)",
  norway_buoys: "MET Norway buoys",
  ships:        "Ships",
  simba:        "SIMBA buoys",
  thermistor:   "Thermistor buoys",
  arctsum:      "ArctSum buoys",
  svalmiz:      "SvalMIZ buoys",
  iabp:         "IABP buoys",
};

// Land sources for the aggregate options
const _LAND_SOURCES_ALL = [
  "svalbard", "north_norway", "offshore", "greenland", "canada",
  "alaska", "russia", "iceland", "finland", "sweden",
];
const _LAND_SOURCES_AROME = [
  "svalbard", "north_norway", "offshore", "greenland",
  "iceland", "finland", "sweden",
];

// Fixed source dropdown (6 curated options)
const _FIXED_SOURCES = ["_land_all", "_land_arome", "svalmiz", "arctsum", "ships", "iabp"];

function _aggSources() {
  if (_source === "_land_all")   return _LAND_SOURCES_ALL;
  if (_source === "_land_arome") return _LAND_SOURCES_AROME;
  return null;
}

// ── Aggregate helpers for "All weather stations" option ──────────────────
function _mergeBuckets(allBuckets) {
  if (!allBuckets.length) return null;
  const nB = allBuckets[0].length;
  return Array.from({ length: nB }, (_, i) => {
    const label = allBuckets[0][i].label;
    let totalN = 0, wBias = 0, wMAE = 0, wRMSE2 = 0;
    for (const bkts of allBuckets) {
      const b = bkts[i];
      if (!b || b.n < 2 || b.rmse == null) continue;
      totalN += b.n; wBias += b.n * b.bias; wMAE += b.n * b.mae; wRMSE2 += b.n * b.rmse * b.rmse;
    }
    if (totalN < 2) return { label, n: totalN, rmse: null, mae: null, bias: null };
    return { label, n: totalN, bias: wBias / totalN, mae: wMAE / totalN, rmse: Math.sqrt(wRMSE2 / totalN) };
  });
}

function _mergeScatter(scatters) {
  const r = { obs: [], model: [], lead: [], lat: [], lon: [] };
  for (const sc of scatters) {
    if (!sc || !sc.obs) continue;
    r.obs.push(...sc.obs); r.model.push(...sc.model); r.lead.push(...sc.lead);
    r.lat.push(...(sc.lat || sc.obs.map(() => null)));
    r.lon.push(...(sc.lon || sc.obs.map(() => null)));
  }
  return r.obs.length ? r : null;
}

// ── State ──────────────────────────────────────────────────────────────────────
let _data   = null;
let _model  = "ifs";
let _source = null;
let _var    = null;
const _grp        = "24h";
const _metricsGrp = "6h";
let _map         = null;
let _dotLayer    = null;
let _domainLayer = null;
let _mapMetric   = "bias";
let _lead        = "all";

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
  const statusEl = document.getElementById("vrf-status");
  await _loadModel(statusEl);
}

async function _loadModel(statusEl) {
  if (!statusEl) statusEl = document.getElementById("vrf-status");
  statusEl.style.display = "";
  statusEl.textContent   = "Loading verification data\u2026";

  // Hide all cards while loading
  ["vrf-controls","map-card","metrics-card","table-card",
   "scatter-card","errvsobs-card","about-card"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });

  try {
    const resp = await fetch(`${ECMWF_BASE}/verification_${_model}.json`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    _data = await resp.json();
  } catch (err) {
    statusEl.textContent =
      `Verification data for ${MODEL_META[_model].label} not yet available. `
      + `(${err.message})`;
    return;
  }

  statusEl.style.display = "none";

  // Re-populate controls and render
  _populateSourceSel();
  _wireControls();
  _render();

  document.getElementById("vrf-controls").style.display = "";
  document.getElementById("about-card").style.display   = "";
  _updateAbout();
}

function _updateAbout() {
  const m = MODEL_META[_model];
  document.getElementById("about-text").innerHTML =
    `Each surface observation is paired with the nearest grid point of the ECMWF
    <strong>${m.label}</strong> deterministic forecast (00\u202aZ and 12\u202aZ runs,
    ${m.steps}, ${m.res} resolution). Maximum accepted distance: 0.5&deg;.
    RMSE\u202a=\u202aroot-mean-square error, MAE\u202a=\u202amean absolute error,
    BIAS\u202a=\u202amean(model\u202a&minus;\u202aobs) &mdash; positive bias means the model is too high.
    Statistics are updated once daily between 09:00 and 21:00\u202aUTC.`;
}

// ── UI population ──────────────────────────────────────────────────────────────
function _populateSourceSel() {
  const sel = document.getElementById("src-sel");
  sel.innerHTML = "";
  _FIXED_SOURCES.forEach((src) => {
    const opt = document.createElement("option");
    opt.value = src;
    opt.textContent = SOURCE_LABELS[src] || src;
    sel.appendChild(opt);
  });
  sel.value = "_land_all";
  _source = "_land_all";
}

function _populateVarSel() {
  const sel = document.getElementById("var-sel");
  sel.innerHTML = "";
  if (!_source) return;
  const varSet = new Set();
  const _agg = _aggSources();
  if (_agg) {
    _agg.forEach((src) => Object.keys((_data.stats || {})[src] || {}).forEach((v) => varSet.add(v)));
  } else {
    if (!_data.stats[_source]) return;
    Object.keys(_data.stats[_source]).forEach((v) => varSet.add(v));
  }
  [...varSet].forEach((v) => {
    const opt = document.createElement("option");
    opt.value = v;
    const meta = (_data.variables || {})[v] || {};
    opt.textContent = `${meta.label || v} (${meta.units || ""})`;
    sel.appendChild(opt);
  });
  _var = sel.value || [...varSet][0] || null;
}

function _wireControls() {
  // Avoid double-binding on model switch — remove old listeners by cloning
  ["model-sel","src-sel","var-sel","map-metric-sel","lead-sel"].forEach((id) => {
    const el = document.getElementById(id);
    const clone = el.cloneNode(true);
    el.parentNode.replaceChild(clone, el);
  });

  document.getElementById("model-sel").addEventListener("change", async (e) => {
    _model = e.target.value;
    // Reset map layers when switching model
    if (_dotLayer)    { _map && _map.removeLayer(_dotLayer);    _dotLayer    = null; }
    if (_domainLayer) { _map && _map.removeLayer(_domainLayer); _domainLayer = null; }
    await _loadModel();
  });

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
    const scatter  = _aggSources()
      ? _mergeScatter(_aggSources().map((s) => (_data.scatter[s] || {})[_var]).filter(Boolean))
      : (_data.scatter[_source] || {})[_var];
    const varMeta  = (_data.variables || {})[_var] || {};
    _renderMap(scatter, varMeta);
  });
  document.getElementById("lead-sel").addEventListener("change", (e) => {
    _lead = e.target.value;
    const scatter = _aggSources()
      ? _mergeScatter(_aggSources().map((s) => (_data.scatter[s] || {})[_var]).filter(Boolean))
      : (_data.scatter[_source] || {})[_var];
    const varMeta = (_data.variables || {})[_var] || {};
    _renderMap(scatter, varMeta);
    _renderErrorVsObs(scatter, varMeta);
  });

  // Restore model selector value after clone
  document.getElementById("model-sel").value = _model;

  _populateVarSel();
}

// ── Main render ────────────────────────────────────────────────────────────────
function _render() {
  if (!_source || !_var) return;

  let statsForVar, scatterForVar;
  const _agg = _aggSources();
  if (_agg) {
    const allBkts = _agg.map((src) => ((_data.stats[src] || {})[_var] || {})[_metricsGrp]).filter(Boolean);
    statsForVar = allBkts.length ? _mergeBuckets(allBkts) : null;
    const allScat = _agg.map((src) => (_data.scatter[src] || {})[_var]).filter(Boolean);
    scatterForVar = allScat.length ? _mergeScatter(allScat) : null;
  } else {
    statsForVar   = ((_data.stats[_source]   || {})[_var] || {})[_metricsGrp];
    scatterForVar = (_data.scatter[_source]  || {})[_var];
  }
  const varMeta       = (_data.variables         || {})[_var] || {};
  const period        = _data.period || {};

  document.getElementById("vrf-meta").textContent =
    `Model: ${MODEL_META[_model].label}  •  `
    + `Period: ${period.start || "?"} \u2192 ${period.end || "?"}  •  `
    + `Generated: ${(_data.generated || "").slice(0, 16).replace("T", " ")} UTC`;

  if (!statsForVar) {
    _showNoData("metrics-card");
    _showNoData("table-card");
    _showNoData("scatter-card");
    _showNoData("errvsobs-card");
  } else {
    _renderMetricsChart(statsForVar, varMeta);
    _renderTable(statsForVar, varMeta);
    _renderScatter(scatterForVar, varMeta);
    _renderErrorVsObs(scatterForVar, varMeta);
  }

  _updateMapLeadSel();
  _renderMap(scatterForVar, varMeta);
}

// ── Metrics bar + bias line chart ──────────────────────────────────────────────
function _renderMetricsChart(buckets, varMeta) {
  document.getElementById("metrics-card").style.display = "";
  const labels = buckets.map((b) => b.label);
  const rmse   = buckets.map((b) => (b.rmse != null ? +b.rmse.toFixed(3) : null));
  const mae    = buckets.map((b) => (b.mae  != null ? +b.mae.toFixed(3)  : null));
  const bias   = buckets.map((b) => (b.bias != null ? +b.bias.toFixed(3) : null));
  const ns     = buckets.map((b) => b.n || 0);
  const unitLbl = varMeta.units ? ` (${varMeta.units})` : "";

  const traces = [
    {
      type: "scatter", mode: "lines+markers", name: "RMSE",
      x: labels, y: rmse, customdata: ns,
      hovertemplate: "RMSE: %{y:.3f}<br>N: %{customdata}<extra></extra>",
      line: { color: "#2e5fa3", width: 2.5 }, marker: { size: 7 },
    },
    {
      type: "scatter", mode: "lines+markers", name: "MAE",
      x: labels, y: mae, customdata: ns,
      hovertemplate: "MAE: %{y:.3f}<br>N: %{customdata}<extra></extra>",
      line: { color: "#2dab6f", width: 2.5 }, marker: { size: 7 },
    },
    {
      type: "scatter", mode: "lines+markers", name: "BIAS",
      x: labels, y: bias, customdata: ns,
      hovertemplate: "BIAS: %{y:.3f}<br>N: %{customdata}<extra></extra>",
      line: { color: "#e05c2e", width: 2.5 }, marker: { size: 7 },
      yaxis: "y2",
    },
  ];

  Plotly.newPlot("metrics-plot", traces, {
    xaxis: { title: "Lead time", tickfont: { size: 12 } },
    yaxis: { title: `Error${unitLbl}`, side: "left", autorange: true,
             showgrid: true, gridcolor: "#eee" },
    yaxis2: { title: `BIAS${unitLbl}`, side: "right", overlaying: "y",
              autorange: true, zeroline: true, zerolinecolor: "#ccc",
              zerolinewidth: 1.5, showgrid: false },
    legend: { orientation: "h", y: -0.2, font: { size: 12 } },
    hovermode: "x unified",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 70, b: 60, l: 65 }, height: 320,
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1,
               yref: "y2", y0: 0, y1: 0,
               line: { color: "#e05c2e", width: 1, dash: "dot" } }],
  }, { responsive: true, displaylogo: false });
}

// ── Summary table ──────────────────────────────────────────────────────────────
function _renderTable(buckets, varMeta) {
  document.getElementById("table-card").style.display = "";
  const unitLbl = varMeta.units ? ` (${varMeta.units})` : "";
  let html = `<table class="vrf-table"><thead><tr>
    <th>Lead time</th><th>N</th>
    <th>RMSE${unitLbl}</th><th>MAE${unitLbl}</th><th>BIAS${unitLbl}</th>
    </tr></thead><tbody>`;
  buckets.forEach((b) => {
    if (b.n < 2) {
      html += `<tr><td>${b.label}</td><td class="num">${b.n}</td>
        <td colspan="3" class="no-data">\u2014 insufficient data \u2014</td></tr>`;
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
  document.getElementById("stats-table").innerHTML = html + "</tbody></table>";
}

// ── Scatter plot ───────────────────────────────────────────────────────────────
function _renderScatter(scatter, varMeta) {
  const card = document.getElementById("scatter-card");
  if (!scatter || !scatter.obs || scatter.obs.length === 0) { card.style.display = "none"; return; }
  card.style.display = "";

  const obs   = scatter.obs;
  const model = scatter.model;
  const leads = scatter.lead;
  const unitLbl = varMeta.units || "";
  const modelLbl = MODEL_META[_model].shortLabel;

  const buckets = (_data.groupings || {})[_grp] || [];
  const traceMap = new Map();
  buckets.forEach((b, idx) => {
    traceMap.set(b.label, {
      type: "scattergl", mode: "markers", name: b.label,
      x: [], y: [],
      marker: { color: GROUP_COLORS[idx % GROUP_COLORS.length], size: 5, opacity: 0.65 },
      hovertemplate: `Obs: %{x:.2f} ${unitLbl}<br>${modelLbl}: %{y:.2f} ${unitLbl}<extra>${b.label}</extra>`,
    });
  });

  obs.forEach((o, k) => {
    const bucket = buckets.find((b) => leads[k] >= b.lo && leads[k] < b.hi);
    if (!bucket) return;
    const tr = traceMap.get(bucket.label);
    if (tr) { tr.x.push(o); tr.y.push(model[k]); }
  });

  const allVals = [...obs, ...model].filter((v) => v != null);
  let vMin = Infinity, vMax = -Infinity;
  for (const v of allVals) { if (v < vMin) vMin = v; if (v > vMax) vMax = v; }
  const pad  = (vMax - vMin) * 0.05;

  const traces = [...traceMap.values(), {
    type: "scatter", mode: "lines", name: "1:1",
    x: [vMin - pad, vMax + pad], y: [vMin - pad, vMax + pad],
    line: { color: "#888", width: 1.5, dash: "dash" },
    hoverinfo: "skip", showlegend: false,
  }];

  Plotly.newPlot("scatter-plot", traces, {
    xaxis: { title: `Observed ${unitLbl}`, range: [vMin - pad, vMax + pad],
             showgrid: true, gridcolor: "#eee" },
    yaxis: { title: `${modelLbl} ${unitLbl}`, range: [vMin - pad, vMax + pad],
             showgrid: true, gridcolor: "#eee" },
    legend: { orientation: "h", y: -0.22, font: { size: 11 } },
    hovermode: "closest",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 25, b: 70, l: 65 }, height: 380,
  }, { responsive: true, displaylogo: false });
}

// ── Error vs. observed ─────────────────────────────────────────────────────────
function _renderErrorVsObs(scatter, varMeta) {
  const card = document.getElementById("errvsobs-card");
  if (!scatter || !scatter.obs || scatter.obs.length === 0) { card.style.display = "none"; return; }
  card.style.display = "";

  const obsAll   = scatter.obs;
  const modelAll = scatter.model;
  const leadsAll = scatter.lead;
  const unitLbl  = varMeta.units ? ` (${varMeta.units})` : "";

  const buckets  = (_data.groupings || {})[_grp] || [];
  const activeBucket = _lead === "all"
    ? null
    : buckets.find((b) => b.label === _lead);

  const obs = [], model = [], leads = [];
  obsAll.forEach((o, k) => {
    const lead = leadsAll[k];
    if (activeBucket && !(lead >= activeBucket.lo && lead < activeBucket.hi)) return;
    obs.push(o); model.push(modelAll[k]); leads.push(lead);
  });

  if (!obs.length) { card.style.display = "none"; return; }

  const traces = [];
  if (activeBucket) {
    traces.push({
      type: "scattergl", mode: "markers", name: activeBucket.label,
      x: obs, y: obs.map((o, k) => +(model[k] - o).toFixed(4)),
      marker: { color: "#5b8fd4", size: 4, opacity: 0.55 },
      hovertemplate: `Obs: %{x:.2f} ${varMeta.units || ""}<br>Error: %{y:+.2f} ${varMeta.units || ""}<extra>${activeBucket.label}</extra>`,
    });
  } else {
    const traceMap = new Map();
    buckets.forEach((b, idx) => {
      traceMap.set(b.label, {
        type: "scattergl", mode: "markers", name: b.label,
        x: [], y: [],
        marker: { color: GROUP_COLORS[idx % GROUP_COLORS.length], size: 4, opacity: 0.55 },
        hovertemplate: `Obs: %{x:.2f} ${varMeta.units || ""}<br>Error: %{y:+.2f} ${varMeta.units || ""}<extra>${b.label}</extra>`,
      });
    });
    obs.forEach((o, k) => {
      const bucket = buckets.find((b) => leads[k] >= b.lo && leads[k] < b.hi);
      if (!bucket) return;
      const tr = traceMap.get(bucket.label);
      if (tr) { tr.x.push(o); tr.y.push(+(model[k] - o).toFixed(4)); }
    });
    traces.push(...traceMap.values());
  }

  // Trend line
  const allErrs = obs.map((o, k) => model[k] - o);
  const n = obs.length;
  let slope = 0, intercept = 0;
  if (n > 1) {
    const meanX = obs.reduce((s, v) => s + v, 0) / n;
    const meanY = allErrs.reduce((s, v) => s + v, 0) / n;
    const num = obs.reduce((s, v, k) => s + (v - meanX) * (allErrs[k] - meanY), 0);
    const den = obs.reduce((s, v)    => s + (v - meanX) ** 2, 0);
    if (den !== 0) { slope = num / den; intercept = meanY - slope * meanX; }
  }
  let xMin = Infinity, xMax = -Infinity;
  for (const v of obs) { if (v < xMin) xMin = v; if (v > xMax) xMax = v; }
  traces.push({
    type: "scatter", mode: "lines",
    name: `Trend (slope ${slope >= 0 ? "+" : ""}${slope.toFixed(3)})`,
    x: [xMin, xMax], y: [slope * xMin + intercept, slope * xMax + intercept],
    line: { color: "#333", width: 2, dash: "dash" },
    hoverinfo: "skip",
  });

  let _eAbsMax = 0; for (const e of allErrs) { const ae = Math.abs(e); if (ae > _eAbsMax) _eAbsMax = ae; }
  const errPad = (_eAbsMax || 1) * 0.08;
  const obsPad = (xMax - xMin) * 0.03;

  Plotly.newPlot("errvsobs-plot", traces, {
    xaxis: { title: `Observed${unitLbl}`, showgrid: true, gridcolor: "#eee",
             range: [xMin - obsPad, xMax + obsPad] },
    yaxis: { title: `Error (model\u2212obs)${unitLbl}`,
             zeroline: true, zerolinecolor: "#888", zerolinewidth: 1.5,
             showgrid: true, gridcolor: "#eee",
             range: [allErrs.reduce((a, v) => v < a ? v : a, Infinity) - errPad,
                     allErrs.reduce((a, v) => v > a ? v : a, -Infinity) + errPad] },
    legend: { orientation: "h", y: -0.22, font: { size: 11 } },
    hovermode: "closest",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    margin: { t: 20, r: 25, b: 70, l: 70 }, height: 360,
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1,
               yref: "y", y0: 0, y1: 0,
               line: { color: "#888", width: 1, dash: "dot" } }],
  }, { responsive: true, displaylogo: false });
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function _showNoData(cardId) {
  const card = document.getElementById(cardId);
  card.style.display = "";
  const target = card.querySelector(".vrf-plot, .vrf-table-wrap");
  if (target) target.innerHTML =
    `<div class="vrf-nodata">No data available for this source / variable.</div>`;
}

function _lerp(a, b, t) { return Math.round(a + (b - a) * t); }

function _valToColor(val, vmin, vmax, isDivergent) {
  if (val == null || !isFinite(val)) return "#aaa";
  const t = Math.max(0, Math.min(1, vmax === vmin ? 0.5 : (val - vmin) / (vmax - vmin)));
  if (isDivergent) {
    if (t <= 0.5) {
      const s = t * 2;
      return `rgb(${_lerp(44,255,s)},${_lerp(123,255,s)},${_lerp(182,255,s)})`;
    } else {
      const s = (t - 0.5) * 2;
      return `rgb(255,${_lerp(255,69,s)},${_lerp(255,0,s)})`;
    }
  }
  return `rgb(255,${_lerp(255,0,t)},${_lerp(250,0,t)})`;
}

function _renderLegend(vmin, vmax, isDivergent, units) {
  const el = document.getElementById("map-legend");
  let bars = "";
  for (let i = 0; i < 200; i++) {
    const v = vmin + (i / 199) * (vmax - vmin);
    bars += `<span style="background:${_valToColor(v, vmin, vmax, isDivergent)}"></span>`;
  }
  const fmt = (v) => (v >= 0 ? "+" : "") + v.toFixed(2);
  const mid  = isDivergent ? `<span>0 ${units}</span>` : "";
  el.innerHTML =
    `<div class="vrf-legend-bar">${bars}</div>
     <div class="vrf-legend-labels">
       <span>${fmt(vmin)} ${units}</span>${mid}<span>${fmt(vmax)} ${units}</span>
     </div>`;
}

function _updateMapLeadSel() {
  const sel = document.getElementById("lead-sel");
  if (!_data || !sel) return;
  const buckets = (_data.groupings || {})[_grp] || [];
  const cur = sel.value;
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

function _renderMap(scatter, varMeta) {
  document.getElementById("map-card").style.display = "";
  _initMap();
  setTimeout(() => _map.invalidateSize(), 50);

  if (_domainLayer) { _map.removeLayer(_domainLayer); _domainLayer = null; }
  const domain = _data.domain || [];
  if (domain.length > 3) {
    _domainLayer = L.polygon(domain, {
      color: "#0b6b8a", weight: 2, fill: false, dashArray: "8 5", opacity: 0.9,
    }).addTo(_map);
  }

  if (_dotLayer) { _map.removeLayer(_dotLayer); _dotLayer = null; }
  document.getElementById("map-legend").innerHTML = "";
  document.getElementById("map-hint").textContent = "";

  const lats = (scatter || {}).lat || [];
  if (!lats.length || lats.every((v) => v == null)) {
    document.getElementById("map-hint").textContent = "Location data not available.";
    return;
  }

  const obs   = scatter.obs   || [];
  const model = scatter.model || [];
  const leads = scatter.lead  || [];
  const lons  = scatter.lon   || [];
  const isDivergent = _mapMetric === "bias";
  const units = varMeta.units || "";

  const buckets = (_data.groupings || {})[_grp] || [];
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
    const e = locAgg.get(key);
    e.sum += p.v; e.n++;
  }
  const pts = [...locAgg.values()].map((e) => ({ lat: e.lat, lon: e.lon, v: e.sum / e.n, n: e.n }));
  const vals = pts.map((p) => p.v);

  let vmin, vmax;
  if (isDivergent) {
    if (_var === "air_temp" || _var === "sea_surface_temp") {
      vmin = -5; vmax = 5;
    } else {
      let absmax = 0; for (const v of vals) { const av = Math.abs(v); if (av > absmax) absmax = av; }
      vmin = -absmax; vmax = absmax;
    }
  } else {
    vmin = 0; vmax = 0; for (const v of vals) if (v > vmax) vmax = v;
  }

  const markers = pts.map(({ lat, lon, v, n }) => {
    const color = _valToColor(v, vmin, vmax, isDivergent);
    const sign  = isDivergent && v >= 0 ? "+" : "";
    return L.circleMarker([lat, lon], {
      radius: 5, color: "rgba(0,0,0,0.25)", weight: 0.5,
      fillColor: color, fillOpacity: 0.85,
    }).bindTooltip(
      `${varMeta.label || _var}: ${sign}${v.toFixed(2)} ${units}<br>n\u202a=\u202a${n} pair${n !== 1 ? "s" : ""}`
    );
  });
  _dotLayer = L.layerGroup(markers).addTo(_map);
  document.getElementById("map-hint").textContent =
    `${pts.length} unique location${pts.length !== 1 ? "s" : ""} (${rawPts.length} pairs)`;
  _renderLegend(vmin, vmax, isDivergent, units);
}

// ── Bootstrap ──────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);
