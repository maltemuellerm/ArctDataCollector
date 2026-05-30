/* ── Helpers ───────────────────────────────────────────── */

function fmtPos(row, item) {
  const lat = parseFloat(row[item.latField]);
  const lon = parseFloat(row[item.lonField]);
  if (isNaN(lat) || isNaN(lon)) return "\u2014";
  return `${Math.abs(lat).toFixed(2)}\u00b0${lat >= 0 ? "N" : "S"} ${Math.abs(lon).toFixed(2)}\u00b0${lon >= 0 ? "E" : "W"}`;
}

function fmtTs(row, item) {
  return (row[item.tsField] || "").replace("T", " ").replace("+00:00", "");
}

function fmtDate(iso) {
  return iso.slice(0, 10);
}

/* ── Filter rows to slider window ─────────────────────── */

function rowsInWindow(item, tStart, tEnd) {
  return item.rows.filter((r) => {
    const ts = r[item.tsField] || "";
    return ts >= tStart && ts <= tEnd;
  });
}

/* ── Is the item currently active? (data within last 48h) */
function isCurrentlyActive(item) {
  if (!item.rows.length) return false;
  const last = item.rows[item.rows.length - 1][item.tsField] || "";
  const age = Date.now() - new Date(last).getTime();
  return age < 48 * 3600 * 1000;
}

/* ── Build card ───────────────────────────────────────── */

function buildCard(item, tStart, tEnd) {
  const visible = rowsInWindow(item, tStart, tEnd);
  const row = visible.length ? visible[visible.length - 1] : item.rows[item.rows.length - 1];
  const color = itemColor(item);
  const card  = document.createElement("div");
  card.className   = "ship-card";
  card.dataset.id  = item.id;
  card.dataset.type = item.type;
  card.style.borderLeftColor = color;

  const tag = item.type === "ship"
    ? `<span class="obs-tag ship-tag">SHIP</span>`
    : item.type === "simba"
    ? `<span class="obs-tag simba-tag">SIMBA</span>`
    : item.type === "arctsum"
    ? `<span class="obs-tag arctsum-tag">ArctSum</span>`
    : item.type === "svalmiz"
    ? `<span class="obs-tag svalmiz-tag">SvalMIZ</span>`
    : item.type === "iabp"
    ? `<span class="obs-tag iabp-tag">IABP</span>`
    : item.type === "svalbard"
    ? `<span class="obs-tag svalbard-tag">SVLB</span>`
    : item.type === "north_norway"
    ? `<span class="obs-tag north-norway-tag">N-NO</span>`
    : item.type === "offshore"
    ? `<span class="obs-tag offshore-tag">OFFSH</span>`
    : item.type === "greenland"
    ? `<span class="obs-tag greenland-tag">GL</span>`
    : item.type === "canada"
    ? `<span class="obs-tag canada-tag">CA</span>`
    : item.type === "alaska"
    ? `<span class="obs-tag alaska-tag">AK</span>`
    : item.type === "russia"
    ? `<span class="obs-tag russia-tag">RU</span>`
    : item.type === "iceland"
    ? `<span class="obs-tag iceland-tag">IS</span>`
    : item.type === "finland"
    ? `<span class="obs-tag finland-tag">FI</span>`
    : item.type === "sweden"
    ? `<span class="obs-tag sweden-tag">SE</span>`
    : item.type === "norway_buoys"
    ? `<span class="obs-tag norway-buoys-tag">NO-B</span>`
    : `<span class="obs-tag thermistor-tag">BUOY</span>`;

  const dotClass = isCurrentlyActive(item) ? "green" : "grey";
  const dot = `<span class="data-dot ${dotClass}" title="${visible.length} obs in window"></span>`;

  let metrics = "";
  if (item.type === "ship") {
    const temp = row["air_temp"];
    const wind = row["wind_speed"];
    const pres = row["air_pressure"];
    if (temp) metrics += `<span>\uD83C\uDF21\uFE0F ${temp}\u00b0C</span>`;
    if (wind) metrics += `<span>\uD83D\uDCA8 ${wind} m/s</span>`;
    if (pres) metrics += `<span>&#8853; ${pres} hPa</span>`;
  } else if (item.type === "simba") {
    const temp = row["air_temp"];
    const pres = row["air_pressure"];
    const surf = row["surface_distance"];
    if (temp) metrics += `<span>\uD83C\uDF21\uFE0F ${temp}\u00b0C</span>`;
    if (pres) metrics += `<span>&#8853; ${pres} hPa</span>`;
    if (surf) metrics += `<span>\u2744\uFE0F surf ${surf} m</span>`;
  } else if (item.type === "thermistor") {
    const temp = row["air_temp"];
    const pres = row["air_pressure"];
    if (temp) metrics += `<span>\uD83C\uDF21\uFE0F ${parseFloat(temp).toFixed(2)}\u00b0C</span>`;
    if (pres) metrics += `<span>&#8853; ${parseFloat(pres).toFixed(1)} hPa</span>`;
  } else if (item.type === "arctsum" || item.type === "svalmiz") {
    const temp = row["air_temp"];
    const hs   = row["wave_height"];
    if (temp) metrics += `<span>\uD83C\uDF21\uFE0F ${parseFloat(temp).toFixed(2)}\u00b0C</span>`;
    if (hs)   metrics += `<span>\uD83C\uDF0A Hs ${parseFloat(hs).toFixed(2)} m</span>`;
  } else if (item.type === "iabp") {
    const ta  = row["air_temp"];
    const ts  = row["surface_temp"];
    const bp  = row["air_pressure"];
    if (ta)  metrics += `<span>\uD83C\uDF21\uFE0F ${parseFloat(ta).toFixed(1)}\u00b0C</span>`;
    if (ts)  metrics += `<span>\u2744\uFE0F Ts ${parseFloat(ts).toFixed(1)}\u00b0C</span>`;
    if (bp)  metrics += `<span>&#8853; ${parseFloat(bp).toFixed(1)} hPa</span>`;
  } else if (item.type === "svalbard" || item.type === "north_norway" || item.type === "offshore" || item.type === "greenland" || item.type === "canada" ||
             item.type === "alaska"   || item.type === "russia"  || item.type === "iceland" ||
             item.type === "finland"  || item.type === "sweden"  || item.type === "norway_buoys") {
    const temp = row["air_temp"];
    const wind = row["wind_speed"];
    const pres = row["air_pressure"];
    if (temp) metrics += `<span>\uD83C\uDF21\uFE0F ${temp}\u00b0C</span>`;
    if (wind) metrics += `<span>\uD83D\uDCA8 ${wind} m/s</span>`;
    if (pres) metrics += `<span>&#8853; ${pres} hPa</span>`;
  }

  card.innerHTML = `
    <div class="ship-name" style="color:${color}">${dot}${item.name} ${tag}</div>
    <div class="ship-pos">${fmtTs(row, item)} UTC<br>${fmtPos(row, item)}</div>
    <div class="ship-metrics">${metrics}</div>`;
  return card;
}

/* ── Select item ──────────────────────────────────────── */

let _currentTStart, _currentTEnd;

function selectItem(item) {
  document.querySelectorAll(".ship-card").forEach((c) => c.classList.remove("active"));
  const card = document.querySelector(`.ship-card[data-id="${item.id}"]`);
  if (card) card.classList.add("active");

  const visible = rowsInWindow(item, _currentTStart, _currentTEnd);
  const row = visible.length ? visible[visible.length - 1] : item.rows[item.rows.length - 1];
  document.getElementById("detail-title").textContent = item.name;
  document.getElementById("detail-meta").textContent =
    `${fmtTs(row, item)} UTC  \u2022  ${fmtPos(row, item)}  \u2022  ${visible.length} obs in window`;

  const detailSection = document.getElementById("detail-section");
  detailSection.style.display = "";
  detailSection.scrollIntoView({ behavior: "smooth", block: "start" });

  // Fade out the click hint on first selection
  const hint = document.getElementById("click-hint");
  if (hint) hint.classList.add("hidden");

  // Create a filtered copy of the item for the detail renderer
  const filtered = { ...item, rows: visible.length ? visible : item.rows };
  // Pass slider bounds so renderers can filter lazy-loaded temp data
  filtered._tStart = _currentTStart;
  filtered._tEnd   = _currentTEnd;
  // Keep reference to original item for caching temp CSVs
  filtered._orig = item;

  if (item.type === "ship")        renderShipDetail(filtered);
  else if (item.type === "simba")  renderBuoyDetail(filtered);
  else if (item.type === "arctsum" || item.type === "svalmiz") renderArctsumDetail(filtered);
  else if (item.type === "iabp")   renderIabpDetail(filtered);
  else if (item.type === "svalbard" || item.type === "north_norway" || item.type === "offshore" || item.type === "greenland" || item.type === "canada" ||
           item.type === "alaska"   || item.type === "russia"  || item.type === "iceland" ||
           item.type === "finland"  || item.type === "sweden"  || item.type === "norway_buoys") renderShipDetail(filtered);
  else                             renderThermistorDetail(filtered);
  _renderModelForecast(item, filtered);
}

/* ── Rebuild all cards ────────────────────────────────── */

const _BADGE_MAP = {
  "ship-cards":         "badge-ships",
  "buoy-cards":         "badge-simba",
  "thermistor-cards":   "badge-thermistor",
  "arctsum-cards":      "badge-arctsum",
  "svalmiz-cards":      "badge-svalmiz",
  "iabp-cards":         "badge-iabp",
  "svalbard-cards":     "badge-svalbard",
  "north-norway-cards": "badge-north-norway",
  "offshore-cards":     "badge-offshore",
  "greenland-cards":    "badge-greenland",
  "canada-cards":       "badge-canada",
  "alaska-cards":       "badge-alaska",
  "russia-cards":       "badge-russia",
  "iceland-cards":      "badge-iceland",
  "finland-cards":      "badge-finland",
  "sweden-cards":       "badge-sweden",
  "norway-buoys-cards": "badge-norway-buoys",
};


const _LAND_CARD_IDS = new Set([
  "svalbard-cards", "north-norway-cards", "greenland-cards", "canada-cards",
  "offshore-cards", "alaska-cards", "russia-cards", "iceland-cards",
  "finland-cards", "sweden-cards"
]);

function rebuildCards(groups, tStart, tEnd) {
  let landActive = 0, landTotal = 0;
  for (const [containerId, items] of groups) {
    const el = document.getElementById(containerId);
    el.innerHTML = "";
    items.forEach((item) => {
      const card = buildCard(item, tStart, tEnd);
      // Dim cards that have no data in the current window (but still show them)
      if (rowsInWindow(item, tStart, tEnd).length === 0) {
        card.style.opacity = "0.35";
        card.title = "No data in selected time window";
      }
      card.addEventListener("click", () => selectItem(item));
      el.appendChild(card);
    });
    // Update count badge: active / total
    const active = items.filter(i => rowsInWindow(i, tStart, tEnd).length > 0).length;
    const badgeEl = document.getElementById(_BADGE_MAP[containerId]);
    if (badgeEl) {
      badgeEl.textContent = items.length === active ? items.length : `${active} / ${items.length}`;
    }
    if (_LAND_CARD_IDS.has(containerId)) {
      landActive += active;
      landTotal  += items.length;
    }
  }
  const landBadge = document.getElementById("badge-land");
  if (landBadge) {
    landBadge.textContent = landTotal === landActive ? landTotal : `${landActive} / ${landTotal}`;
  }
}

/* ── NWP model forecast overlay ─────────────────────────── */

// Lightweight timeseries-only files (~5–7 MB each) used for the map explorer overlay.
// The full verification JSONs (50–60 MB) are only loaded by the verification pages.
const _VRF_URLS = {
  arome:   (IS_LOCAL ? "" : "http://148.230.70.161") + "/data/arome/timeseries.json",
  ifs:     (IS_LOCAL ? "" : "http://148.230.70.161") + "/data/ecmwf/timeseries_ifs.json",
  aifs:    (IS_LOCAL ? "" : "http://148.230.70.161") + "/data/ecmwf/timeseries_aifs.json",
  ifs_exp: (IS_LOCAL ? "" : "http://148.230.70.161") + "/data/ecmwf/timeseries_ifs_exp.json",
};
const _vrf = {};
let   _vrfLoadStarted = false;
let   _vrfLoadPromise  = null;

async function _loadVrfData() {
  if (_vrfLoadStarted) return;
  _vrfLoadStarted = true;
  _vrfLoadPromise = Promise.allSettled(Object.entries(_VRF_URLS).map(async ([key, url]) => {
    try {
      const resp = await fetch(url);
      if (resp.ok) _vrf[key] = await resp.json();
    } catch (e) { /* VRF unavailable – model overlays won't show */ }
  }));
  await _vrfLoadPromise;
}

const _VRF_MODEL_CFG = [
  { key: "arome",   label: "AROME",            color: "#2e5fa3" },
  { key: "ifs",     label: "IFS HRES",          color: "#c44b27" },
  { key: "aifs",   label: "AIFS",              color: "#2dab6f" },
  { key: "ifs_exp", label: "IFS experimental",  color: "#8b5cf6" },
];

async function _renderModelForecast(item, filtered) {
  // Create container once, inserted after #plot-container
  let container = document.getElementById("model-forecast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "model-forecast-container";
    document.getElementById("plot-container").after(container);
  }
  container.style.cssText = "display:none;border-top:1px solid #d0dde6;margin-top:.5rem";

  if (!_vrfLoadStarted) _loadVrfData();

  // Wait for all timeseries files to load (or up to 10 s if server is slow / unavailable).
  if (_vrfLoadPromise) await Promise.race([_vrfLoadPromise, new Promise(r => setTimeout(r, 10000))]);
  if (!Object.keys(_vrf).length) return;

  const source  = item.type === "ship" ? "ships" : item.type;
  const instrId = item.deploymentId || item.id;
  const tS10    = (filtered._tStart || "").slice(0, 10);
  const tE10    = (filtered._tEnd   || "").slice(0, 10);

  const traces = [];

  // Observation air_temp as grey reference dots
  const obsDates = filtered.rows.map(r => r[filtered.tsField]);
  const obsVals  = filtered.rows.map(r => { const v = parseFloat(r["air_temp"]); return isNaN(v) ? null : v; });
  if (obsVals.some(v => v !== null)) {
    traces.push({ x: obsDates, y: obsVals, name: "Obs",
      mode: "markers", marker: { color: "#555", size: 4, opacity: 0.65 } });
  }

  // One coloured line per model — 0–24 h stitched forecast
  for (const { key, label, color } of _VRF_MODEL_CFG) {
    const ts = _vrf[key] && _vrf[key].timeseries &&
               _vrf[key].timeseries[source] &&
               _vrf[key].timeseries[source].air_temp &&
               _vrf[key].timeseries[source].air_temp[instrId];
    if (!ts) continue;
    const times = [], vals = [];
    for (let i = 0; i < ts.t.length; i++) {
      const d = ts.t[i].slice(0, 10);
      if ((!tS10 || d >= tS10) && (!tE10 || d <= tE10)) { times.push(ts.t[i]); vals.push(ts.m[i]); }
    }
    if (!times.length) continue;
    traces.push({ x: times, y: vals, name: label, mode: "lines",
      line: { color: color, width: 1.8 } });
  }

  if (traces.length < 1) return;  // nothing to show
  const hasModels = traces.length >= 2;

  container.style.cssText = "border-top:1px solid #d0dde6;margin-top:.5rem";
  const titleText = hasModels
    ? "Air temperature \u2014 model forecast (0\u201324 h, stitched)"
    : "Air temperature \u2014 observations (no model data yet)";
  Plotly.newPlot(container, traces, {
    title: { text: titleText,
             font: { size: 12 }, x: 0.02, xanchor: "left" },
    xaxis: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    yaxis: { title: "Air temp (\u00b0C)", showgrid: true, gridcolor: "#eee", zeroline: false },
    legend: { orientation: "h", y: -0.3, font: { size: 11 } },
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    margin: { t: 35, r: 20, b: 85, l: 65 },
    height: 270,
    hovermode: "x unified",
  }, { responsive: true, displaylogo: false });
}

/* ── Init ─────────────────────────────────────────────── */

async function init() {
  const statusEl   = document.getElementById("status");
  const mapSection = document.getElementById("map-section");

  let ships, buoys, thermistors, arctsum, svalmiz, iabp, svalbard, northNorway, offshore, greenland, canada,
      alaska, russia, iceland, finland, sweden, norwayBuoys;
  try {
    [ships, buoys, thermistors, arctsum, svalmiz, iabp, svalbard, northNorway, offshore, greenland, canada,
     alaska, russia, iceland, finland, sweden, norwayBuoys] = await Promise.all([
      loadAllShips(), loadAllBuoys(), loadAllThermistors(), loadAllArctsum(), loadAllSvalMIZ(), loadAllIABP(),
      loadAllSvalbard(), loadAllNorthNorway(), loadAllOffshore(), loadAllGreenland(), loadAllCanada(),
      loadAllAlaska(), loadAllRussia(), loadAllIceland(), loadAllFinland(), loadAllSweden(), loadAllNorwayBuoys()
    ]);
  } catch (err) {
    statusEl.textContent = "Failed to load data: " + err.message;
    return;
  }
  const allItems = [...ships, ...buoys, ...thermistors, ...arctsum, ...svalmiz, ...iabp, ...svalbard, ...northNorway, ...offshore, ...greenland, ...canada,
                   ...alaska, ...russia, ...iceland, ...finland, ...sweden, ...norwayBuoys];
  if (!allItems.length) { statusEl.textContent = "No data available."; return; }
  statusEl.style.display = "none";
  _loadVrfData();  // pre-load verification data in background

  // ── Compute global time extent (all items) ─────────────────────────────
  let globalMin = "9999", globalMax = "0000";
  allItems.forEach((item) => {
    item.rows.forEach((r) => {
      const ts = r[item.tsField] || "";
      if (ts && ts < globalMin) globalMin = ts;
      if (ts && ts > globalMax) globalMax = ts;
    });
  });

  // Build a daily tick array for the slider
  const dMin = new Date(globalMin);
  const dMax = new Date(globalMax);
  dMin.setUTCHours(0,0,0,0);
  dMax.setUTCHours(23,59,59,999);
  const days = [];
  for (let d = new Date(dMin); d <= dMax; d.setUTCDate(d.getUTCDate() + 1)) {
    days.push(d.toISOString());
  }
  if (days.length < 2) days.push(dMax.toISOString());

  const sliderLo = document.getElementById("slider-lo");
  const sliderHi = document.getElementById("slider-hi");
  const startLabel = document.getElementById("slider-start-label");
  const rangeLabel = document.getElementById("slider-range-label");
  const endLabel   = document.getElementById("slider-end-label");

  sliderLo.max = sliderHi.max = days.length - 1;
  sliderHi.value = days.length - 1;
  sliderLo.value = Math.max(0, days.length - 15);  // default: last 14 days

  const cardGroups = [
    ["ship-cards",         ships],
    ["arctsum-cards",      arctsum],
    ["svalmiz-cards",      svalmiz],
    ["iabp-cards",         iabp],
    ["buoy-cards",         buoys],
    ["thermistor-cards",   thermistors],
    ["svalbard-cards",     svalbard],
    ["north-norway-cards", northNorway],
    ["greenland-cards",    greenland],
    ["canada-cards",       canada],
    ["offshore-cards",     offshore],
    ["alaska-cards",       alaska],
    ["russia-cards",       russia],
    ["iceland-cards",      iceland],
    ["finland-cards",      finland],
    ["sweden-cards",       sweden],
    ["norway-buoys-cards", norwayBuoys],
  ];

  function onSliderChange() {
    let lo = parseInt(sliderLo.value);
    let hi = parseInt(sliderHi.value);
    if (lo > hi) { lo = hi; sliderLo.value = lo; }

    const tStart = days[lo];
    const tEnd   = days[hi];
    _currentTStart = tStart;
    _currentTEnd   = tEnd;

    startLabel.textContent = fmtDate(tStart);
    endLabel.textContent   = fmtDate(tEnd);
    const spanDays = Math.round((new Date(tEnd) - new Date(tStart)) / 86400000);
    rangeLabel.textContent = `${spanDays} day${spanDays !== 1 ? "s" : ""}`;

    renderMap(allItems, tStart, tEnd, selectItem);
    rebuildCards(cardGroups, tStart, tEnd);
  }

  sliderLo.addEventListener("input", onSliderChange);
  sliderHi.addEventListener("input", onSliderChange);

  // ── Accordion toggles ──────────────────────────────────
  document.querySelectorAll(".section-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      btn.closest(".section-group").classList.toggle("collapsed");
    });
  });
  document.querySelectorAll(".obs-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const grp = btn.closest(".obs-group");
      grp.classList.toggle("collapsed");
    });
  });

  mapSection.style.display = "";
  _currentTStart = days[0];
  _currentTEnd   = days[days.length - 1];
  onSliderChange();

}

init();
