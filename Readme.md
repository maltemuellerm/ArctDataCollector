# ArctDataCollector

An operational Arctic observation data collection and visualization platform. The system fetches meteorological and oceanographic data from multiple remote Arctic instruments — research ships, ice-tethered buoys, and thermistor chains — stores it as rolling 30-day CSV archives on a VPS, and serves it through a static interactive website with an Arctic polar-stereo map and detailed time-series plots.

---

## Overview

```
Remote APIs  →  VPS ingestion (Python + systemd)  →  CSV files  →  Nginx  →  Static website
```

The VPS runs scheduled Python fetch jobs (one per data source). Each job downloads the latest data, deduplicates it against the stored archive, and writes the result back as a CSV. Nginx serves those CSVs with CORS headers so the frontend can fetch them directly from any browser. There is no database and no application backend — just flat files and a well-structured JavaScript frontend.

---

## Data Sources

| Source | Instruments | Provider | Interval |
|--------|-------------|----------|----------|
| **Ships** | Le Commandant Charcot, Tara Polar Station, Polarstern, Oden | [EUMETNET eSurfMar](https://esurfmar.meteo.fr) | Every 4 h |
| **ArctSum 2025 buoys** | 19 ice-tethered thermistor string buoys | [Thredds / Met.no](https://thredds.met.no) | Scheduled |
| **SvalMIZ 2026 buoys** | 18 ice-tethered thermistor string buoys | [Thredds / Met.no](https://thredds.met.no) | Scheduled |
| **SIMBA ice buoys** | 2–3 Sea Ice Mass Balance buoys | [CryosphereInnovation API](https://api.cryosphereinnovation.com) | Scheduled |
| **Thermistor chains** | 2024T117, 2025T141, 2025T142 | [Sea Ice Portal](https://data.seaiceportal.de) | Scheduled |
| **IABP Arctic buoys** | ~30 active drifting buoys (with air temperature) | [IABP / apl.uw.edu](https://iabp.apl.uw.edu) | Every 6 h |

All sources retain the **last 30 days** of data. Older rows are pruned automatically on each fetch.

---

## Repository Layout

```
ArctDataCollector/
├── dev_serve.sh                  # Local dev helper: rsync from VPS + serve website
├── vps_server/
│   ├── app/
│   │   └── ingestion/
│   │       ├── handlers/         # Deduplication + CSV persistence (one per source)
│   │       └── sources/          # API fetch + parsing (one per source)
│   ├── config/
│   │   ├── ships.yaml            # Active ship registry
│   │   ├── arctsum_buoys.yaml    # ArctSum buoy registry + sensor calibration
│   │   ├── svalmiz_buoys.yaml    # SvalMIZ 2026 buoy registry
│   │   ├── simba_buoys.yaml      # SIMBA deployment IDs
│   │   ├── thermistor_buoys.yaml # Thermistor chain IDs
│   │   ├── iabp_buoys.yaml       # Active IABP buoy registry (auto-managed)
│   │   ├── secrets.example.yaml  # Template — copy to secrets.yaml and fill in API keys
│   │   └── settings.example.yaml # Template — server/path settings
│   ├── data/
│   │   └── processed/csv/        # Runtime CSV storage (gitignored)
│   │       ├── ships/
│   │       ├── arctsum/
│   │       ├── svalmiz/
│   │       ├── simba/
│   │       ├── thermistor/
│   │       └── iabp/             # One CSV per buoy + _index.json
│   ├── logs/                     # Runtime logs (gitignored)
│   ├── nginx/
│   │   └── arct-collector.conf   # Nginx site config
│   ├── requirements.txt
│   ├── scripts/
│   │   ├── bootstrap_vps.sh      # One-time setup: create venv + install deps
│   │   ├── fetch_ship_data.py
│   │   ├── fetch_arctsum_data.py
│   │   ├── fetch_simba_data.py
│   │   ├── fetch_thermistor_data.py
│   │   ├── fetch_iabp_data.py    # Daily IABP fetch
│   │   └── discover_iabp_buoys.py # Weekly: find new active Arctic IABP buoys
│   └── systemd/                  # Service + timer units for each source
└── website/
    ├── index.html
    ├── assets/
    │   ├── css/styles.css
    │   └── js/
    │       ├── app.js            # Main controller: time-range slider, card management
    │       ├── csv-loader.js     # CSV parser + URL routing (local vs. production)
    │       ├── map.js            # Leaflet Arctic polar-stereo map
    │       └── plot.js           # Plotly multi-panel detail plots
    ├── data/                     # Populated at runtime by dev_serve.sh (gitignored)
    └── scripts/
        └── generate_geojson.php  # Optional server-side GeoJSON converter
```

---

## VPS Deployment

### 1. Copy files to the server

```bash
rsync -av vps_server/ root@<your-vps-ip>:/opt/arct-collector/
```

### 2. Bootstrap the Python environment

```bash
ssh root@<your-vps-ip>
cd /opt/arct-collector
bash scripts/bootstrap_vps.sh
```

This creates `.venv/` and installs all dependencies from `requirements.txt`.

### 3. Configure

```bash
cp config/secrets.example.yaml config/secrets.yaml
# Edit secrets.yaml — add the CryosphereInnovation API key
```

### 4. Install and enable systemd timers

```bash
cp systemd/*.service systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

# Enable and start all timers
for svc in fetch-ship-data fetch-arctsum-data fetch-simba-data fetch-thermistor-data fetch-iabp-data discover-iabp-buoys; do
  systemctl enable --now ${svc}.timer
done

# Check status
systemctl list-timers fetch-* discover-*
```

Each timer fires a few minutes after boot and then repeats on its configured interval. Runs are persistent — a missed run is caught up on next boot.

| Timer | Interval | Purpose |
|-------|----------|---------|
| `fetch-ship-data` | Every 4 h | Ship observations |
| `fetch-arctsum-data` | Scheduled | ArctSum + SvalMIZ buoys |
| `fetch-simba-data` | Scheduled | SIMBA ice buoys |
| `fetch-thermistor-data` | Scheduled | Thermistor chains |
| `fetch-iabp-data` | Every 6 h | IABP drifting buoys |
| `discover-iabp-buoys` | Weekly (Mon 04:00 UTC) | Find newly active IABP buoys |

### 5. Configure Nginx

```bash
cp nginx/arct-collector.conf /etc/nginx/sites-available/arct-collector.conf
ln -s /etc/nginx/sites-available/arct-collector.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

The config exposes read-only locations with CORS headers:

| URL | Content |
|-----|---------|
| `http://<vps-ip>/data/ships/<WMO_ID>.csv` | Ship observations |
| `http://<vps-ip>/data/arctsum/<buoy_id>_ts.csv` | ArctSum time-series |
| `http://<vps-ip>/data/arctsum/<buoy_id>_temp.csv` | ArctSum temperature profile |
| `http://<vps-ip>/data/svalmiz/<buoy_id>_ts.csv` | SvalMIZ time-series |
| `http://<vps-ip>/data/svalmiz/<buoy_id>_temp.csv` | SvalMIZ temperature profile |
| `http://<vps-ip>/data/simba/<deployment_id>.csv` | SIMBA DTC profile |
| `http://<vps-ip>/data/thermistor/<buoy_id>.csv` | Thermistor chain data |
| `http://<vps-ip>/data/iabp/<buoy_id>.csv` | IABP buoy time-series |
| `http://<vps-ip>/data/iabp/_index.json` | IABP active buoy index |

---

## IABP Integration

Active Arctic drifting buoys are fetched from the [International Arctic Buoy Programme](https://iabp.apl.uw.edu).

**Data source:** `https://iabp.apl.uw.edu/TABLES/ArcticTables.js` (live table) + per-buoy time-series at `https://iabp.apl.uw.edu/WebData/{buoy_id}.dat`

**Registry filters** (`iabp_buoys.yaml`):
- Latitude ≥ 65°N
- Last report within 5 days (active buoys only)
- Must have air temperature (Ta) — position-only and surface-temp-only buoys excluded

**Quality control** (applied on every fetch):
- Physical plausibility: air temp −75 to +50°C, surface temp −5 to +35°C, pressure 850–1100 hPa
- Exact zero values rejected
- Buoys with no valid air_temp rows are excluded
- Stuck-sensor detection: if air_temp std-dev < 0.05°C over ≥10 readings, the buoy is excluded

**Weekly discovery** (`discover_iabp_buoys.py`): runs every Monday and appends newly active buoys to `iabp_buoys.yaml`. Existing entries are never removed — buoys that go quiet may become active again.

---

## Adding New Instruments

### New ship

Edit `vps_server/config/ships.yaml`:

```yaml
ships:
  - name: "My New Ship"
    wmo_id: "ABCD123"
    active: true
```

No code changes required. The ship will be picked up on the next timer run.

### New ArctSum / SvalMIZ buoy

Edit `vps_server/config/arctsum_buoys.yaml` or `svalmiz_buoys.yaml`:

```yaml
buoys:
  - buoy_id: "2025_08_KVS_ArctSum_20"
    sensor_ice2: 6   # index of the ice-surface reference sensor
    active: true
```

### New SIMBA buoy

Edit `vps_server/config/simba_buoys.yaml`:

```yaml
buoys:
  - name: "SIMBA buoy 4"
    deployment_id: "<uuid-from-cryosphere-innovation>"
    active: true
```

### New thermistor chain

Edit `vps_server/config/thermistor_buoys.yaml`:

```yaml
buoys:
  - name: "Thermistor 2025T200"
    buoy_id: "2025T200"
    active: true
```

### New IABP buoy

IABP buoys are auto-discovered weekly by `discover_iabp_buoys.py`. To register one immediately, add an entry to `vps_server/config/iabp_buoys.yaml` following the existing format, then run `fetch_iabp_data.py` manually.

---

## Running Manually

Any fetch script can be run directly for testing or a manual refresh:

```bash
cd /opt/arct-collector
source .venv/bin/activate

python3 scripts/fetch_ship_data.py --log-level DEBUG
python3 scripts/fetch_arctsum_data.py
python3 scripts/fetch_simba_data.py
python3 scripts/fetch_thermistor_data.py
python3 scripts/fetch_iabp_data.py
python3 scripts/discover_iabp_buoys.py --dry-run   # preview new buoys without writing
```

Each script accepts `--config` and `--output` overrides — run with `--help` for details.

---

## Local Development

`dev_serve.sh` pulls the latest CSV data from the VPS via rsync (falls back to the local cache if SSH is not reachable), copies it into `website/data/`, and starts a local HTTP server:

```bash
bash dev_serve.sh          # default port 8000
bash dev_serve.sh 9000     # custom port
```

The website is then available at **http://localhost:8000**.

The frontend automatically detects `localhost` / `127.0.0.1` and reads data from the local `website/data/` directory. On any other host it fetches directly from the production VPS via HTTP.

---

## Website Features

- **Arctic polar-stereo map** (Leaflet + Proj4js, EPSG:3996) centred on 90°N
  - GEBCO North Polar bathymetry WMS layer
  - Lat/lon graticule every 5°
  - Ship tracks (solid lines) and buoy tracks (dashed lines)
  - Latest-position markers with coloured borders
- **Time-range slider** — dual-handle, default last 14 days; all views update live
- **Quick-select cards** — one per instrument, showing data-freshness indicator, latest timestamp, position, and key scalar values
- **Detail plots** (Plotly, opens on card click):
  - **Ships**: air temperature, SST, pressure, wind speed/direction, humidity
  - **SIMBA**: DTC heatmap (depth in cm, 2 cm spacing) + air/water temperature, pressure, surface/bottom distance
  - **Thermistor chains**: T1–T240 heatmap + air temperature, pressure, tilt
  - **ArctSum / SvalMIZ buoys**: temperature string heatmap (depth-relative) + air/skin temperature, wave height, wave period
  - **IABP buoys**: atmospheric pressure time-series + air temperature time-series (panels auto-hide if sensor absent)

---

## Dependencies

### Python (VPS)

| Package | Purpose |
|---------|---------|
| `pyyaml` | Config file parsing |
| `requests` | HTTP fetches (SIMBA, thermistor) |
| `netCDF4` | ArctSum Thredds NetCDF parsing |
| `numpy` | Array operations for NetCDF data |

Install via: `pip install -r vps_server/requirements.txt`

### JavaScript (website, CDN — no install needed)

| Library | Purpose |
|---------|---------|
| [Leaflet](https://leafletjs.com) | Interactive map |
| [Proj4js](https://proj4js.org) | Polar-stereo projection |
| [Leaflet.Proj](https://github.com/kartena/Proj4Leaflet) | Proj4js adapter for Leaflet |
| [Plotly.js](https://plotly.com/javascript/) | Time-series and heatmap plots |

---

## Security Notes

- `vps_server/config/secrets.yaml` is **gitignored** and must never be committed. It contains the CryosphereInnovation API key. Use `secrets.example.yaml` as a template.
- Nginx serves CSV files read-only with `no-cache` headers. No write endpoints are exposed.
- The VPS does not run any application server in its public-facing configuration — only Nginx serves content externally.

---

## License

This project is developed for Arctic field research. Contact the repository owner for usage terms.


---

## Overview

```
Remote APIs  →  VPS ingestion (Python + systemd)  →  CSV files  →  Nginx  →  Static website
```

The VPS runs four scheduled Python fetch jobs (one per data source). Each job downloads the latest data, deduplicates it against the stored archive, and writes the result back as a CSV. Nginx serves those CSVs with CORS headers so the frontend can fetch them directly from any browser. There is no database and no application backend — just flat files and a well-structured JavaScript frontend.

---

## Data Sources

| Source | Instruments | Provider | Interval |
|--------|-------------|----------|----------|
| **Ships** | Le Commandant Charcot, Tara Polar Station, Polarstern, Oden | [EUMETNET eSurfMar](https://esurfmar.meteo.fr) | Every 4 h |
| **ArctSum 2025 buoys** | 19 ice-tethered thermistor string buoys | [Thredds / Met.no](https://thredds.met.no) | Scheduled |
| **SIMBA ice buoys** | 2 Sea Ice Mass Balance buoys | [CryosphereInnovation API](https://api.cryosphereinnovation.com) | Scheduled |
| **Thermistor chains** | 2024T117, 2025T141, 2025T142 | [Sea Ice Portal](https://data.seaiceportal.de) | Scheduled |

All sources retain the **last 30 days** of data. Older rows are pruned automatically on each fetch.

---

## Repository Layout

```
ArctDataCollector/
├── dev_serve.sh                  # Local dev helper: rsync from VPS + serve website
├── vps_server/
│   ├── app/
│   │   └── ingestion/
│   │       ├── handlers/         # Deduplication + CSV persistence (one per source)
│   │       └── sources/          # API fetch + parsing (one per source)
│   ├── config/
│   │   ├── ships.yaml            # Active ship registry
│   │   ├── arctsum_buoys.yaml    # ArctSum buoy registry + sensor calibration
│   │   ├── simba_buoys.yaml      # SIMBA deployment IDs
│   │   ├── thermistor_buoys.yaml # Thermistor chain IDs
│   │   ├── secrets.example.yaml  # Template — copy to secrets.yaml and fill in API keys
│   │   └── settings.example.yaml # Template — server/path settings
│   ├── data/
│   │   └── processed/csv/        # Runtime CSV storage (gitignored)
│   │       ├── ships/
│   │       ├── arctsum/
│   │       ├── simba/
│   │       └── thermistor/
│   ├── logs/                     # Runtime logs (gitignored)
│   ├── nginx/
│   │   └── arct-collector.conf   # Nginx site config
│   ├── requirements.txt
│   ├── scripts/
│   │   ├── bootstrap_vps.sh      # One-time setup: create venv + install deps
│   │   ├── fetch_ship_data.py
│   │   ├── fetch_arctsum_data.py
│   │   ├── fetch_simba_data.py
│   │   └── fetch_thermistor_data.py
│   └── systemd/                  # Service + timer units for each source
└── website/
    ├── index.html
    ├── assets/
    │   ├── css/styles.css
    │   └── js/
    │       ├── app.js            # Main controller: time-range slider, card management
    │       ├── csv-loader.js     # CSV parser + URL routing (local vs. production)
    │       ├── map.js            # Leaflet Arctic polar-stereo map
    │       └── plot.js           # Plotly multi-panel detail plots
    ├── data/                     # Populated at runtime by dev_serve.sh (gitignored)
    └── scripts/
        └── generate_geojson.php  # Optional server-side GeoJSON converter
```

---

## VPS Deployment

### 1. Copy files to the server

```bash
rsync -av vps_server/ root@<your-vps-ip>:/opt/arct-collector/
```

### 2. Bootstrap the Python environment

```bash
ssh root@<your-vps-ip>
cd /opt/arct-collector
bash scripts/bootstrap_vps.sh
```

This creates `.venv/` and installs all dependencies from `requirements.txt`.

### 3. Configure

```bash
cp config/secrets.example.yaml config/secrets.yaml
# Edit secrets.yaml — add the CryosphereInnovation API key
```

### 4. Install and enable systemd timers

```bash
cp systemd/*.service systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

# Enable and start all four timers
for svc in fetch-ship-data fetch-arctsum-data fetch-simba-data fetch-thermistor-data; do
  systemctl enable --now ${svc}.timer
done

# Check status
systemctl list-timers fetch-*
```

Each timer fires **5 minutes after boot**, then repeats on its configured interval (ships: every 4 h; others as defined in their timer units). Runs are persistent — a missed run is caught up on next boot.

### 5. Configure Nginx

```bash
cp nginx/arct-collector.conf /etc/nginx/sites-available/arct-collector
ln -s /etc/nginx/sites-available/arct-collector /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

The config exposes four read-only locations with CORS headers:

| URL | Content |
|-----|---------|
| `http://<vps-ip>/data/ships/<WMO_ID>.csv` | Ship observations |
| `http://<vps-ip>/data/arctsum/<buoy_id>_ts.csv` | ArctSum time-series |
| `http://<vps-ip>/data/arctsum/<buoy_id>_temp.csv` | ArctSum temperature profile |
| `http://<vps-ip>/data/simba/<deployment_id>.csv` | SIMBA DTC profile |
| `http://<vps-ip>/data/thermistor/<buoy_id>.csv` | Thermistor chain data |

---

## Adding New Instruments

### New ship

Edit `vps_server/config/ships.yaml`:

```yaml
ships:
  - name: "My New Ship"
    wmo_id: "ABCD123"
    active: true
```

No code changes required. The ship will be picked up on the next timer run.

### New ArctSum buoy

Edit `vps_server/config/arctsum_buoys.yaml`:

```yaml
buoys:
  - buoy_id: "2025_08_KVS_ArctSum_20"
    sensor_ice2: 6   # index of the ice-surface reference sensor
    active: true
```

### New SIMBA buoy

Edit `vps_server/config/simba_buoys.yaml`:

```yaml
buoys:
  - name: "SIMBA buoy 4"
    deployment_id: "<uuid-from-cryosphere-innovation>"
    active: true
```

### New thermistor chain

Edit `vps_server/config/thermistor_buoys.yaml`:

```yaml
buoys:
  - name: "Thermistor 2025T200"
    buoy_id: "2025T200"
    active: true
```

---

## Running Manually

Any fetch script can be run directly for testing or a manual refresh:

```bash
cd /opt/arct-collector
source .venv/bin/activate

python3 scripts/fetch_ship_data.py --log-level DEBUG
python3 scripts/fetch_arctsum_data.py
python3 scripts/fetch_simba_data.py
python3 scripts/fetch_thermistor_data.py
```

Each script accepts `--config` and `--output` overrides — run with `--help` for details.

---

## Local Development

`dev_serve.sh` pulls the latest CSV data from the VPS via rsync (falls back to the local cache if SSH is not reachable), copies it into `website/data/`, and starts a local HTTP server:

```bash
bash dev_serve.sh          # default port 8000
bash dev_serve.sh 9000     # custom port
```

The website is then available at **http://localhost:8000**.

The frontend automatically detects `localhost` / `127.0.0.1` and reads data from the local `website/data/` directory. On any other host it fetches directly from the production VPS via HTTP.

---

## Website Features

- **Arctic polar-stereo map** (Leaflet + Proj4js, EPSG:3996) centred on 90°N
  - GEBCO North Polar bathymetry WMS layer
  - Lat/lon graticule every 5°
  - Ship tracks (solid lines) and buoy tracks (dashed lines)
  - Latest-position markers with coloured borders
- **Time-range slider** — dual-handle, default last 14 days; all views update live
- **Quick-select cards** — one per instrument, showing data-freshness indicator, latest timestamp, position, and key scalar values
- **Detail plots** (Plotly, opens on card click):
  - **Ships**: air temperature, SST, pressure, wind speed/direction, humidity
  - **SIMBA**: DTC heatmap + air/water temperature, pressure, surface/bottom distance
  - **Thermistor chains**: T1–T240 heatmap + air temperature, pressure, tilt
  - **ArctSum buoys**: temperature string heatmap (depth-relative) + air/skin temperature, wave height, wave period

---

## Dependencies

### Python (VPS)

| Package | Purpose |
|---------|---------|
| `pyyaml` | Config file parsing |
| `requests` | HTTP fetches (SIMBA, thermistor) |
| `netCDF4` | ArctSum Thredds NetCDF parsing |
| `numpy` | Array operations for NetCDF data |

Install via: `pip install -r vps_server/requirements.txt`

### JavaScript (website, CDN — no install needed)

| Library | Purpose |
|---------|---------|
| [Leaflet](https://leafletjs.com) | Interactive map |
| [Proj4js](https://proj4js.org) | Polar-stereo projection |
| [Leaflet.Proj](https://github.com/kartena/Proj4Leaflet) | Proj4js adapter for Leaflet |
| [Plotly.js](https://plotly.com/javascript/) | Time-series and heatmap plots |

---

## Security Notes

- `vps_server/config/secrets.yaml` is **gitignored** and must never be committed. It contains the CryosphereInnovation API key. Use `secrets.example.yaml` as a template.
- Nginx serves CSV files read-only with `no-cache` headers. No write endpoints are exposed.
- The VPS does not run any application server in its public-facing configuration — only Nginx serves content externally.

---

## License

This project is developed for Arctic field research. Contact the repository owner for usage terms.


