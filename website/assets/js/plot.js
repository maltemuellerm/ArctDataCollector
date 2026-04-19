function _num(rows, key) {
  return rows.map((r) => { const v = parseFloat(r[key]); return isNaN(v) ? null : v; });
}

function renderShipDetail(ship) {
  const rows  = ship.rows; // chronological
  const dates = rows.map((r) => r[ship.tsField]).filter(Boolean);

  const hasSolar = rows.some((r) => (r["solar_irradiance"] || "") !== "");

  const traces = [
    { x: dates, y: _num(rows, "air_temp"),
      name: "Air Temp (\u00b0C)", mode: "lines",
      line: { color: "#e05c2e", width: 1.8 }, xaxis: "x", yaxis: "y" },
    { x: dates, y: _num(rows, "sea_surface_temp"),
      name: "SST (\u00b0C)", mode: "lines",
      line: { color: "#2e8bc0", width: 1.8, dash: "dot" }, xaxis: "x", yaxis: "y" },
    { x: dates, y: _num(rows, "dew_point_temp"),
      name: "Dew point (\u00b0C)", mode: "lines",
      line: { color: "#8e6dbf", width: 1.4, dash: "dash" }, xaxis: "x", yaxis: "y" },
    { x: dates, y: _num(rows, "air_pressure"),
      name: "Pressure (hPa)", mode: "lines",
      line: { color: "#6a5acd", width: 1.8 }, xaxis: "x2", yaxis: "y2" },
    { x: dates, y: _num(rows, "wind_speed"),
      name: "Wind (m/s)", mode: "lines",
      line: { color: "#2dab6f", width: 1.8 }, xaxis: "x3", yaxis: "y3" },
    { x: dates, y: _num(rows, "humidity"),
      name: "Humidity (%)", mode: "lines",
      line: { color: "#e0a020", width: 1.8 }, xaxis: "x4", yaxis: "y4" },
  ];

  let layout;
  if (hasSolar) {
    traces.push({
      x: dates, y: _num(rows, "solar_irradiance"),
      name: "Solar irradiance (W/m\u00b2)", mode: "lines",
      line: { color: "#d4a017", width: 1.8 }, xaxis: "x5", yaxis: "y5",
    });
    layout = {
      xaxis:  { matches: "x5", showticklabels: false, showgrid: true, gridcolor: "#eee" },
      xaxis2: { matches: "x5", showticklabels: false, showgrid: true, gridcolor: "#eee" },
      xaxis3: { matches: "x5", showticklabels: false, showgrid: true, gridcolor: "#eee" },
      xaxis4: { matches: "x5", showticklabels: false, showgrid: true, gridcolor: "#eee" },
      xaxis5: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
      yaxis:  { title: "Temp (\u00b0C)",       domain: [0.84, 1.00], showgrid: true, gridcolor: "#eee", zeroline: false },
      yaxis2: { title: "Pressure (hPa)",        domain: [0.63, 0.79], showgrid: true, gridcolor: "#eee", zeroline: false },
      yaxis3: { title: "Wind (m/s)",             domain: [0.42, 0.58], showgrid: true, gridcolor: "#eee", zeroline: false },
      yaxis4: { title: "Humidity (%)",           domain: [0.21, 0.37], showgrid: true, gridcolor: "#eee", zeroline: false },
      yaxis5: { title: "Solar (W/m\u00b2)",      domain: [0.00, 0.16], showgrid: true, gridcolor: "#eee", zeroline: false },
      margin: { t: 15, r: 25, b: 55, l: 75 },
      legend: { orientation: "h", y: -0.14, font: { size: 12 } },
      hovermode: "x unified",
      plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
      height: 620,
    };
  } else {
    layout = {
      xaxis:  { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
      xaxis2: { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
      xaxis3: { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
      xaxis4: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
      yaxis:  { title: "Temp (\u00b0C)",    domain: [0.77, 1.00], showgrid: true, gridcolor: "#eee", zeroline: false },
      yaxis2: { title: "Pressure (hPa)", domain: [0.52, 0.73], showgrid: true, gridcolor: "#eee", zeroline: false },
      yaxis3: { title: "Wind (m/s)",     domain: [0.27, 0.48], showgrid: true, gridcolor: "#eee", zeroline: false },
      yaxis4: { title: "Humidity (%)",   domain: [0.00, 0.21], showgrid: true, gridcolor: "#eee", zeroline: false },
      margin: { t: 15, r: 25, b: 55, l: 75 },
      legend: { orientation: "h", y: -0.18, font: { size: 12 } },
      hovermode: "x unified",
      plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
      height: 520,
    };
  }

  Plotly.newPlot("plot-container", traces, layout, { responsive: true, displaylogo: false });
}

function renderBuoyDetail(buoy) {
  const rows  = buoy.rows; // chronological
  const dates = rows.map((r) => r[buoy.tsField]).filter(Boolean);

  // Detect DTC temperature profile columns (dtc_values_0 … dtc_values_N)
  const dtcCols = Object.keys(rows[0] || {})
    .filter((k) => /^dtc_values_\d+$/.test(k))
    .sort((a, b) => parseInt(a.split("_").pop()) - parseInt(b.split("_").pop()));

  // z[sensor_index][time_index] — shape: sensors × timestamps
  const z = dtcCols.map((col) => _num(rows, col));

  // SIMBA sensor chain: 2 cm spacing, sensor 0 at the top of the chain.
  const dtcDepthsCm = dtcCols.map((_, i) => i * 2);

  const DTC_COLORSCALE = [
    [0.0,  "#053061"], [0.25, "#2166ac"], [0.45, "#92c5de"],
    [0.5,  "#f7f7f7"],
    [0.55, "#fddbc7"], [0.75, "#d6604d"], [1.0,  "#67001f"],
  ];

  const traces = [
    // Panel 1 — DTC temperature profile heatmap
    {
      type: "heatmap",
      x: dates,
      y: dtcDepthsCm,
      z,
      colorscale: DTC_COLORSCALE,
      zmin: -40, zmax: 5,
      colorbar: { title: "\u00b0C", thickness: 14, len: 0.43, y: 0.78, yanchor: "bottom" },
      xaxis: "x", yaxis: "y",
      hovertemplate: "%{x}<br>Depth %{y} cm<br><b>%{z:.2f}\u00b0C</b><extra></extra>",
    },
    // Panel 2 — Air temp + water temp
    { x: dates, y: _num(rows, "air_temp"),   name: "Air Temp (\u00b0C)",   mode: "lines",
      line: { color: "#e05c2e", width: 1.8 }, xaxis: "x2", yaxis: "y2" },
    { x: dates, y: _num(rows, "water_temp"), name: "Water Temp (\u00b0C)", mode: "lines",
      line: { color: "#2e8bc0", width: 1.8, dash: "dot" }, xaxis: "x2", yaxis: "y2" },
    // Panel 3 — Air pressure
    { x: dates, y: _num(rows, "air_pressure"), name: "Pressure (hPa)", mode: "lines",
      line: { color: "#6a5acd", width: 1.8 }, xaxis: "x3", yaxis: "y3" },
    // Panel 4 — Surface & bottom distance
    { x: dates, y: _num(rows, "surface_distance"), name: "Surface dist (m)", mode: "lines",
      line: { color: "#2dab6f", width: 1.8 }, xaxis: "x4", yaxis: "y4" },
    { x: dates, y: _num(rows, "bottom_distance"),  name: "Bottom dist (m)",  mode: "lines",
      line: { color: "#f39c12", width: 1.8, dash: "dot" }, xaxis: "x4", yaxis: "y4" },
  ];

  const layout = {
    // Heatmap panel
    xaxis:  { matches: "x4", showticklabels: false, showgrid: false },
    yaxis:  { title: "Depth (cm)", domain: [0.55, 1.00], showgrid: false,
              autorange: "reversed" }, // depth 0 at top of chain
    // Time series panels
    xaxis2: { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
    xaxis3: { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
    xaxis4: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    yaxis2: { title: "Temp (\u00b0C)",    domain: [0.38, 0.50],
              zeroline: true, zerolinecolor: "#aaa", showgrid: true, gridcolor: "#eee" },
    yaxis3: { title: "Pressure (hPa)", domain: [0.21, 0.33], showgrid: true, gridcolor: "#eee", zeroline: false },
    yaxis4: { title: "Distance (m)",   domain: [0.00, 0.15], showgrid: true, gridcolor: "#eee", zeroline: false },
    margin: { t: 15, r: 90, b: 55, l: 75 },
    legend: { orientation: "h", y: -0.18, font: { size: 12 } },
    hovermode: "x unified",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    height: 680,
  };

  Plotly.newPlot("plot-container", traces, layout, { responsive: true, displaylogo: false });
}

async function renderThermistorDetail(buoy) {
  // Lazy-load the TEMP CSV (T1…T240 profile, 6-hourly)
  const orig = buoy._orig || buoy;
  if (!orig._allTempRows) {
    try {
      orig._allTempRows = await _fetchCSV(`${THERMISTOR_BASE}/${buoy.id}_temp.csv`);
    } catch (e) {
      orig._allTempRows = [];
    }
  }

  const tsRows   = buoy.rows;     // 2-hourly TS (lat, lon, air temp, pressure, tilt)
  // Filter temp rows to the same time window as tsRows
  const tS = buoy._tStart || "", tE = buoy._tEnd || "9999";
  const tempRows = orig._allTempRows.filter((r) => {
    const t = r["time"] || "";
    return t >= tS && t <= tE;
  });

  const tsDates   = tsRows.map((r) => r[buoy.tsField]).filter(Boolean);
  const tempDates = tempRows.map((r) => r["time"]).filter(Boolean);

  // Sensor columns: "T1 (degC)", "T2 (degC)", …
  const tCols = Object.keys(tempRows[0] || {})
    .filter((k) => /^T\d+ \(degC\)$/.test(k))
    .sort((a, b) => parseInt(a.match(/\d+/)[0]) - parseInt(b.match(/\d+/)[0]));

  // z[sensor_index][time_index]
  const z = tCols.map((col) => _num(tempRows, col));

  const THERM_COLORSCALE = [
    [0.0,  "#053061"], [0.25, "#2166ac"], [0.45, "#92c5de"],
    [0.5,  "#f7f7f7"],
    [0.55, "#fddbc7"], [0.75, "#d6604d"], [1.0,  "#67001f"],
  ];

  const traces = [
    // Panel 1 — Thermistor profile heatmap
    {
      type: "heatmap",
      x: tempDates,
      y: tCols.map((_, i) => i + 1),
      z,
      colorscale: THERM_COLORSCALE,
      zmin: -40, zmax: 0,
      colorbar: { title: "\u00b0C", thickness: 14, len: 0.43, y: 0.78, yanchor: "bottom" },
      xaxis: "x", yaxis: "y",
      hovertemplate: "%{x}<br>Sensor %{y}<br><b>%{z:.2f}\u00b0C</b><extra></extra>",
    },
    // Panel 2 — Air temperature
    { x: tsDates, y: _num(tsRows, "air_temp"),
      name: "Air Temp (\u00b0C)", mode: "lines",
      line: { color: "#e05c2e", width: 1.8 }, xaxis: "x2", yaxis: "y2" },
    // Panel 3 — Barometric pressure
    { x: tsDates, y: _num(tsRows, "air_pressure"),
      name: "Pressure (hPa)", mode: "lines",
      line: { color: "#6a5acd", width: 1.8 }, xaxis: "x3", yaxis: "y3" },
    // Panel 4 — Tilt
    { x: tsDates, y: _num(tsRows, "tilt"),
      name: "Tilt (\u00b0)", mode: "lines",
      line: { color: "#2dab6f", width: 1.8 }, xaxis: "x4", yaxis: "y4" },
  ];

  const layout = {
    xaxis:  { matches: "x4", showticklabels: false, showgrid: false },
    yaxis:  { title: "Sensor #", domain: [0.55, 1.00], showgrid: false,
              autorange: "reversed" },
    xaxis2: { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
    xaxis3: { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
    xaxis4: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    yaxis2: { title: "Temp (\u00b0C)",    domain: [0.38, 0.50],
              zeroline: true, zerolinecolor: "#aaa", showgrid: true, gridcolor: "#eee" },
    yaxis3: { title: "Pressure (hPa)", domain: [0.21, 0.33], showgrid: true, gridcolor: "#eee", zeroline: false },
    yaxis4: { title: "Tilt (\u00b0)",    domain: [0.00, 0.15], showgrid: true, gridcolor: "#eee", zeroline: false },
    margin: { t: 15, r: 90, b: 55, l: 75 },
    legend: { orientation: "h", y: -0.18, font: { size: 12 } },
    hovermode: "x unified",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    height: 680,
  };

  Plotly.newPlot("plot-container", traces, layout, { responsive: true, displaylogo: false });
}

async function renderArctsumDetail(buoy) {
  // Lazy-load the TEMP CSV (temperature string profile, hourly)
  const orig = buoy._orig || buoy;
  const tempBase = orig._tempBase || ARCTSUM_BASE;
  if (!orig._allTempRows) {
    try {
      orig._allTempRows = await _fetchCSV(`${tempBase}/${buoy.id}_temp.csv`);
    } catch (e) {
      orig._allTempRows = [];
    }
  }

  const tsRows   = buoy.rows;
  // Filter temp rows to the same time window as tsRows
  const tS = buoy._tStart || "", tE = buoy._tEnd || "9999";
  const tempRows = buoy._allTempRows.filter((r) => {
    const t = r["time"] || "";
    return t >= tS && t <= tE;
  });

  const tsDates   = tsRows.map((r) => r[buoy.tsField]).filter(Boolean);
  const tempDates = tempRows.map((r) => r["time"]).filter(Boolean);

  // Depth cols: "D-0.48", "D0.00", "D0.12", … sorted by numeric depth
  const dCols = Object.keys(tempRows[0] || {})
    .filter((k) => /^D-?\d+\.\d+$/.test(k))
    .sort((a, b) => parseFloat(a.slice(1)) - parseFloat(b.slice(1)));

  const z = dCols.map((col) => _num(tempRows, col));
  const yLabels = dCols.map((c) => parseFloat(c.slice(1)));

  const ARCTSUM_COLORSCALE = [
    [0.0,  "#053061"], [0.25, "#2166ac"], [0.45, "#92c5de"],
    [0.5,  "#f7f7f7"],
    [0.55, "#fddbc7"], [0.75, "#d6604d"], [1.0,  "#67001f"],
  ];

  const traces = [
    // Panel 1 — Temperature string heatmap (depth relative to ice surface)
    {
      type: "heatmap",
      x: tempDates,
      y: yLabels,
      z,
      colorscale: ARCTSUM_COLORSCALE,
      zmin: -25, zmax: 5,
      colorbar: { title: "\u00b0C", thickness: 14, len: 0.43, y: 0.78, yanchor: "bottom" },
      xaxis: "x", yaxis: "y",
      hovertemplate: "%{x}<br>Depth %{y:.2f} m<br><b>%{z:.2f}\u00b0C</b><extra></extra>",
    },
    // Panel 2 — Air temperature + skin temperature
    { x: tsDates, y: _num(tsRows, "air_temp"),
      name: "Air Temp (\u00b0C)", mode: "lines",
      line: { color: "#e05c2e", width: 1.8 }, xaxis: "x2", yaxis: "y2" },
    { x: tsDates, y: _num(tsRows, "skin_temp"),
      name: "Skin Temp (\u00b0C)", mode: "lines",
      line: { color: "#c0392b", width: 1.4, dash: "dot" }, xaxis: "x2", yaxis: "y2" },
    // Panel 3 — Significant wave height
    { x: tsDates, y: _num(tsRows, "wave_height"),
      name: "Wave Hs (m)", mode: "lines",
      line: { color: "#2e8bc0", width: 1.8 }, xaxis: "x3", yaxis: "y3" },
    // Panel 4 — Wave period
    { x: tsDates, y: _num(tsRows, "wave_period"),
      name: "T\u2080\u2082 (s)", mode: "lines",
      line: { color: "#6a5acd", width: 1.8 }, xaxis: "x4", yaxis: "y4" },
  ];

  const layout = {
    xaxis:  { matches: "x4", showticklabels: false, showgrid: false },
    yaxis:  { title: "Depth rel. ice (m)", domain: [0.55, 1.00], showgrid: false,
              autorange: "reversed" },
    xaxis2: { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
    xaxis3: { matches: "x4", showticklabels: false, showgrid: true, gridcolor: "#eee" },
    xaxis4: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    yaxis2: { title: "Temp (\u00b0C)",  domain: [0.38, 0.50],
              zeroline: true, zerolinecolor: "#aaa", showgrid: true, gridcolor: "#eee" },
    yaxis3: { title: "Hs (m)",        domain: [0.21, 0.33], showgrid: true, gridcolor: "#eee", zeroline: false },
    yaxis4: { title: "T\u2080\u2082 (s)", domain: [0.00, 0.15], showgrid: true, gridcolor: "#eee", zeroline: false },
    margin: { t: 15, r: 90, b: 55, l: 90 },
    legend: { orientation: "h", y: -0.18, font: { size: 12 } },
    hovermode: "x unified",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    height: 680,
  };

  Plotly.newPlot("plot-container", traces, layout, { responsive: true, displaylogo: false });
}

function renderIabpDetail(buoy) {
  const rows  = buoy.rows;
  const dates = rows.map((r) => r.time).filter(Boolean);

  const tempTraces = [];
  const bpTraces   = [];

  if (rows.some((r) => r.air_temp !== "")) {
    tempTraces.push({ x: dates, y: _num(rows, "air_temp"),
      name: "Air Temp (\u00b0C)", mode: "lines",
      line: { color: "#e05c2e", width: 1.8 }, xaxis: "x2", yaxis: "y2" });
  }
  if (rows.some((r) => r.surface_temp !== "")) {
    tempTraces.push({ x: dates, y: _num(rows, "surface_temp"),
      name: "Surface Temp (\u00b0C)", mode: "lines",
      line: { color: "#2e8bc0", width: 1.8, dash: "dot" }, xaxis: "x2", yaxis: "y2" });
  }
  if (rows.some((r) => r.air_pressure !== "")) {
    bpTraces.push({ x: dates, y: _num(rows, "air_pressure"),
      name: "Pressure (hPa)", mode: "lines",
      line: { color: "#6a5acd", width: 1.8 }, xaxis: "x", yaxis: "y" });
  }

  const traces = [...bpTraces, ...tempTraces];
  const hasBp   = bpTraces.length > 0;
  const hasTemp = tempTraces.length > 0;

  const layout = {
    xaxis:  { matches: "x2", showticklabels: !hasTemp, showgrid: true, gridcolor: "#eee",
              title: hasTemp ? "" : "Date (UTC)" },
    xaxis2: { title: "Date (UTC)", showgrid: true, gridcolor: "#eee" },
    yaxis:  { title: "Pressure (hPa)", domain: hasBp && hasTemp ? [0.55, 1.00] : [0.0, 1.0],
              showgrid: true, gridcolor: "#eee", zeroline: false },
    yaxis2: { title: "Temp (\u00b0C)",  domain: hasBp && hasTemp ? [0.00, 0.42] : [0.0, 1.0],
              showgrid: true, gridcolor: "#eee", zeroline: false },
    margin: { t: 15, r: 30, b: 55, l: 75 },
    legend: { orientation: "h", y: -0.22, font: { size: 12 } },
    hovermode: "x unified",
    plot_bgcolor: "#f8fbfc", paper_bgcolor: "#ffffff",
    height: hasBp && hasTemp ? 420 : 300,
  };

  Plotly.newPlot("plot-container", traces, layout, { responsive: true, displaylogo: false });
}
