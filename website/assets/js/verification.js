/* verification.js – unified NWP verification page (AROME / IFS / AIFS / IFS-exp)
 *
 * Loads four verification JSONs in parallel and renders:
 *   – Map with model toggle (AROME | IFS | AIFS | IFS exp)
 *   – Bias & MAE chart (all four models, 6 h buckets)
 *   – RMSE chart (all four models, 6 h buckets)
 *   – Scatter plot (per-model checkboxes)
 *   – Variogram (all four models)
 */

"use strict";

const IS_LOCAL = location.hostname === "localhost"
              || location.hostname === "127.0.0.1"
              || location.protocol === "file:";

const BASE = IS_LOCAL ? "" : "http://148.230.70.161";

const MODELS = [
  { key: "arome",   label: "AROME",            url: `${BASE}/data/arome/verification.json` },
  { key: "ifs",     label: "IFS HRES",          url: `${BASE}/data/ecmwf/verification_ifs.json` },
  { key: "aifs",   label: "AIFS",              url: `${BASE}/data/ecmwf/verification_aifs.json` },
  { key: "ifs_exp", label: "IFS experimental",  url: `${BASE}/data/ecmwf/verification_ifs_exp.json` },
];

// Line styles per model
const MODEL_STYLE = {
  arome:   { color: "#2e5fa3" },
  ifs:     { color: "#c44b27" },
  aifs:    { color: "#2dab6f" },
  ifs_exp: { color: "#8b5cf6" },
};

// ── Palette for scatter lead-time groups ──────────────────────────────────────
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

// ── Aggregate helpers for "All weather stations" option ────────────────────────
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
  for (const m of MODELS) {
    const d = _datasets[m.key];
    if (!d) continue;
    const _agg = _aggSources();
    if (_agg) {
      _agg.forEach((src) => Object.keys((d.stats || {})[src] || {}).forEach((v) => varSet.add(v)));
    } else {
      Object.keys((d.stats || {})[_source] || {}).forEach((v) => varSet.add(v));
    }
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
    _renderVariogram();
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

  // Scatter model checkboxes
  ["chk-arome","chk-ifs","chk-aifs","chk-ifs_exp"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => _renderScatter());
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
  _renderVariogram();
}

function _getBuckets(modelKey) {
  const d = _datasets[modelKey];
  if (!d) return null;
  const agg = _aggSources();
  if (!agg) return ((d.stats[_source] || {})[_var] || {})[_metricsGrp] || null;
  const allBkts = agg.map((src) => ((d.stats[src] || {})[_var] || {})[_metricsGrp]).filter(Boolean);
  return allBkts.length ? _mergeBuckets(allBkts) : null;
}

function _getScatter(modelKey) {
  const d = _datasets[modelKey];
  if (!d) return null;
  const agg = _aggSources();
  if (!agg) return (d.scatter[_source] || {})[_var] || null;
  const all = agg.map((src) => (d.scatter[src] || {})[_var]).filter(Boolean);
  return all.length ? _mergeScatter(all) : null;
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

  let vMin = Infinity, vMax = -Infinity;
  for (const v of allVals) { if (v < vMin) vMin = v; if (v > vMax) vMax = v; }
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

// ── Variogram ─────────────────────────────────────────────────────────────────
const _VARIO_WINDOWS = [
  { label: "Lead time 0\u201312 h",  key: "0-12h"  },
  { label: "Lead time 48\u201360 h", key: "48-60h" },
];

function _renderVariogram() {
  const card    = document.getElementById("variogram-card");
  if (_aggSources()) { card.style.display = "none"; return; }
  const varMeta = _varMeta();
  let anyData   = false;

  for (let w = 0; w < _VARIO_WINDOWS.length; w++) {
    const win    = _VARIO_WINDOWS[w];
    const plotEl = document.getElementById(`variogram-plot-${w}`);
    const traces = [];
    let obsAdded = false;

    for (const m of MODELS) {
      const d = _datasets[m.key];
      if (!d) continue;
      const vg = ((d.variogram || {})[_source] || {})[_var];
      if (!vg) continue;
      const wdata = vg[win.key];
      if (!wdata) continue;

      // Observation reference — drawn once from first available model
      if (!obsAdded && wdata.obs && wdata.obs.length) {
        traces.push({
          x: wdata.obs.map((p) => p.d),
          y: wdata.obs.map((p) => p.g),
          customdata: wdata.obs.map((p) => p.n),
          name: "Observations",
          mode: "lines+markers",
          line:   { color: "#444", width: 2.5, dash: "dash" },
          marker: { color: "#444", size: 5 },
          hovertemplate: "Obs<br>d=%{x:.0f} km, \u03b3=%{y:.4f}<br>n=%{customdata}<extra></extra>",
        });
        obsAdded = true;
        anyData  = true;
      }

      if (wdata.model && wdata.model.length) {
        const { color } = MODEL_STYLE[m.key];
        traces.push({
          x: wdata.model.map((p) => p.d),
          y: wdata.model.map((p) => p.g),
          customdata: wdata.model.map((p) => p.n),
          name: m.label,
          mode: "lines+markers",
          line:   { color, width: 2 },
          marker: { color, size: 5 },
          hovertemplate: `${m.label}<br>d=%{x:.0f} km, \u03b3=%{y:.4f}<br>n=%{customdata}<extra></extra>`,
        });
        anyData = true;
      }
    }

    if (!traces.length) { Plotly.purge(plotEl); continue; }

    const unitsSq = varMeta.units ? `${varMeta.units}\u00b2` : "";
    Plotly.newPlot(plotEl, traces, {
      title:  { text: win.label, font: { size: 13 }, x: 0.5, xanchor: "center" },
      xaxis:  { title: "Distance (km)", showgrid: true, gridcolor: "#eee" },
      yaxis:  { title: `Semivariance (${unitsSq})`,
                showgrid: true, gridcolor: "#eee", rangemode: "tozero" },
      legend: { orientation: "h", y: -0.30, font: { size: 11 } },
      plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
      hovermode: "x unified",
      margin: { t: 40, r: 20, b: 90, l: 72 }, height: 300,
    }, { responsive: true, displaylogo: false });
  }

  card.style.display = anyData ? "" : "none";
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

  // EPSG:3996 — Arctic polar stereographic (same as main map)
  const crs = new L.Proj.CRS(
    "EPSG:3996",
    "+proj=stere +lat_0=90 +lat_ts=75 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs +type=crs",
    {
      origin: [-3333793.82, 3368075.98],
      resolutions: [8192, 4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1],
      bounds: L.bounds([-3333793.82, -3368075.98], [3333793.82, 3368075.98]),
    }
  );

  _map = L.map("obs-map", {
    crs,
    center: [85, 30],
    zoom: 2,
    minZoom: 0,
    maxZoom: 7,
    zoomControl: true,
  });

  // GEBCO North Polar bathymetry WMS
  L.tileLayer.wms("https://wms.gebco.net/north-polar/mapserv?", {
    layers: "GEBCO_NORTH_POLAR_VIEW",
    format: "image/png",
    transparent: false,
    version: "1.3.0",
    crs: crs,
    noWrap: true,
    attribution: "Bathymetry &copy; GEBCO",
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

  const scatter  = _getScatter(_mapModel);
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
    else { let a = 0; for (const v of vals) { const av = Math.abs(v); if (av > a) a = av; } vmin = -a; vmax = a; }
  } else { vmin = 0; vmax = 0; for (const v of vals) if (v > vmax) vmax = v; }

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
