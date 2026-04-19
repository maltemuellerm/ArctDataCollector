const IS_LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:";
const SHIPS_BASE      = IS_LOCAL ? "data/ships"      : "http://148.230.70.161/data/ships";
const SIMBA_BASE      = IS_LOCAL ? "data/simba"      : "http://148.230.70.161/data/simba";
const THERMISTOR_BASE = IS_LOCAL ? "data/thermistor" : "http://148.230.70.161/data/thermistor";
const ARCTSUM_BASE    = IS_LOCAL ? "data/arctsum"    : "http://148.230.70.161/data/arctsum";
const SVALMIZ_BASE    = IS_LOCAL ? "data/svalmiz"    : "http://148.230.70.161/data/svalmiz";
const IABP_BASE       = IS_LOCAL ? "data/iabp"       : "http://148.230.70.161/data/iabp";

// Shared colour palette — one colour per item id.
// ArctSum buoys fall back to the campaign colour via TYPE_COLORS.
const ITEM_COLORS = {
  MBBJ7YM:      "#e05c2e",
  SXZPW9C:      "#2e8bc0",
  JKFA7QZ:      "#2dab6f",
  SMLQ:         "#9b59b6",
  "fb39a488":   "#f39c12",
  "759dbda3":   "#c0392b",
  "3YYQ":       "#1a6e3c",
  "2024T117":   "#27ae60",
  "2025T141":   "#16a085",
  "2025T142":   "#8e44ad",
};
const TYPE_COLORS = {
  ship: "#0b6b8a",
  simba: "#f39c12",
  thermistor: "#27ae60",
  arctsum: "#7d3ac1",
  svalmiz: "#c0764e",
  iabp: "#1a7a4a",
};
function itemColor(item) {
  return ITEM_COLORS[item.id] || TYPE_COLORS[item.type] || "#0b6b8a";
}

const SHIPS = [
  { type: "ship", name: "Le Commandant Charcot", id: "MBBJ7YM",
    latField: "Latitude (deg)", lonField: "Longitude (deg)", tsField: "date" },
  { type: "ship", name: "Tara Polar Station",    id: "SXZPW9C",
    latField: "Latitude (deg)", lonField: "Longitude (deg)", tsField: "date" },
  { type: "ship", name: "Polarstern",            id: "JKFA7QZ",
    latField: "Latitude (deg)", lonField: "Longitude (deg)", tsField: "date" },
  { type: "ship", name: "Oden",                  id: "SMLQ",
    latField: "Latitude (deg)", lonField: "Longitude (deg)", tsField: "date" },
  { type: "ship", name: "RV Kronprins Haakon",   id: "3YYQ",
    latField: "Latitude (deg)", lonField: "Longitude (deg)", tsField: "date" },
];

const BUOYS = [
  { type: "simba", name: "SIMBA buoy 2", id: "fb39a488",
    deploymentId: "fb39a488-4209-4fa1-8220-76a384960de5",
    latField: "latitude", lonField: "longitude", tsField: "time_stamp" },
  { type: "simba", name: "SIMBA buoy 3", id: "759dbda3",
    deploymentId: "759dbda3-f61f-4461-9cdd-cb717a49b45a",
    latField: "latitude", lonField: "longitude", tsField: "time_stamp" },
];

function parseCSV(text) {
  const lines = text.trim().split("\n");
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const values = line.split(",").map((v) => v.trim());
    const row = {};
    headers.forEach((h, i) => { row[h] = values[i] ?? ""; });
    return row;
  });
}

async function _fetchCSV(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
  return parseCSV(await resp.text());
}

async function loadAllShips() {
  const results = await Promise.allSettled(
    SHIPS.map(async (ship) => {
      const rows = await _fetchCSV(`${SHIPS_BASE}/${ship.id}.csv`);
      // sort chronologically (handler writes newest-first)
      rows.sort((a, b) => (a[ship.tsField] || "").localeCompare(b[ship.tsField] || ""));
      return { ...ship, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

async function loadAllBuoys() {
  const results = await Promise.allSettled(
    BUOYS.map(async (buoy) => {
      const rows = await _fetchCSV(`${SIMBA_BASE}/${buoy.deploymentId}.csv`);
      // handler already writes chronologically
      return { ...buoy, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const THERMISTORS = [
  { type: "thermistor", name: "Thermistor 2024T117", id: "2024T117",
    latField: "latitude (deg)", lonField: "longitude (deg)", tsField: "time" },
  { type: "thermistor", name: "Thermistor 2025T141", id: "2025T141",
    latField: "latitude (deg)", lonField: "longitude (deg)", tsField: "time" },
  { type: "thermistor", name: "Thermistor 2025T142", id: "2025T142",
    latField: "latitude (deg)", lonField: "longitude (deg)", tsField: "time" },
];

async function loadAllThermistors() {
  const results = await Promise.allSettled(
    THERMISTORS.map(async (buoy) => {
      const rows = await _fetchCSV(`${THERMISTOR_BASE}/${buoy.id}_ts.csv`);
      // TS file is already chronological
      return { ...buoy, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const ARCTSUM = [
  "2025_08_KVS_ArctSum_01", "2025_08_KVS_ArctSum_02", "2025_08_KVS_ArctSum_03",
  "2025_08_KVS_ArctSum_04", "2025_08_KVS_ArctSum_05", "2025_08_KVS_ArctSum_06",
  "2025_08_KVS_ArctSum_07", "2025_08_KVS_ArctSum_08", "2025_08_KVS_ArctSum_09",
  "2025_08_KVS_ArctSum_10", "2025_08_KVS_ArctSum_11", "2025_08_KVS_ArctSum_12",
  "2025_08_KVS_ArctSum_13", "2025_08_KVS_ArctSum_14", "2025_08_KVS_ArctSum_15",
  "2025_08_KVS_ArctSum_16", "2025_08_KVS_ArctSum_17", "2025_08_KVS_ArctSum_18",
  "2025_08_KVS_ArctSum_19",
].map((id) => ({
  type: "arctsum",
  name: id.replace("2025_08_KVS_", "").replace(/_/g, " "),
  id,
  latField: "latitude", lonField: "longitude", tsField: "time",
}));

async function loadAllArctsum() {
  const results = await Promise.allSettled(
    ARCTSUM.map(async (buoy) => {
      const rows = await _fetchCSV(`${ARCTSUM_BASE}/${buoy.id}_ts.csv`);
      return { ...buoy, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const SVALMIZ = [
  "2026_04_KVS_SvalMIZ_01", "2026_04_KVS_SvalMIZ_02", "2026_04_KVS_SvalMIZ_03",
  "2026_04_KVS_SvalMIZ_04", "2026_04_KVS_SvalMIZ_05", "2026_04_KVS_SvalMIZ_06",
  "2026_04_KVS_SvalMIZ_07", "2026_04_KVS_SvalMIZ_08", "2026_04_KVS_SvalMIZ_09",
  "2026_04_KVS_SvalMIZ_10", "2026_04_KVS_SvalMIZ_11", "2026_04_KVS_SvalMIZ_12",
  "2026_04_KVS_SvalMIZ_13", "2026_04_KVS_SvalMIZ_14", "2026_04_KVS_SvalMIZ_15",
  "2026_04_KVS_SvalMIZ_16", "2026_04_KVS_SvalMIZ_17", "2026_04_KVS_SvalMIZ_18",
].map((id) => ({
  type: "svalmiz",
  name: id.replace("2026_04_KVS_", "").replace(/_/g, " "),
  id,
  latField: "latitude", lonField: "longitude", tsField: "time",
  _tempBase: SVALMIZ_BASE,
}));

async function loadAllSvalMIZ() {
  const results = await Promise.allSettled(
    SVALMIZ.map(async (buoy) => {
      const rows = await _fetchCSV(`${SVALMIZ_BASE}/${buoy.id}_ts.csv`);
      return { ...buoy, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

async function loadAllIABP() {
  // Fetch dynamic index of tracked buoys, then load each CSV
  let index;
  try {
    const resp = await fetch(`${IABP_BASE}/_index.json`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    index = await resp.json();
  } catch (e) {
    console.warn("IABP index unavailable:", e.message);
    return [];
  }

  const results = await Promise.allSettled(
    index.map(async (meta) => {
      const rows = await _fetchCSV(`${IABP_BASE}/${meta.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return {
        type: "iabp",
        id:   meta.id,
        name: meta.name || meta.id,
        latField: "latitude",
        lonField: "longitude",
        tsField:  "time",
        has_bp:   meta.has_bp,
        has_ts:   meta.has_ts,
        has_ta:   meta.has_ta,
        owner:    meta.owner,
        campaign: meta.campaign,
        rows,
      };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}
