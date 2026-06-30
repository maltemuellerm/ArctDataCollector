const IS_LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:";
// When served via the OpenMetBuoy reverse proxy (/arct-data/), route data
// fetches back through the same origin so the browser never contacts the VPS directly.
const IS_OMB   = location.hostname.includes("openmetbuoy-arctic.com");

function _base(path) {
  if (IS_LOCAL) return path;
  if (IS_OMB)   return "/arct-data/" + path;
  return "http://148.230.70.161/" + path;
}

const SHIPS_BASE        = _base("data/ships");
const SIMBA_BASE        = _base("data/simba");
const THERMISTOR_BASE   = _base("data/thermistor");
const ARCTSUM_BASE      = _base("data/arctsum");
const SVALMIZ_BASE      = _base("data/svalmiz");
const IABP_BASE         = _base("data/iabp");
const SVALBARD_BASE     = _base("data/svalbard");
const NORTH_NORWAY_BASE = _base("data/north_norway");
const OFFSHORE_BASE     = _base("data/offshore");
const GREENLAND_BASE    = _base("data/greenland");
const CANADA_BASE       = _base("data/canada");
const ALASKA_BASE       = _base("data/alaska");
const RUSSIA_BASE       = _base("data/russia");
const ICELAND_BASE      = _base("data/iceland");
const FINLAND_BASE      = _base("data/finland");
const SWEDEN_BASE       = _base("data/sweden");
const NORWAY_BUOYS_BASE = _base("data/norway_buoys");

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
  svalbard: "#0b3e75",
  north_norway: "#7a1515",
  offshore: "#5c3d00",
  greenland: "#1a5c38",
  canada:    "#c41230",
  alaska:       "#b35c00",
  russia:       "#8b0000",
  iceland:      "#1a3f7a",
  finland:      "#003580",
  sweden:       "#8a6900",
  norway_buoys: "#5b1fa3",
};
function itemColor(item) {
  return ITEM_COLORS[item.id] || TYPE_COLORS[item.type] || "#0b6b8a";
}

const SHIPS = [
  { type: "ship", name: "Le Commandant Charcot", id: "MBBJ7YM",
    latField: "latitude", lonField: "longitude", tsField: "time" },
  { type: "ship", name: "Tara Polar Station",    id: "SXZPW9C",
    latField: "latitude", lonField: "longitude", tsField: "time" },
  { type: "ship", name: "Polarstern",            id: "JKFA7QZ",
    latField: "latitude", lonField: "longitude", tsField: "time" },
  { type: "ship", name: "Oden",                  id: "SMLQ",
    latField: "latitude", lonField: "longitude", tsField: "time" },
  { type: "ship", name: "RV Kronprins Haakon",   id: "3YYQ",
    latField: "latitude", lonField: "longitude", tsField: "time" },
];

const BUOYS = [
  { type: "simba", name: "SIMBA buoy 2", id: "fb39a488",
    deploymentId: "fb39a488-4209-4fa1-8220-76a384960de5",
    latField: "latitude", lonField: "longitude", tsField: "time" },
  { type: "simba", name: "SIMBA buoy 3", id: "759dbda3",
    deploymentId: "759dbda3-f61f-4461-9cdd-cb717a49b45a",
    latField: "latitude", lonField: "longitude", tsField: "time" },
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
    latField: "latitude", lonField: "longitude", tsField: "time" },
  { type: "thermistor", name: "Thermistor 2025T141", id: "2025T141",
    latField: "latitude", lonField: "longitude", tsField: "time" },
  { type: "thermistor", name: "Thermistor 2025T142", id: "2025T142",
    latField: "latitude", lonField: "longitude", tsField: "time" },
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

const SVALBARD_STATIONS = [
  { type: "svalbard", name: "Karl XII-\u00F8ya",     id: "SN99935", latitude: 80.652, longitude:  25.005 },
  { type: "svalbard", name: "Verlegenhuken",          id: "SN99927", latitude: 80.055, longitude:  16.243 },
  { type: "svalbard", name: "Ny-\u00C5lesund",        id: "SN99910", latitude: 78.922, longitude:  11.932 },
  { type: "svalbard", name: "Svalbard Lufthavn",      id: "SN99840", latitude: 78.245, longitude:  15.502 },
  { type: "svalbard", name: "Adventdalen",            id: "SN99870", latitude: 78.202, longitude:  15.831 },
  { type: "svalbard", name: "Isfjord Radio",          id: "SN99790", latitude: 78.062, longitude:  13.619 },
  { type: "svalbard", name: "Hornsund",               id: "SN99754", latitude: 77.000, longitude:  15.535 },
  { type: "svalbard", name: "Hopen",                  id: "SN99720", latitude: 76.510, longitude:  25.013 },
  { type: "svalbard", name: "Bj\u00F8rn\u00F8ya",    id: "SN99710", latitude: 74.504, longitude:  18.998 },
  { type: "svalbard", name: "Jan Mayen",              id: "SN99950", latitude: 70.939, longitude:  -8.669 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllSvalbard() {
  const results = await Promise.allSettled(
    SVALBARD_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${SVALBARD_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const NORTH_NORWAY_STATIONS = [
  { type: "north_norway", name: "Nordkapp E69",              id: "SN94640", latitude: 71.157, longitude: 25.779 },
  { type: "north_norway", name: "Fruholmen Fyr",             id: "SN94500", latitude: 71.094, longitude: 23.984 },
  { type: "north_norway", name: "Slettnes Fyr",              id: "SN96400", latitude: 71.089, longitude: 28.217 },
  { type: "north_norway", name: "Mehamn Lufthavn",           id: "SN96310", latitude: 71.033, longitude: 27.830 },
  { type: "north_norway", name: "Honningsv\u00E5g Lufthavn", id: "SN94680", latitude: 71.010, longitude: 25.978 },
  { type: "north_norway", name: "Berlev\u00E5g Lufthavn",    id: "SN98090", latitude: 70.873, longitude: 29.042 },
  { type: "north_norway", name: "Makkaur Fyr",               id: "SN98400", latitude: 70.706, longitude: 30.070 },
  { type: "north_norway", name: "Hammerfest Lufthavn",       id: "SN94280", latitude: 70.681, longitude: 23.677 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllNorthNorway() {
  const results = await Promise.allSettled(
    NORTH_NORWAY_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${NORTH_NORWAY_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const GREENLAND_STATIONS = [
  { type: "greenland", name: "Station Nord",                  id: "04206", latitude: 81.600, longitude: -16.667 },
  { type: "greenland", name: "Pituffik (Thule AB)",           id: "04202", latitude: 76.531, longitude: -68.703 },
  { type: "greenland", name: "Danmarkshavn",                  id: "04320", latitude: 76.767, longitude: -18.667 },
  { type: "greenland", name: "Nerlerit Inaat",                id: "04336", latitude: 70.740, longitude: -22.650 },
  { type: "greenland", name: "Ittoqqortoormiit",              id: "04339", latitude: 70.485, longitude: -21.952 },
  { type: "greenland", name: "Ilulissat",                    id: "04221", latitude: 69.230, longitude: -51.060 },
  { type: "greenland", name: "Aasiaat",                      id: "04220", latitude: 68.700, longitude: -52.783 },
  { type: "greenland", name: "Kangerlussuaq",                id: "04231", latitude: 67.013, longitude: -50.706 },
  { type: "greenland", name: "Tasiilaq",                     id: "04360", latitude: 65.612, longitude: -37.636 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllGreenland() {
  const results = await Promise.allSettled(
    GREENLAND_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${GREENLAND_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const CANADA_STATIONS = [
  { type: "canada", name: "Alert",         id: "71355", latitude: 82.4938, longitude:  -62.3522 },
  { type: "canada", name: "Svartevaeg",    id: "71872", latitude: 81.1612, longitude:  -91.8161 },
  { type: "canada", name: "Eureka",        id: "71613", latitude: 79.9892, longitude:  -85.9339 },
  { type: "canada", name: "Grise Fiord",   id: "71971", latitude: 76.4225, longitude:  -82.9012 },
  { type: "canada", name: "Resolute",      id: "71018", latitude: 74.7063, longitude:  -94.9676 },
  { type: "canada", name: "Arctic Bay",    id: "71592", latitude: 72.9928, longitude:  -85.0116 },
  { type: "canada", name: "Pond Inlet",    id: "71576", latitude: 72.6931, longitude:  -77.9574 },
  { type: "canada", name: "Sachs Harbour", id: "71467", latitude: 71.9916, longitude: -125.2431 },
  { type: "canada", name: "Clyde River",   id: "71358", latitude: 70.4840, longitude:  -68.5149 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllCanada() {
  const results = await Promise.allSettled(
    CANADA_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${CANADA_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const OFFSHORE_STATIONS = [
  { type: "offshore", name: "Wisting",                id: "SN20925", latitude: 73.500, longitude: 24.130 },
  { type: "offshore", name: "Hjelms\u00F8ybanken II", id: "SN20924", latitude: 72.502, longitude: 20.169 },
  { type: "offshore", name: "Hjelms\u00F8ybanken",   id: "SN20926", latitude: 72.490, longitude: 20.150 },
  { type: "offshore", name: "Johan Castberg",         id: "SN76909", latitude: 72.484, longitude: 20.234 },
  { type: "offshore", name: "Goliat FPSO",            id: "SN76956", latitude: 71.311, longitude: 22.250 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllOffshore() {
  const results = await Promise.allSettled(
    OFFSHORE_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${OFFSHORE_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const ALASKA_STATIONS = [
  { type: "alaska", name: "Utqia\u011Fvik (Barrow)", id: "PABR",  latitude:  71.2854, longitude: -156.7887 },
  { type: "alaska", name: "Prudhoe Bay / Deadhorse", id: "PAPR",  latitude:  70.1997, longitude: -148.4654 },
  { type: "alaska", name: "Wainwright",               id: "PAWI",  latitude:  70.6383, longitude: -159.9949 },
  { type: "alaska", name: "Point Lay",                id: "PPIZ",  latitude:  69.7328, longitude: -163.0050 },
  { type: "alaska", name: "Barter Island (Kaktovik)", id: "PABM",  latitude:  70.1342, longitude: -143.5778 },
  { type: "alaska", name: "Point Hope",               id: "PAPO",  latitude:  68.3481, longitude: -166.7992 },
  { type: "alaska", name: "Kotzebue",                 id: "PAOT",  latitude:  66.8846, longitude: -162.5989 },
  { type: "alaska", name: "Nome",                     id: "PAOM",  latitude:  64.5122, longitude: -165.4453 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllAlaska() {
  const results = await Promise.allSettled(
    ALASKA_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${ALASKA_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const RUSSIA_STATIONS = [
  { type: "russia", name: "Krenkel (Franz Josef Land)",  id: "20046099999", latitude:  80.617, longitude:  58.050 },
  { type: "russia", name: "Golomyanny",                  id: "20667099999", latitude:  79.550, longitude:  90.633 },
  { type: "russia", name: "Ostrov Vize",                 id: "20292099999", latitude:  79.500, longitude:  76.983 },
  { type: "russia", name: "Ostrov Kotelny",              id: "20674099999", latitude:  75.983, longitude: 137.867 },
  { type: "russia", name: "Mys Chelyuskin",              id: "20069099999", latitude:  77.717, longitude: 104.283 },
  { type: "russia", name: "Dikson",                      id: "23078099999", latitude:  73.500, longitude:  80.400 },
  { type: "russia", name: "Mys Shmidta",                 id: "25399099999", latitude:  68.900, longitude: -179.367 },
  { type: "russia", name: "Belushya Guba",               id: "22113099999", latitude:  71.550, longitude:  52.317 },
  { type: "russia", name: "Tiksi",                       id: "21432099999", latitude:  71.583, longitude: 128.917 },
  { type: "russia", name: "Wrangel Island",              id: "25034099999", latitude:  70.983, longitude: -178.617 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllRussia() {
  const results = await Promise.allSettled(
    RUSSIA_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${RUSSIA_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const ICELAND_STATIONS = [
  { type: "iceland", name: "Gr\u00EDmsey",        id: "3976", latitude: 66.544, longitude: -18.017 },
  { type: "iceland", name: "Raufarhöfn",           id: "4828", latitude: 66.459, longitude: -15.950 },
  { type: "iceland", name: "\u00D3lafsfj\u00F6r\u00F0ur", id: "3658", latitude: 66.073, longitude: -18.674 },
  { type: "iceland", name: "Siglfj\u00F6r\u00F0ur", id: "3752", latitude: 66.132, longitude: -18.918 },
  { type: "iceland", name: "Akureyri",             id: "422",  latitude: 65.686, longitude: -18.100 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllIceland() {
  const results = await Promise.allSettled(
    ICELAND_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${ICELAND_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const FINLAND_STATIONS = [
  { type: "finland", name: "Utsjoki",                    id: "101976", latitude: 69.908, longitude: 27.007 },
  { type: "finland", name: "Enonteki\u00F6 Kilpisj\u00E4rvi", id: "102016", latitude: 69.039, longitude: 20.814 },
  { type: "finland", name: "Inari Angeli",               id: "102026", latitude: 68.903, longitude: 25.736 },
  { type: "finland", name: "Inari Saarisek\u00E4",       id: "102006", latitude: 68.560, longitude: 27.517 },
  { type: "finland", name: "Enonteki\u00F6 N\u00E4kk\u00E4l\u00E4", id: "102019", latitude: 68.603, longitude: 23.576 },
  { type: "finland", name: "Soданkyl\u00E4",             id: "101932", latitude: 67.367, longitude: 26.633 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllFinland() {
  const results = await Promise.allSettled(
    FINLAND_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${FINLAND_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const SWEDEN_STATIONS = [
  { type: "sweden", name: "Naimakka A",    id: "191910", latitude: 68.676, longitude: 21.523 },
  { type: "sweden", name: "Karesuando A",  id: "192840", latitude: 68.442, longitude: 22.444 },
  { type: "sweden", name: "Katterjåkk A", id: "188850", latitude: 68.420, longitude: 18.168 },
  { type: "sweden", name: "Abisko Aut",    id: "188790", latitude: 68.354, longitude: 18.816 },
  { type: "sweden", name: "Tarfala A",     id: "178970", latitude: 67.912, longitude: 18.610 },
  { type: "sweden", name: "Esrange",       id: "181970", latitude: 67.891, longitude: 21.083 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllSweden() {
  const results = await Promise.allSettled(
    SWEDEN_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${SWEDEN_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

const NORWAY_BUOYS_STATIONS = [
  { type: "norway_buoys", name: "Hopen met buoy",               id: "SN99722", latitude: 76.510, longitude: 25.013 },
  { type: "norway_buoys", name: "Barents Sea buoy (Fugløya)",   id: "SN76931", latitude: 74.500, longitude: 19.000 },
  { type: "norway_buoys", name: "Norwegian Sea buoy W",         id: "SN66740", latitude: 70.100, longitude:  1.000 },
].map(s => ({ ...s, latField: "latitude", lonField: "longitude", tsField: "time" }));

async function loadAllNorwayBuoys() {
  const results = await Promise.allSettled(
    NORWAY_BUOYS_STATIONS.map(async (stn) => {
      const rows = await _fetchCSV(`${NORWAY_BUOYS_BASE}/${stn.id}.csv`);
      rows.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
      return { ...stn, rows };
    })
  );
  return results.filter((r) => r.status === "fulfilled").map((r) => r.value);
}

