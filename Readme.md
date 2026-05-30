# ArctDataCollector

An operational Arctic observation data collection and visualization platform. The system fetches meteorological and oceanographic data from multiple remote Arctic instruments — research ships, ice-tethered buoys, and thermistor chains — stores rolling 30-day CSV archives on a VPS, and serves them through a static interactive website with an Arctic polar-stereo map, detailed time-series plots, and NWP model verification.

---

## Architecture

```
Remote APIs  →  VPS ingestion (Python + systemd)  →  CSV / JSON files  →  Nginx  →  Static website
```

The VPS runs scheduled Python fetch jobs — one per data source. Each job downloads the latest data, deduplicates it against the stored archive, and writes the result back as a CSV. Nginx serves those files with CORS headers so the frontend can fetch them directly from any browser. There is no database and no application backend — just flat files and a well-structured JavaScript frontend.

---

## Data Sources

| Source | Instruments | Provider | Interval |
|--------|-------------|----------|----------|
| **Ships** | Le Commandant Charcot, Tara Polar Station, Polarstern, Oden | [EUMETNET eSurfMar](https://esurfmar.meteo.fr) | Every 4 h |
| **ArctSum 2025 buoys** | 19 ice-tethered thermistor string buoys | [Thredds / Met.no](https://thredds.met.no) | Scheduled |
| **SvalMIZ 2026 buoys** | 18 ice-tethered thermistor string buoys | [Thredds / Met.no](https://thredds.met.no) | Scheduled |
| **SIMBA ice buoys** | 2–3 Sea Ice Mass Balance buoys | [CryosphereInnovation API](https://api.cryosphereinnovation.com) | Scheduled |
| **Thermistor chains** | 2024T117, 2025T141, 2025T142 | [Sea Ice Portal](https://data.seaiceportal.de) | Scheduled |
| **IABP Arctic buoys** | ~30 active drifting buoys | [IABP / apl.uw.edu](https://iabp.apl.uw.edu) | Every 6 h |

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
│   │   └── processed/csv/        # Runtime file storage (gitignored)
│   │       ├── ships/
│   │       ├── arctsum/
│   │       ├── svalmiz/
│   │       ├── simba/
│   │       ├── thermistor/
│   │       ├── iabp/             # One CSV per buoy + _index.json
│   │       ├── arome/            # AROME Arctic NWP verification JSON
│   │       └── ecmwf/            # IFS HRES + AIFS verification JSON
│   ├── logs/                     # Runtime logs (gitignored)
│   ├── nginx/
│   │   └── arct-collector.conf   # Nginx site config
│   ├── requirements.txt
│   ├── scripts/
│   │   ├── bootstrap_vps.sh              # One-time setup: create venv + install deps
│   │   ├── fetch_ship_data.py
│   │   ├── fetch_arctsum_data.py
│   │   ├── fetch_simba_data.py
│   │   ├── fetch_thermistor_data.py
│   │   ├── fetch_iabp_data.py            # Daily IABP fetch
│   │   ├── discover_iabp_buoys.py        # Weekly: find new active Arctic IABP buoys
│   │   ├── compute_arome_verification.py # Daily AROME Arctic verification
│   │   └── compute_ecmwf_verification.py # Daily IFS HRES + AIFS verification (MARS)
│   └── systemd/                  # Service + timer units for each source
└── website/
    ├── index.html                # Main map & explorer page
    ├── verification.html         # NWP model verification page (AROME Arctic)
    ├── verification_ecmwf.html   # NWP model verification page (IFS HRES + AIFS)
    ├── download.html             # Data download page
    ├── svalmiz_analysis.html     # SvalMIZ-26 campaign in-depth analysis
    ├── assets/
    │   ├── css/
    │   │   ├── styles.css
    │   │   ├── download.css
    │   │   └── verification.css
    │   └── js/
    │       ├── app.js                 # Main controller: time-range slider, card management
    │       ├── csv-loader.js          # CSV parser + URL routing (local vs. production)
    │       ├── map.js                 # Leaflet Arctic polar-stereo map
    │       ├── plot.js                # Plotly multi-panel detail plots
    │       ├── svalmiz_analysis.js    # SvalMIZ-26 campaign ensemble analysis
    │       └── verification.js        # NWP verification charts and map
    └── data/                     # Populated at runtime by dev_serve.sh (gitignored)
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
# Edit secrets.yaml — add the CryosphereInnovation API key and ECMWF API key
```

### 4. Install and enable systemd timers

```bash
cp systemd/*.service systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

for svc in fetch-ship-data fetch-arctsum-data fetch-simba-data fetch-thermistor-data \
           fetch-iabp-data discover-iabp-buoys \
           compute-arome-verification compute-ecmwf-verification; do
  systemctl enable --now ${svc}.timer
done

systemctl list-timers fetch-* discover-* compute-*
```

| Timer | Interval | Purpose |
|-------|----------|---------|
| `fetch-ship-data` | Every 4 h | Ship observations |
| `fetch-arctsum-data` | Scheduled | ArctSum + SvalMIZ buoys |
| `fetch-simba-data` | Scheduled | SIMBA ice buoys |
| `fetch-thermistor-data` | Scheduled | Thermistor chains |
| `fetch-iabp-data` | Every 6 h | IABP drifting buoys |
| `discover-iabp-buoys` | Weekly (Mon 04:00 UTC) | Find newly active IABP buoys |
| `compute-arome-verification` | Daily 06:00 UTC | AROME Arctic NWP verification |
| `compute-ecmwf-verification` | Daily 07:00 UTC | IFS HRES + AIFS NWP verification |

### 5. Configure Nginx

```bash
cp nginx/arct-collector.conf /etc/nginx/sites-available/arct-collector.conf
ln -s /etc/nginx/sites-available/arct-collector.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

Key served locations:

| URL path | Content |
|----------|---------|
| `/data/ships/<WMO_ID>.csv` | Ship observations |
| `/data/arctsum/<buoy_id>_{ts,temp}.csv` | ArctSum time-series + temperature profile |
| `/data/svalmiz/<buoy_id>_{ts,temp}.csv` | SvalMIZ time-series + temperature profile |
| `/data/simba/<deployment_id>.csv` | SIMBA DTC profile |
| `/data/thermistor/<buoy_id>.csv` | Thermistor chain data |
| `/data/iabp/<buoy_id>.csv` | IABP buoy time-series |
| `/data/iabp/_index.json` | IABP active buoy index |
| `/data/arome/verification.json` | AROME Arctic verification stats |
| `/data/ecmwf/verification_ifs.json` | IFS HRES verification stats |
| `/data/ecmwf/verification_aifs.json` | AIFS verification stats |

---

## NWP Verification

The verification page compares model forecasts against co-located surface observations across three models:

- **AROME Arctic 2.5 km** — 00Z and 12Z, hourly steps up to 66 h, fetched from MET Norway THREDDS
- **IFS HRES 0.25°** — 00Z and 12Z, hourly steps up to 72 h, fetched via ECMWF MARS
- **AIFS 0.25°** — 00Z and 12Z, 6-hourly steps up to 72 h, fetched via ECMWF MARS

Each surface observation is paired with the nearest model grid point (max 0.5° accepted). Statistics are computed over 30-day rolling windows grouped by lead time.

The verification page shows:
- Observation locations coloured by per-point bias or absolute error (toggle between models)
- Bias & MAE vs. lead time (all three models on one chart)
- RMSE vs. lead time (all three models on one chart)
- Observation vs. model scatter with per-model selection
- Error vs. observed value with per-model selection

---

## IABP Integration

Active Arctic drifting buoys are fetched from the [International Arctic Buoy Programme](https://iabp.apl.uw.edu).

**Registry filters:** latitude ≥ 65°N, last report within 5 days, must report air temperature.

**Quality control:** physical plausibility bounds, exact-zero rejection, stuck-sensor detection (std-dev < 0.05°C over ≥10 readings → excluded).

**Weekly discovery** (`discover_iabp_buoys.py`): runs every Monday and appends newly active buoys to `iabp_buoys.yaml`. Existing entries are never removed.

---

## Adding New Instruments

### New ship
Edit `vps_server/config/ships.yaml` — no code changes required.

### New ArctSum / SvalMIZ buoy
Edit `vps_server/config/arctsum_buoys.yaml` or `svalmiz_buoys.yaml` and set `sensor_ice2` (ice-surface reference sensor index).

### New SIMBA buoy
Edit `vps_server/config/simba_buoys.yaml` with the CryosphereInnovation deployment UUID.

### New thermistor chain
Edit `vps_server/config/thermistor_buoys.yaml` with the Sea Ice Portal buoy ID.

### New IABP buoy
IABP buoys are auto-discovered weekly. To register one immediately, add it to `iabp_buoys.yaml` and run `fetch_iabp_data.py` manually.

---

## Running Manually

```bash
cd /opt/arct-collector
source .venv/bin/activate

python3 scripts/fetch_ship_data.py --log-level DEBUG
python3 scripts/fetch_arctsum_data.py
python3 scripts/fetch_simba_data.py
python3 scripts/fetch_thermistor_data.py
python3 scripts/fetch_iabp_data.py
python3 scripts/discover_iabp_buoys.py --dry-run
python3 scripts/compute_arome_verification.py
python3 scripts/compute_ecmwf_verification.py
```

---

## Local Development

`dev_serve.sh` pulls the latest data from the VPS via rsync, copies it into `website/data/`, and starts a local HTTP server:

```bash
bash dev_serve.sh          # default port 8000
bash dev_serve.sh 9000     # custom port
```

The frontend automatically detects `localhost` / `127.0.0.1` and reads data from the local `website/data/` directory. On any other host it fetches directly from the production VPS via HTTP.

---

## Website Features

- **Arctic polar-stereo map** (Leaflet + Proj4js, EPSG:3996) centred on 90°N with GEBCO bathymetry WMS and lat/lon graticule
- **Time-range slider** — dual-handle, default last 14 days; all views update live
- **Collapsible observation panels** — one accordion group per source (Ships / ArctSum / SvalMIZ / IABP / SIMBA / Thermistor), each showing active/total count badge
- **Detail plots** (Plotly, opens on card click):
  - **Ships**: air temp, SST, dew point, pressure, wind speed, humidity, solar irradiance
  - **SIMBA**: DTC heatmap + air/water temperature, pressure, surface/bottom distance
  - **Thermistor chains**: T-string heatmap + air temperature, pressure, tilt
  - **ArctSum / SvalMIZ buoys**: temperature string heatmap + air/skin temp, wave height, wave period
  - **IABP buoys**: pressure + air temperature time-series
- **NWP Verification page** — unified comparison of AROME Arctic, IFS HRES, and AIFS against surface observations
- **SvalMIZ-26 Analysis page** — in-depth campaign-level analysis across all 18 SvalMIZ-26 buoys:
  - Ensemble mean ± 1σ time-series for **air temperature** and **skin temperature**
  - **Conductive heat flux** through sea ice ($F = k_\text{ice} \times dT/dz$) from linear regression through in-ice thermistor sensors (z = 0.00–0.48 m); scale −10 to +30 W m⁻²; upward/downward labelled
  - **Modified Stefan law sea-ice growth model** driven by ensemble mean air temperature (initial ice 0.50 m, snow 0.10 m, $k_\text{snow}$ = 0.31 W m⁻¹ K⁻¹); red shading marks periods where growth is paused ($T_\text{air} > T_f$)
- **Near-freezing colorscale** — temperature heatmaps for ArctSum/SvalMIZ buoys use a custom colorscale with a distinctive bright-cyan band at −3 to 0 °C to highlight the sea-water freezing zone

---

## Dependencies

### Python (VPS)

| Package | Purpose |
|---------|---------|
| `pyyaml` | Config file parsing |
| `requests` | HTTP fetches |
| `netCDF4` | Thredds NetCDF parsing |
| `numpy` | Array operations |
| `ecmwf-api-client` | ECMWF MARS requests (IFS/AIFS verification) |

Install via: `pip install -r vps_server/requirements.txt`

### JavaScript (website, CDN — no install needed)

| Library | Purpose |
|---------|---------|
| [Leaflet](https://leafletjs.com) | Interactive map |
| [Proj4js](https://proj4js.org) | Polar-stereo projection |
| [Leaflet.Proj](https://github.com/kartena/Proj4Leaflet) | Proj4js adapter for Leaflet |
| [Plotly.js](https://plotly.com/javascript/) | Time-series, heatmap, and verification plots |

---

## Security Notes

- `vps_server/config/secrets.yaml` is **gitignored** and must never be committed. It contains API keys (CryosphereInnovation, ECMWF). Use `secrets.example.yaml` as a template.
- Nginx serves all files read-only with `no-cache` headers. No write endpoints are exposed.
- The VPS does not run any application server publicly — only Nginx serves content externally.

---

## License

This project is developed for Arctic field research. Contact the repository owner for usage terms.
