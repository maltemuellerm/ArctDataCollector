"""IABP buoy ingestion handler.

Reads iabp_buoys.yaml, downloads the .dat time-series for each registered
buoy, and writes one CSV per buoy:

    data/processed/csv/iabp/{buoy_id}.csv

Columns: time, latitude, longitude, bp, surface_temp, air_temp

Also writes a JSON index file for the frontend:

    data/processed/csv/iabp/_index.json

The index contains display metadata for every buoy that has a non-empty CSV.
"""

import csv
import json
import logging
import sys
from pathlib import Path

import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from ingestion.sources.iabp_buoy import fetch_iabp_buoy

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "iabp_buoys.yaml"
_CSV_DIR     = Path(__file__).resolve().parents[3] / "data" / "processed" / "csv" / "iabp"

_CSV_FIELDS  = ["time", "latitude", "longitude", "bp", "surface_temp", "air_temp"]


def _load_yaml(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return cfg.get("buoys", [])


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows → %s", len(rows), path)


# Minimum std-dev for air_temp to be considered a live sensor (not stuck).
# Applied only when n >= _QC_MIN_N.
_QC_STUCK_STD = 0.05
_QC_MIN_N = 10


def _qc_rows(rows: list[dict], buoy_id: str) -> bool:
    """Return True if the buoy data passes quality control, False if it should
    be excluded.  Failures are logged at WARNING level."""
    ta_vals = [float(r["air_temp"]) for r in rows if r.get("air_temp") not in ("", None)]
    if not ta_vals:
        logger.warning("QC FAIL %s — no valid air_temp values (position-only)", buoy_id)
        return False
    if len(ta_vals) >= _QC_MIN_N:
        from statistics import stdev
        std = stdev(ta_vals)
        if std < _QC_STUCK_STD:
            logger.warning(
                "QC FAIL %s — stuck air_temp sensor (n=%d std=%.4f, all values ~%.2f°C)",
                buoy_id, len(ta_vals), std, sum(ta_vals) / len(ta_vals),
            )
            return False
    return True


def run(config_path: Path = _CONFIG_PATH, csv_dir: Path = _CSV_DIR) -> None:
    buoys = _load_yaml(config_path)
    csv_dir.mkdir(parents=True, exist_ok=True)

    index_entries = []

    for buoy in buoys:
        buoy_id  = buoy["buoy_id"]
        has_bp   = bool(buoy.get("has_bp", False))
        has_ts   = bool(buoy.get("has_ts", False))
        has_ta   = bool(buoy.get("has_ta", False))

        rows = fetch_iabp_buoy(buoy_id, has_bp=has_bp, has_ts=has_ts, has_ta=has_ta)

        if not rows:
            logger.warning("No data for buoy %s — skipping CSV", buoy_id)
            continue

        if not _qc_rows(rows, buoy_id):
            continue

        _write_csv(csv_dir / f"{buoy_id}.csv", rows)

        # Build human-readable name
        parts = []
        if buoy.get("buoy_type"):
            parts.append(buoy["buoy_type"])
        if buoy.get("campaign"):
            parts.append(buoy["campaign"])
        name = " – ".join(parts) if parts else buoy_id
        if buoy.get("wmo"):
            name = f"{name} ({buoy['wmo']})"

        index_entries.append({
            "id":       buoy_id,
            "name":     name,
            "owner":    buoy.get("owner", ""),
            "campaign": buoy.get("campaign", ""),
            "buoy_type": buoy.get("buoy_type", ""),
            "added":    buoy.get("added", ""),
            "has_bp":   has_bp,
            "has_ts":   has_ts,
            "has_ta":   has_ta,
        })

    # Write index for the frontend
    index_path = csv_dir / "_index.json"
    with index_path.open("w", encoding="utf-8") as fh:
        json.dump(index_entries, fh, indent=2)
    logger.info("Wrote index with %d entries → %s", len(index_entries), index_path)

    # Remove stale CSVs that are no longer in the registry
    active_ids = {e["id"] for e in index_entries}
    for stale in csv_dir.glob("*.csv"):
        if stale.stem not in active_ids:
            stale.unlink()
            logger.info("Removed stale CSV: %s", stale.name)
