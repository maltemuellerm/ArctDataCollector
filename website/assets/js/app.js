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
    : `<span class="obs-tag thermistor-tag">BUOY</span>`;

  const dotClass = isCurrentlyActive(item) ? "green" : "grey";
  const dot = `<span class="data-dot ${dotClass}" title="${visible.length} obs in window"></span>`;

  let metrics = "";
  if (item.type === "ship") {
    const temp = row["Air temperature (\u00b0C)"];
    const wind = row["Wind speed (m/s)"];
    const pres = row["Sea level Pressure (hPa)"];
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
    const temp = row["air temperature (degC)"];
    const pres = row["barometric pressure (hPa)"];
    if (temp) metrics += `<span>\uD83C\uDF21\uFE0F ${parseFloat(temp).toFixed(2)}\u00b0C</span>`;
    if (pres) metrics += `<span>&#8853; ${parseFloat(pres).toFixed(1)} hPa</span>`;
  } else if (item.type === "arctsum") {
    const temp = row["air_temp_C"];
    const hs   = row["wave_height_m"];
    if (temp) metrics += `<span>\uD83C\uDF21\uFE0F ${parseFloat(temp).toFixed(2)}\u00b0C</span>`;
    if (hs)   metrics += `<span>\uD83C\uDF0A Hs ${parseFloat(hs).toFixed(2)} m</span>`;
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

  // Create a filtered copy of the item for the detail renderer
  const filtered = { ...item, rows: visible.length ? visible : item.rows };
  // Pass slider bounds so renderers can filter lazy-loaded temp data
  filtered._tStart = _currentTStart;
  filtered._tEnd   = _currentTEnd;
  // Keep reference to original item for caching temp CSVs
  filtered._orig = item;

  if (item.type === "ship")        renderShipDetail(filtered);
  else if (item.type === "simba")  renderBuoyDetail(filtered);
  else if (item.type === "arctsum") renderArctsumDetail(filtered);
  else                             renderThermistorDetail(filtered);
}

/* ── Rebuild all cards ────────────────────────────────── */

function rebuildCards(groups, tStart, tEnd) {
  for (const [containerId, items] of groups) {
    const el = document.getElementById(containerId);
    el.innerHTML = "";
    items.forEach((item) => {
      if (rowsInWindow(item, tStart, tEnd).length === 0) return; // hide if no data
      const card = buildCard(item, tStart, tEnd);
      card.addEventListener("click", () => selectItem(item));
      el.appendChild(card);
    });
  }
}

/* ── Init ─────────────────────────────────────────────── */

async function init() {
  const statusEl   = document.getElementById("status");
  const mapSection = document.getElementById("map-section");

  let ships, buoys, thermistors, arctsum;
  try {
    [ships, buoys, thermistors, arctsum] = await Promise.all([
      loadAllShips(), loadAllBuoys(), loadAllThermistors(), loadAllArctsum()
    ]);
  } catch (err) {
    statusEl.textContent = "Failed to load data: " + err.message;
    return;
  }

  const allItems = [...ships, ...buoys, ...thermistors, ...arctsum];
  if (!allItems.length) { statusEl.textContent = "No data available."; return; }
  statusEl.style.display = "none";

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
    ["ship-cards", ships],
    ["buoy-cards", buoys],
    ["thermistor-cards", thermistors],
    ["arctsum-cards", arctsum],
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

  mapSection.style.display = "";
  _currentTStart = days[0];
  _currentTEnd   = days[days.length - 1];
  onSliderChange();

  if (ships.length) selectItem(ships[0]);
}

init();
