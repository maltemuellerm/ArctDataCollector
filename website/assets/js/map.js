/* ── Leaflet polar-stereo Arctic map ──────────────────── */

let _map = null;
let _layerGroup = null;
let _currentOnSelect = null;
let _currentItems = null;

function _initMap() {
  if (_map) return;

  // EPSG:3996 — Arctic polar stereographic (same as openmetbuoy-arctic.com)
  const crs = new L.Proj.CRS(
    "EPSG:3996",
    "+proj=stere +lat_0=90 +lat_ts=75 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs +type=crs",
    {
      origin: [-3333793.82, 3368075.98],
      resolutions: [8192, 4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1],
      bounds: L.bounds([-3333793.82, -3368075.98], [3333793.82, 3368075.98]),
    }
  );

  _map = L.map("map-container", {
    crs,
    center: [90, 0],
    zoom: 0,
    minZoom: 0,
    maxZoom: 9,
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

  // Graticule – lat/lon lines every 5°
  _drawGraticule();

  _layerGroup = L.layerGroup().addTo(_map);
}

function _drawGraticule() {
  const grat = L.layerGroup();

  // Latitude circles every 5° from 60°N to 90°N
  for (let lat = 60; lat <= 90; lat += 5) {
    const pts = [];
    for (let lon = -180; lon <= 180; lon += 2) {
      pts.push([lat, lon]);
    }
    const line = L.polyline(pts, {
      color: "#888", weight: 0.6, opacity: 0.5, dashArray: "4,4", interactive: false,
    });
    grat.addLayer(line);

    // label
    if (lat < 90) {
      L.marker([lat, 30], {
        icon: L.divIcon({
          className: "graticule-label",
          html: `${lat}°`,
          iconSize: [30, 14],
          iconAnchor: [15, 7],
        }),
        interactive: false,
      }).addTo(grat);
    }
  }

  // Longitude lines every 30° from 60°N to pole
  for (let lon = -180; lon < 180; lon += 30) {
    const pts = [];
    for (let lat = 60; lat <= 90; lat += 1) {
      pts.push([lat, lon]);
    }
    const line = L.polyline(pts, {
      color: "#888", weight: 0.6, opacity: 0.5, dashArray: "4,4", interactive: false,
    });
    grat.addLayer(line);

    // label at 62°N
    L.marker([62, lon], {
      icon: L.divIcon({
        className: "graticule-label",
        html: `${lon}°`,
        iconSize: [36, 14],
        iconAnchor: [18, 7],
      }),
      interactive: false,
    }).addTo(grat);
  }

  grat.addTo(_map);
}

function renderMap(items, tStart, tEnd, onSelect) {
  _initMap();
  _currentOnSelect = onSelect;
  _currentItems = items;
  _layerGroup.clearLayers();

  items.forEach((item) => {
    const rows  = item.rows;
    const color = itemColor(item);
    const isShip = item.type === "ship";

    const coords = [];
    const times  = [];
    rows.forEach((r) => {
      const ts = r[item.tsField] || "";
      if (ts < tStart || ts > tEnd) return;
      const lat = parseFloat(r[item.latField]);
      const lon = parseFloat(r[item.lonField]);
      if (!isNaN(lat) && !isNaN(lon)) {
        coords.push([lat, lon]);
        times.push(ts);
      }
    });

    if (coords.length === 0) return;

    // Track line
    const line = L.polyline(coords, {
      color,
      weight: isShip ? 3 : 2,
      opacity: 0.7,
      dashArray: isShip ? null : "6,4",
    });
    line.on("click", () => onSelect(item));
    _layerGroup.addLayer(line);

    // Track dots (small, semi-transparent)
    coords.forEach((c, i) => {
      const dot = L.circleMarker(c, {
        radius: isShip ? 2 : 2.5,
        color: color,
        fillColor: color,
        fillOpacity: 0.25,
        weight: 0,
        interactive: false,
      });
      _layerGroup.addLayer(dot);
    });

    // Latest position — large marker with white border
    const last = coords[coords.length - 1];
    const latest = L.circleMarker(last, {
      radius: isShip ? 7 : 8,
      color: "#ffffff",
      weight: 2,
      fillColor: color,
      fillOpacity: 1,
    });
    latest.bindTooltip(
      `<b>${item.name}</b><br>${times[times.length - 1]}<br>${last[0].toFixed(2)}°N ${last[1].toFixed(2)}°E`,
      { direction: "top", offset: [0, -8] }
    );
    latest.on("click", () => onSelect(item));
    _layerGroup.addLayer(latest);
  });
}
