/* ── SvalMIZ-26 Campaign Ensemble Analysis ────────────────────────────────────
 *
 * Loads all 18 SvalMIZ-26 buoy CSVs and computes ensemble statistics:
 *   • Air temperature  (1 m above surface, "air" position in thermistor string)
 *   • Skin temperature (infrared, measured at snow surface)
 *   • Upward conductive heat flux through sea ice
 *
 * Flux method (Fourier's law):
 *   F = k_ice × dT/dz   [W m⁻²]   positive = upward (ocean → atmosphere)
 *
 *   dT/dz is estimated by least-squares linear regression through the in-ice
 *   thermistor sensors at z = 0.00, 0.12, 0.24, 0.36, 0.48 m (z = 0 is the
 *   ice surface, i.e. the sensor_ice2 reference depth from the NetCDF).
 *   Sensors at negative z (snow / air side) are excluded.
 *
 *   Physical constants used:
 *     k_ice      = 2.1   W m⁻¹ K⁻¹  (sea ice thermal conductivity)
 *     h_snow     = 0.10  m           (assumed snow layer on top of ice)
 *     h_ice_init = 0.50  m           (initial ice thickness, all buoys)
 *
 * Data files (served by Nginx, or locally via dev_serve.sh):
 *   {SVALMIZ_BASE}/{id}_ts.csv    — hourly GPS + air_temp + skin_temp
 *   {SVALMIZ_BASE}/{id}_temp.csv  — hourly thermistor profile (depth columns)
 */

"use strict";

// ── Physical / campaign constants ──────────────────────────────────────────
const K_ICE       = 2.1;    // W m⁻¹ K⁻¹  thermal conductivity of sea ice
const K_SNOW      = 0.31;   // W m⁻¹ K⁻¹  thermal conductivity of snow
const RHO_ICE     = 917;    // kg m⁻³  density of sea ice
const L_ICE       = 334000; // J kg⁻¹  latent heat of fusion
const T_FREEZE    = -1.8;   // °C  seawater freezing point
const H_ICE_INIT  = 0.50;   // m  initial ice thickness (campaign start, all buoys)
const H_SNOW      = 0.10;   // m  assumed snow layer depth (constant)
const GRAD_Z_MAX  = 0.48;   // m  deepest in-ice sensor to include in gradient fit
//                                (≈ initial ice bottom; 0.48 is the 5th sensor at
//                                 0.12 m spacing starting from 0.00 m)

// ── Surface sensible heat flux (bulk aerodynamic) constants ────────────────
const RHO_AIR     = 1.30;   // kg m⁻³  air density at -10°C
const CP_AIR      = 1005;   // J kg⁻¹ K⁻¹  specific heat capacity of air
const CH_BULK     = 1.5e-3; // dimensionless, bulk heat transfer coefficient (neutral)
const U_ASSUMED   = 5.0;    // m s⁻¹  assumed wind speed
// H = ρ × cp × CH × U × (Tskin − Tair)  positive = upward (surface → atm)

const SVALMIZ_IDS = [
  "2026_04_KVS_SvalMIZ_01", "2026_04_KVS_SvalMIZ_02", "2026_04_KVS_SvalMIZ_03",
  "2026_04_KVS_SvalMIZ_04", "2026_04_KVS_SvalMIZ_05", "2026_04_KVS_SvalMIZ_06",
  "2026_04_KVS_SvalMIZ_07", "2026_04_KVS_SvalMIZ_08", "2026_04_KVS_SvalMIZ_09",
  "2026_04_KVS_SvalMIZ_10", "2026_04_KVS_SvalMIZ_11", "2026_04_KVS_SvalMIZ_12",
  "2026_04_KVS_SvalMIZ_13", "2026_04_KVS_SvalMIZ_14", "2026_04_KVS_SvalMIZ_15",
  "2026_04_KVS_SvalMIZ_16", "2026_04_KVS_SvalMIZ_17", "2026_04_KVS_SvalMIZ_18",
];

// ── Maths helpers ──────────────────────────────────────────────────────────

/**
 * Least-squares linear regression slope (dY/dX) of (xs[i], ys[i]) pairs.
 * NaN / non-finite y values are silently skipped.
 * Returns NaN when fewer than 2 finite pairs are available.
 */
function _linSlope(xs, ys) {
  let n = 0, sx = 0, sy = 0, sxy = 0, sx2 = 0;
  for (let i = 0; i < xs.length; i++) {
    if (!isFinite(ys[i])) continue;
    n++; sx += xs[i]; sy += ys[i]; sxy += xs[i] * ys[i]; sx2 += xs[i] * xs[i];
  }
  if (n < 2) return NaN;
  const denom = n * sx2 - sx * sx;
  return Math.abs(denom) < 1e-12 ? NaN : (n * sxy - sx * sy) / denom;
}

/**
 * Compute upward conductive heat flux through sea ice [W m⁻²] from one
 * temperature-profile CSV row.
 *
 * A linear temperature gradient is fitted through the in-ice sensors
 * (z ∈ [0, GRAD_Z_MAX]) and multiplied by k_ice.
 *
 * @param {object} tempRow          — CSV row with depth columns (D0.00, D0.12, …)
 * @param {{depth:number,col:string}[]} iceCols — pre-filtered in-ice columns
 */
function _iceFlux(tempRow, iceCols) {
  const xs = [], ys = [];
  for (const { depth, col } of iceCols) {
    const t = parseFloat(tempRow[col]);
    if (isFinite(t)) { xs.push(depth); ys.push(t); }
  }
  const slope = _linSlope(xs, ys);   // dT/dz  [°C m⁻¹], typically > 0 (warmer at depth)
  return isFinite(slope) ? K_ICE * slope : NaN;  // W m⁻², positive = upward
}

/**
 * Population mean and sample standard deviation of an array of numbers.
 * Non-finite values are ignored.
 * Returns { mean, std, n } where mean/std are null if n = 0 / n < 2.
 */
function _stats(values) {
  const v = values.filter(isFinite);
  if (v.length === 0) return { mean: null, std: null, n: 0 };
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  if (v.length === 1) return { mean, std: null, n: 1 };
  const variance = v.reduce((a, b) => a + (b - mean) ** 2, 0) / (v.length - 1);
  return { mean, std: Math.sqrt(variance), n: v.length };
}

// ── Time-bin helpers ───────────────────────────────────────────────────────

/** "2026-04-15T14:32:00+00:00"  →  "2026-04-15T14"  (1-hour bin key) */
function _hourKey(isoStr) { return (isoStr || "").substring(0, 13); }

/** "2026-04-15T14"  →  "2026-04-15T14:00:00Z"  (Plotly-friendly datetime) */
function _keyToDate(key) { return key + ":00:00Z"; }

// ── Plotly fill-band helper ────────────────────────────────────────────────

/**
 * Returns three Plotly traces that together draw a mean line with a ±1σ
 * shaded band:
 *   [0] invisible lower bound  (mean − std)
 *   [1] upper bound + tonexty fill back to lower
 *   [2] mean line (the visible, named, hoverable trace)
 *
 * @param {string[]}         times      x-axis values
 * @param {(number|null)[]}  means
 * @param {(number|null)[]}  stds
 * @param {string}           name       legend / hover label
 * @param {string}           hexColor   e.g. "#e05c2e"
 * @param {string}           fillRgba   e.g. "rgba(224,92,46,0.18)"
 */
function _bandTraces(times, means, stds, name, hexColor, fillRgba) {
  const upper = means.map((m, i) =>
    m !== null && stds[i] !== null ? m + stds[i] : null);
  const lower = means.map((m, i) =>
    m !== null && stds[i] !== null ? m - stds[i] : null);
  return [
    // ① invisible lower bound
    {
      x: times, y: lower,
      mode: "lines", line: { width: 0, color: "transparent" },
      hoverinfo: "skip", showlegend: false,
    },
    // ② upper bound — filled down to the lower bound
    {
      x: times, y: upper,
      mode: "lines", line: { width: 0, color: "transparent" },
      fill: "tonexty", fillcolor: fillRgba,
      name: `\u00b11\u03c3 (${name})`, showlegend: true,
      hoverinfo: "skip",
    },
    // ③ mean line
    {
      x: times, y: means,
      mode: "lines", name,
      line: { color: hexColor, width: 2.2 },
      hovertemplate: `%{x|%Y-%m-%d %H:00 UTC}<br><b>${name}: %{y:.2f}</b><extra></extra>`,
    },
  ];
}

// ── Main analysis ──────────────────────────────────────────────────────────

async function loadAndAnalyze() {
  const statusEl   = document.getElementById("status");
  const tempNLabel = document.getElementById("temp-n-label");
  const fluxNLabel = document.getElementById("flux-n-label");
  const shfNLabel  = document.getElementById("shf-n-label");

  statusEl.textContent = `Loading ${SVALMIZ_IDS.length} SvalMIZ-26 buoys\u2026`;

  // ── 1. Fetch all _ts.csv and _temp.csv in parallel ───────────────────────
  const loadResults = await Promise.allSettled(
    SVALMIZ_IDS.map(async (id) => {
      const [tsRows, tempRows] = await Promise.all([
        _fetchCSV(`${SVALMIZ_BASE}/${id}_ts.csv`),
        _fetchCSV(`${SVALMIZ_BASE}/${id}_temp.csv`),
      ]);
      return { id, tsRows, tempRows };
    })
  );

  const buoys = loadResults
    .filter((r) => r.status === "fulfilled" && r.value.tsRows.length > 0)
    .map((r) => r.value);

  if (buoys.length === 0) {
    statusEl.textContent = "No SvalMIZ-26 data available.";
    return;
  }

  // ── 2. Identify in-ice depth columns from the first buoy with temp data ──
  //   Columns look like "D0.00", "D0.12", … (D + non-negative float)
  //   Sensors at negative depth (D-0.36, …) are snow/air side — excluded.
  let iceCols = [];
  for (const b of buoys) {
    if (b.tempRows.length === 0) continue;
    const hdr = Object.keys(b.tempRows[0]);
    const candidates = hdr
      .filter((k) => /^D\d+\.\d+$/.test(k))        // non-negative depth: D0.00, D0.12 …
      .map((col) => ({ col, depth: parseFloat(col.slice(1)) }))
      .filter(({ depth }) => depth <= GRAD_Z_MAX + 0.005)
      .sort((a, b) => a.depth - b.depth);
    if (candidates.length >= 2) { iceCols = candidates; break; }
  }

  // ── 3. Build hourly bins ─────────────────────────────────────────────────
  //   bins[hourKey] = { airTemps:[], skinTemps:[], fluxes:[] }
  //   Each buoy contributes AT MOST ONE value per hour — we keep the last
  //   row that falls within each 1-hour bin so the count never exceeds
  //   the number of buoys (18).
  const bins = {};

  for (const { tsRows, tempRows } of buoys) {
    // Index temp rows by hour key (last row wins within a bin)
    const tempByHour = {};
    for (const row of tempRows) {
      const k = _hourKey(row.time);
      if (k) tempByHour[k] = row;
    }

    // Deduplicate ts rows to one-per-hour (last row within each bin wins)
    const tsByHour = {};
    for (const row of tsRows) {
      const k = _hourKey(row.time);
      if (k) tsByHour[k] = row;
    }

    for (const [k, row] of Object.entries(tsByHour)) {
      if (!bins[k]) bins[k] = { airTemps: [], skinTemps: [], fluxes: [], shfs: [] };

      const at = parseFloat(row.air_temp);
      const st = parseFloat(row.skin_temp);
      if (isFinite(at)) bins[k].airTemps.push(at);
      if (isFinite(st)) bins[k].skinTemps.push(st);

      // Surface sensible heat flux (bulk aerodynamic approximation)
      // H = ρ × cp × CH × U × (Tskin − Tair)  [W m⁻², positive = upward]
      if (isFinite(at) && isFinite(st)) {
        const shf = RHO_AIR * CP_AIR * CH_BULK * U_ASSUMED * (st - at);
        bins[k].shfs.push(shf);
      }

      // Conductive flux — requires temp profile at the same hour
      if (iceCols.length >= 2) {
        const tRow = tempByHour[k];
        if (tRow) {
          const flux = _iceFlux(tRow, iceCols);
          if (isFinite(flux)) bins[k].fluxes.push(flux);
        }
      }
    }
  }

  // ── 4. Sort bins and build time-series arrays ────────────────────────────
  const keys = Object.keys(bins).sort();
  const times = keys.map(_keyToDate);

  const airMean = [], airStd = [];
  const skinMean = [], skinStd = [];
  const fluxMean = [], fluxStd = [], fluxCount = [];
  const shfMean = [], shfStd = [], shfCount = [];
  let maxN = 0, maxNShf = 0;

  for (const k of keys) {
    const b  = bins[k];
    const sa = _stats(b.airTemps);
    const ss = _stats(b.skinTemps);
    const sf = _stats(b.fluxes);
    const sh = _stats(b.shfs);

    airMean.push(sa.mean);   airStd.push(sa.std);
    skinMean.push(ss.mean);  skinStd.push(ss.std);
    fluxMean.push(sf.mean);  fluxStd.push(sf.std);
    fluxCount.push(sf.n);
    shfMean.push(sh.mean);   shfStd.push(sh.std);
    shfCount.push(sh.n);
    if (sf.n > maxN) maxN = sf.n;
    if (sh.n > maxNShf) maxNShf = sh.n;
  }

  // ── 5. Build Stefan law model from ensemble mean air temperature ──────────
  const stefanThickness = _stefanModel(times, airMean);

  // ── 6. Render plots ──────────────────────────────────────────────────────
  const nOk = buoys.length;
  tempNLabel.textContent = `${nOk} / ${SVALMIZ_IDS.length} buoys loaded`;
  fluxNLabel.textContent = `up to ${maxN} buoys per hour \u00b7 in-ice sensors z\u2009=\u20090.00\u2013${GRAD_Z_MAX.toFixed(2)}\u2009m \u00b7 k\u2090\u1d35\u2091\u2009=\u2009${K_ICE}\u2009W\u2009m\u207b\u00b9\u2009K\u207b\u00b9`;
  shfNLabel.textContent = `up to ${maxNShf} buoys per hour \u00b7 U\u2009=\u2009${U_ASSUMED}\u2009m\u2009s\u207b\u00b9 (assumed) \u00b7 C\u2095\u2009=\u2009${(CH_BULK * 1e3).toFixed(1)}\u00d710\u207b\u00b3`;

  // Reveal cards BEFORE rendering so Plotly can measure the true container width
  statusEl.style.display = "none";
  document.getElementById("method-card").style.display  = "";
  document.getElementById("temp-card").style.display    = "";
  document.getElementById("flux-card").style.display    = "";
  document.getElementById("shf-card").style.display     = "";
  document.getElementById("stefan-card").style.display  = "";

  // Use rAF to let the browser paint the revealed cards before Plotly measures them
  requestAnimationFrame(() => {
    _renderTempPlot(times, airMean, airStd, skinMean, skinStd, buoys.length);
    _renderFluxPlot(times, fluxMean, fluxStd, fluxCount, buoys.length, iceCols);
    _renderShfPlot(times, shfMean, shfStd, shfCount, buoys.length);
    _renderStefanPlot(times, stefanThickness, airMean);
  });
}

// ── Plot renderers ─────────────────────────────────────────────────────────

function _renderTempPlot(times, airMean, airStd, skinMean, skinStd, nBuoys) {
  const traces = [
    ..._bandTraces(times, airMean,  airStd,  "Air Temp (\u00b0C)",  "#e05c2e", "rgba(224,92,46,0.18)"),
    ..._bandTraces(times, skinMean, skinStd, "Skin Temp (\u00b0C)", "#8e44ad", "rgba(142,68,173,0.18)"),
  ];

  const layout = {
    margin: { t: 12, r: 50, b: 60, l: 68 },
    yaxis: {
      title: "Temperature (\u00b0C)",
      zeroline: true, zerolinecolor: "#888", zerolinewidth: 1,
      showgrid: true, gridcolor: "#eee",
    },
    xaxis: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    legend: { orientation: "h", y: -0.22, font: { size: 12 } },
    hovermode: "x unified",
    autosize: true,
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
  };

  Plotly.newPlot("temp-plot", traces, layout, { responsive: true, displaylogo: false });
}

function _renderFluxPlot(times, fluxMean, fluxStd, fluxCount, nBuoys, iceCols) {
  const traces = [
    ..._bandTraces(times, fluxMean, fluxStd,
      "Conductive flux (W\u2009m\u207b\u00b2)", "#0b6b8a", "rgba(11,107,138,0.18)"),
  ];

  // Add buoy count to hover for the mean line
  traces[2].customdata = fluxCount;
  traces[2].hovertemplate =
    "%{x|%Y-%m-%d %H:00 UTC}<br>" +
    "<b>Flux: %{y:.1f}\u2009W\u2009m\u207b\u00b2</b><br>" +
    "n\u2009=\u2009%{customdata} buoys<extra></extra>";

  const depthLabel = iceCols.length
    ? `z\u2009=\u2009${iceCols[0].depth.toFixed(2)}\u2013${iceCols[iceCols.length - 1].depth.toFixed(2)}\u2009m`
    : "";

  const layout = {
    margin: { t: 12, r: 110, b: 60, l: 80 },
    yaxis: {
      title: "Heat flux (W\u2009m\u207b\u00b2)",
      range: [-10, 30],
      zeroline: true, zerolinecolor: "#888", zerolinewidth: 1.5,
      showgrid: true, gridcolor: "#eee",
    },
    xaxis: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    // Coloured zones for upward (positive) and downward (negative) flux
    shapes: [
      {
        type: "rect", xref: "paper", yref: "y",
        x0: 0, x1: 1, y0: 0, y1: 30,
        fillcolor: "rgba(211,84,0,0.04)", line: { width: 0 }, layer: "below",
      },
      {
        type: "rect", xref: "paper", yref: "y",
        x0: 0, x1: 1, y0: -10, y1: 0,
        fillcolor: "rgba(41,128,185,0.04)", line: { width: 0 }, layer: "below",
      },
    ],
    annotations: [
      {
        xref: "paper", yref: "paper", x: 0.01, y: 0.97,
        xanchor: "left", yanchor: "top",
        text: `Linear T gradient \u00b7 ${depthLabel} \u00b7 k<sub>ice</sub>\u2009=\u2009${K_ICE}\u2009W\u2009m<sup>\u22121</sup>K<sup>\u22121</sup>`,
        font: { size: 9.5, color: "#777" }, showarrow: false,
        bgcolor: "rgba(255,255,255,0.75)",
      },
      // Upward label (right-hand side, upper half)
      {
        xref: "paper", yref: "y", x: 1.01, y: 15,
        xanchor: "left", yanchor: "middle",
        text: "\u2191 upward<br>(ocean\u2192atm)",
        font: { size: 9, color: "#d35400" }, showarrow: false,
      },
      // Downward label (right-hand side, lower half)
      {
        xref: "paper", yref: "y", x: 1.01, y: -5,
        xanchor: "left", yanchor: "middle",
        text: "\u2193 downward<br>(atm\u2192ocean)",
        font: { size: 9, color: "#2980b9" }, showarrow: false,
      },
    ],
    legend: { orientation: "h", y: -0.22, font: { size: 12 } },
    hovermode: "x unified",
    autosize: true,
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
  };

  Plotly.newPlot("flux-plot", traces, layout, { responsive: true, displaylogo: false });
}

// ── Surface sensible heat flux plot (bulk aerodynamic approximation) ──────

function _renderShfPlot(times, shfMean, shfStd, shfCount, nBuoys) {
  const traces = [
    ..._bandTraces(times, shfMean, shfStd,
      "Surface heat flux (W\u2009m\u207b\u00b2)", "#c0392b", "rgba(192,57,43,0.18)"),
  ];

  // Add buoy count to hover for the mean line
  traces[2].customdata = shfCount;
  traces[2].hovertemplate =
    "%{x|%Y-%m-%d %H:00 UTC}<br>" +
    "<b>H: %{y:.1f}\u2009W\u2009m\u207b\u00b2</b><br>" +
    "n\u2009=\u2009%{customdata} buoys<extra></extra>";

  const layout = {
    margin: { t: 12, r: 110, b: 60, l: 80 },
    yaxis: {
      title: "Heat flux (W\u2009m\u207b\u00b2)",
      range: [-50, 50],
      zeroline: true, zerolinecolor: "#888", zerolinewidth: 1.5,
      showgrid: true, gridcolor: "#eee",
    },
    xaxis: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    // Coloured zones for upward (positive) and downward (negative) flux
    shapes: [
      {
        type: "rect", xref: "paper", yref: "y",
        x0: 0, x1: 1, y0: 0, y1: 50,
        fillcolor: "rgba(211,84,0,0.04)", line: { width: 0 }, layer: "below",
      },
      {
        type: "rect", xref: "paper", yref: "y",
        x0: 0, x1: 1, y0: -50, y1: 0,
        fillcolor: "rgba(41,128,185,0.04)", line: { width: 0 }, layer: "below",
      },
    ],
    annotations: [
      {
        xref: "paper", yref: "paper", x: 0.01, y: 0.97,
        xanchor: "left", yanchor: "top",
        text: `Bulk aerodynamic \u00b7 H\u2009=\u2009\u03c1\u2009c<sub>p</sub>\u2009C<sub>H</sub>\u2009U\u2009(T<sub>skin</sub>\u2212T<sub>air</sub>) \u00b7 U\u2009=\u2009${U_ASSUMED}\u2009m\u2009s<sup>\u22121</sup> (assumed)`,
        font: { size: 9.5, color: "#777" }, showarrow: false,
        bgcolor: "rgba(255,255,255,0.75)",
      },
      // Upward label (right-hand side, upper half)
      {
        xref: "paper", yref: "y", x: 1.01, y: 25,
        xanchor: "left", yanchor: "middle",
        text: "\u2191 upward<br>(sfc\u2192atm)",
        font: { size: 9, color: "#d35400" }, showarrow: false,
      },
      // Downward label (right-hand side, lower half)
      {
        xref: "paper", yref: "y", x: 1.01, y: -25,
        xanchor: "left", yanchor: "middle",
        text: "\u2193 downward<br>(atm\u2192sfc)",
        font: { size: 9, color: "#2980b9" }, showarrow: false,
      },
    ],
    legend: { orientation: "h", y: -0.22, font: { size: 12 } },
    hovermode: "x unified",
    autosize: true,
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
  };

  Plotly.newPlot("shf-plot", traces, layout, { responsive: true, displaylogo: false });
}

// ── Stefan law sea-ice growth model ───────────────────────────────────────
/**
 * Forward-Euler integration of the modified Stefan law with snow cover:
 *
 *   dh/dt = max(T_freeze - T_air, 0) / (ρ_ice × L × (h/k_ice + h_snow/k_snow))
 *
 * Only ice growth is modelled (Stefan's law); melt is not included.
 *
 * @param {string[]}         times    — ISO date strings (hourly, UTC)
 * @param {(number|null)[]}  airMean  — ensemble mean air temperature [°C]
 * @returns {(number|null)[]}  ice thickness [m] at each time step
 */
function _stefanModel(times, airMean) {
  const dt = 3600; // seconds per step (hourly data)
  let h = H_ICE_INIT;
  const thickness = [];

  for (let i = 0; i < times.length; i++) {{
    const Ta = airMean[i];
    if (Ta === null || !isFinite(Ta)) {
      thickness.push(h); // carry forward last thickness
      continue;
    }
    const dT = T_FREEZE - Ta;          // °C, positive when freezing
    if (dT > 0) {
      // Ice growth rate [m s⁻¹]
      const R = h / K_ICE + H_SNOW / K_SNOW;  // thermal resistance [m² K W⁻¹]
      const dhdt = dT / (RHO_ICE * L_ICE * R);
      h = Math.max(0, h + dhdt * dt);
    }
    // No melt term — Stefan law is a growth model only
    thickness.push(h);
  }}
  return thickness;
}

function _renderStefanPlot(times, thickness, airMean) {
  // Shade periods where T_air > T_freeze (melting conditions, growth paused)
  const meltShapes = [];
  let meltStart = null;
  for (let i = 0; i < times.length; i++) {
    const Ta = airMean[i];
    const melting = Ta !== null && isFinite(Ta) && Ta > T_FREEZE;
    if (melting && meltStart === null) meltStart = times[i];
    if (!melting && meltStart !== null) {
      meltShapes.push({
        type: "rect", xref: "x", yref: "paper",
        x0: meltStart, x1: times[i - 1] || times[i],
        y0: 0, y1: 1,
        fillcolor: "rgba(231,76,60,0.08)", line: { width: 0 }, layer: "below",
      });
      meltStart = null;
    }
  }
  if (meltStart !== null) {
    meltShapes.push({
      type: "rect", xref: "x", yref: "paper",
      x0: meltStart, x1: times[times.length - 1],
      y0: 0, y1: 1,
      fillcolor: "rgba(231,76,60,0.08)", line: { width: 0 }, layer: "below",
    });
  }

  const traces = [
    // Stefan model ice thickness
    {
      x: times, y: thickness,
      mode: "lines", name: "Ice thickness (Stefan model, m)",
      line: { color: "#1a5c9e", width: 2.4 },
      hovertemplate: "%{x|%Y-%m-%d %H:00 UTC}<br><b>h\u2090\u1d35\u2091: %{y:.3f}\u2009m</b><extra></extra>",
    },
    // Initial thickness reference
    {
      x: [times[0], times[times.length - 1]], y: [H_ICE_INIT, H_ICE_INIT],
      mode: "lines", name: `Initial thickness (${H_ICE_INIT}\u2009m)`,
      line: { color: "#888", width: 1.2, dash: "dot" },
      hoverinfo: "skip",
    },
    // Snow layer reference
    {
      x: [times[0], times[times.length - 1]], y: [H_SNOW, H_SNOW],
      mode: "lines", name: `Snow depth (${H_SNOW}\u2009m, assumed constant)`,
      line: { color: "#c0764e", width: 1.2, dash: "dash" },
      hoverinfo: "skip",
    },
  ];

  const layout = {
    margin: { t: 12, r: 110, b: 60, l: 80 },
    yaxis: {
      title: "Thickness (m)",
      rangemode: "tozero",
      showgrid: true, gridcolor: "#eee",
    },
    xaxis: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    shapes: meltShapes,
    annotations: [
      {
        xref: "paper", yref: "paper", x: 0.01, y: 0.97,
        xanchor: "left", yanchor: "top",
        text: `Modified Stefan law \u00b7 h<sub>ice,0</sub>\u2009=\u2009${H_ICE_INIT}\u2009m \u00b7 h<sub>snow</sub>\u2009=\u2009${H_SNOW}\u2009m \u00b7 k<sub>snow</sub>\u2009=\u2009${K_SNOW}\u2009W\u2009m<sup>\u22121</sup>K<sup>\u22121</sup> \u00b7 T<sub>f</sub>\u2009=\u2009${T_FREEZE}\u2009\u00b0C \u00b7 red shading: T<sub>air</sub>\u2009>\u2009T<sub>f</sub> (growth paused)`,
        font: { size: 9.5, color: "#777" }, showarrow: false,
        bgcolor: "rgba(255,255,255,0.75)",
      },
    ],
    legend: { orientation: "h", y: -0.22, font: { size: 12 } },
    hovermode: "x unified",
    autosize: true,
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
  };

  Plotly.newPlot("stefan-plot", traces, layout, { responsive: true, displaylogo: false });
}

// ── Boot ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", loadAndAnalyze);

// Resize all plots when the window changes size
window.addEventListener("resize", () => {
  ["temp-plot", "flux-plot", "stefan-plot"].forEach((id) => {
    const el = document.getElementById(id);
    if (el && el.layout) Plotly.Plots.resize(el);
  });
});
