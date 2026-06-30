"""
Flask HTTP endpoint that receives hex-encoded RockBLOCK payloads and returns
decoded packet data as JSON.

Deployment:
    Install BOTH this file (as main.py) and decoder_online.py at /opt/decoder/.
    Requires a venv at /opt/decoder_venv with: flask numpy scipy

    # Set up venv once:
    python3 -m venv /opt/decoder_venv
    /opt/decoder_venv/bin/pip install flask numpy scipy

    # Run via systemd (see systemd/decoder-flask.service):
    sudo systemctl enable --now decoder-flask

    # Test:
    curl -X POST http://localhost:8080/decode \
        -H "Content-Type: application/json" \
        -d '{"data":"4704469cb62a6007160f2ef5581e1246c2b62a60d3150f2e1b5b1e1246e8b62a6009110f2e2e8a1e1245"}'
"""

import dataclasses
import datetime
import json

import numpy as np
from flask import Flask, request, jsonify
from decoder_online import decode_message

app = Flask(__name__)


def _to_jsonable(obj):
    """Recursively convert dataclasses and datetimes to JSON-safe types."""
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


@app.route("/decode", methods=["POST"])
def decode():
    body = request.get_json(silent=True)
    if not body or not body.get("data"):
        return jsonify({"error": "Missing 'data' field"}), 400

    data_hex = body["data"]
    try:
        kind, metadata, packets = decode_message(data_hex, print_decoded=False)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 422

    return jsonify([_to_jsonable(p) for p in packets])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
