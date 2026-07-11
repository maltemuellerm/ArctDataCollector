# VPS Server

This folder contains all software that runs on the VPS (`148.230.70.161`).

## Responsibilities

- Receive Iridium/RockBLOCK messages, decode them, and expose a live GeoJSON feed
- Fetch meteorological and oceanographic observations from multiple remote APIs
- Deduplicate and store rolling 30-day CSV archives per instrument
- Serve everything via Nginx with CORS headers for the static frontend

---

## RockBLOCK / OpenMetBuoy Pipeline

RockBLOCK Web Services delivers each Iridium message as an HTTP POST to
`https://openmetbuoy-arctic.com/rockblock`. Nginx proxies that to a Flask
decoder running locally on port 8080.

```
RockBLOCK Web Services
        │  POST /rockblock (form-encoded)
        ▼
openmetbuoy-arctic.com  (nginx)
        │  proxy_pass → 127.0.0.1:8080/rockblock
        ▼
decoder-flask.service  (/opt/decoder/main.py)
        │  decode hex payload → GNSS/wave/thermistor packets
        │  append to master-decoded.json  (atomic write + threading.Lock)
        │  regenerate decoded_fixes.geojson  (atomic write)
        │  copy both files to /var/www/openmetbuoy-arctic.com/
        ▼
https://openmetbuoy-arctic.com/decoded_fixes.geojson  (public, CORS *)
https://openmetbuoy-arctic.com/master-decoded.json    (public, CORS *)
```

### Key design decisions

| Topic | Decision |
|-------|----------|
| **Concurrency** | All writes are wrapped in a `threading.Lock` — parallel Iridium deliveries never corrupt the JSON store |
| **Atomicity** | Files are written via `tempfile + os.replace()` — a crash mid-write cannot produce a partial/corrupt file |
| **History** | `master-decoded.json` accumulates every message ever received; `decoded_fixes.geojson` is rebuilt from it on every new arrival |
| **GNSS only** | Only packets with decoded GPS fixes appear in the GeoJSON — Iridium network geolocation is intentionally excluded |
| **External access** | Both JSON files are served with `Access-Control-Allow-Origin: *` so QGIS, web maps, and notebooks can load them directly |

### Deploy / update the decoder

```bash
# From the ArctDataCollector repo root:
scp vps_server/scripts/decoder_flask_main.py root@148.230.70.161:/opt/decoder/main.py
ssh root@148.230.70.161 "systemctl restart decoder-flask"
```

### Deploy nginx config

```bash
bash vps_server/scripts/deploy_openmetbuoy.sh --skip-certbot
```

This installs:
- `/etc/nginx/snippets/rockblock-proxy.conf` — forwards `/rockblock` to Flask
- `/etc/nginx/snippets/arct-proxy.conf` — proxies `/arct-data/` to ArctDataCollector
- `/etc/nginx/sites-available/openmetbuoy-arctic.com` — HTTPS server block with CORS for the data files

### Test the decoder

```bash
curl -X POST http://localhost:8080/decode \
  -H 'Content-Type: application/json' \
  -d '{"data":"4704469cb62a6007160f2ef5581e1246c2b62a60d3150f2e1b5b1e1246e8b62a6009110f2e2e8a1e1245"}'
```

---

## Data Fetch Services

Deploy with `scripts/bootstrap_vps.sh` then enable the systemd timers:

```bash
for svc in fetch-ship-data fetch-arctsum-data fetch-simba-data fetch-thermistor-data \
           fetch-iabp-data discover-iabp-buoys \
           compute-arome-verification compute-ecmwf-verification; do
  systemctl enable --now ${svc}.timer
done
```

Add new instruments in `config/ships.yaml`, `config/arctsum_buoys.yaml`, etc.
