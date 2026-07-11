"""
Flask HTTP endpoint that receives hex-encoded RockBLOCK payloads, decodes them,
stores them in master-decoded.json, and regenerates decoded_fixes.geojson for
the website map.

Deployment:
    Install BOTH this file (as main.py) and decoder_online.py at /opt/decoder/.
    Requires a venv at /opt/decoder_venv with: flask numpy scipy

    # Set up venv once:
    python3 -m venv /opt/decoder_venv
    /opt/decoder_venv/bin/pip install flask numpy scipy

    # Run via systemd (see systemd/decoder-flask.service):
    sudo systemctl enable --now decoder-flask

    # Test decode endpoint:
    curl -X POST http://localhost:8080/decode \
        -H "Content-Type: application/json" \
        -d '{"data":"4704469cb62a6007160f2ef5581e1246c2b62a60d3150f2e1b5b1e1246e8b62a6009110f2e2e8a1e1245"}'
"""

import dataclasses
import datetime
import json
import logging
import os
import tempfile
import threading

import numpy as np

from flask import Flask, request, jsonify, Response
from decoder_online import decode_message

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Serialize all writes so parallel Iridium deliveries never corrupt the files.
_lock = threading.Lock()

BASE_DIR          = os.path.dirname(__file__)
MASTER_JSON       = os.path.join(BASE_DIR, "master-decoded.json")
GEOJSON_LOCAL     = os.path.join(BASE_DIR, "decoded_fixes.geojson")
WEB_ROOT          = "/var/www/openmetbuoy-arctic.com"
GEOJSON_WEB       = os.path.join(WEB_ROOT, "decoded_fixes.geojson")
MASTER_JSON_WEB   = os.path.join(WEB_ROOT, "master-decoded.json")
LOG_FILE          = os.path.join(BASE_DIR, "rockblock-decoded.log")


def _to_jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(i) for i in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return [_to_jsonable(i) for i in obj.tolist()]
    return obj


def _atomic_write(path, text):
    """Write *text* to *path* atomically via a temp file + os.replace().

    Uses the same directory as the target so the rename stays on one
    filesystem and is therefore guaranteed atomic on POSIX.
    Any intermediate directories are created as needed.
    """
    dir_path = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_path, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_master():
    if os.path.exists(MASTER_JSON):
        with open(MASTER_JSON) as f:
            try:
                return json.load(f)
            except Exception:
                logging.warning("master-decoded.json was corrupt; starting fresh.")
                return []
    return []


def _save_master(entries):
    """Atomically persist entries to both the local store and the web root."""
    data = json.dumps(entries, indent=2)
    _atomic_write(MASTER_JSON, data)
    try:
        _atomic_write(MASTER_JSON_WEB, data)
    except Exception as exc:
        logging.warning("Could not write master-decoded.json to web root: %s", exc)


def _regenerate_geojson(entries):
    """Rebuild decoded_fixes.geojson from all stored entries and write it atomically.

    Only GNSS packets decoded from the payload are used — Iridium network
    geolocation is intentionally ignored.
    """
    features = []
    for entry in entries:
        imei          = entry.get("imei")
        transmit_time = entry.get("transmit_time")
        for fix in entry.get("decoded") or []:
            if fix.get("is_valid") and "latitude" in fix and "longitude" in fix:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type":        "Point",
                        "coordinates": [fix["longitude"], fix["latitude"]],
                    },
                    "properties": {
                        "imei":          imei,
                        "datetime_fix":  fix.get("datetime_fix"),
                        "transmit_time": transmit_time,
                    },
                })
    geojson = {"type": "FeatureCollection", "features": features}
    data = json.dumps(geojson, indent=2)
    _atomic_write(GEOJSON_LOCAL, data)
    try:
        _atomic_write(GEOJSON_WEB, data)
    except Exception as exc:
        logging.warning("Could not write decoded_fixes.geojson to web root: %s", exc)
    return len(features)


@app.route("/decode", methods=["POST"])
def decode():
    body = request.get_json(silent=True)
    if not body or not body.get("data"):
        return jsonify({"error": "Missing 'data' field"}), 400
    try:
        kind, metadata, packets = decode_message(
            body["data"], print_decoded=False, print_debug_information=False
        )
        return jsonify([_to_jsonable(p) for p in packets])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 422


# Accept both the canonical path and the legacy PHP path that some buoys
# may have configured as their RockBLOCK webhook URL.
@app.route("/rockblock", methods=["POST"])
@app.route("/rockblock-endpoint.php", methods=["POST"])
def rockblock():
    """Receives RockBlock Web Services delivery webhook."""
    data_hex      = request.form.get("data", "")
    imei          = request.form.get("imei", "")
    transmit_time = request.form.get("transmit_time", "")
    iridium_lat   = request.form.get("iridium_latitude", "")
    iridium_lon   = request.form.get("iridium_longitude", "")

    if not data_hex:
        return "FAILED", 400

    try:
        kind, metadata, packets = decode_message(
            data_hex, print_decoded=False, print_debug_information=False
        )
        decoded = [_to_jsonable(p) for p in packets]
    except Exception as exc:
        logging.error("Decode error IMEI=%s: %s", imei, exc)
        decoded = []

    with open(LOG_FILE, "a") as lf:
        lf.write("==== {} ====\n".format(datetime.datetime.utcnow().isoformat()))
        lf.write("IMEI: {}\nTime: {}\nLat: {} | Lon: {}\nHex: {}\n".format(
            imei, transmit_time, iridium_lat, iridium_lon, data_hex))
        lf.write("Decoded: {}\n\n".format(json.dumps(decoded)))

    with _lock:
        entries = _load_master()
        entries.append({
            "imei": imei,
            "transmit_time": transmit_time,
            "iridium_latitude": iridium_lat,
            "iridium_longitude": iridium_lon,
            "decoded": decoded,
        })
        _save_master(entries)
        n = _regenerate_geojson(entries)
    logging.info("rockblock: IMEI=%s, %d features in geojson", imei, n)

    return "OK", 200


@app.route("/decoded_fixes.geojson", methods=["GET"])
def send_geojson():
    if os.path.exists(GEOJSON_LOCAL):
        with open(GEOJSON_LOCAL) as f:
            data = f.read()
    else:
        data = json.dumps({"type": "FeatureCollection", "features": []})
    resp = Response(data, mimetype="application/geo+json")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/master-decoded.json", methods=["GET"])
def send_master():
    """Serve the full raw store so external tools can consume it."""
    if os.path.exists(MASTER_JSON):
        with open(MASTER_JSON) as f:
            data = f.read()
    else:
        data = "[]"
    resp = Response(data, mimetype="application/json")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
