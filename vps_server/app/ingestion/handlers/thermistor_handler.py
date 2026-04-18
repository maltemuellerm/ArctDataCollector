"""Thermistor chain buoy ingestion handler.

Downloads the ZIP from the Sea Ice Portal, extracts TS and TEMP CSVs,
and writes them to:
  data/processed/csv/thermistor/{buoy_id}_ts.csv
  data/processed/csv/thermistor/{buoy_id}_temp.csv

Files are fully overwritten on each run (always latest full deployment).
"""

import csv
import logging
import re
import sys
from pathlib import Path

import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from ingestion.sources.seaiceportal_thermistor import fetch_thermistor

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "thermistor_buoys.yaml"
_CSV_DIR     = Path(__file__).resolve().parents[3] / "data" / "processed" / "csv" / "thermistor"

# Keep only time + T-sensor columns in the TEMP file to reduce file size.
_TEMP_COL_RE = re.compile(r"^(time|T\d+ \(degC\))$")


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _write_csv(path: Path, rows: list[dict], cols: list[str] | None = None) -> None:
    if not rows:
        logger.warning("No rows to write to %s", path)
        return
    fieldnames = cols or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows → %s", len(rows), path)


def run(config_path: Path = _CONFIG_PATH, csv_dir: Path = _CSV_DIR) -> None:
    cfg   = _load_yaml(config_path)
    base_url = cfg["seaiceportal"]["base_url"]
    buoys    = [b for b in cfg["buoys"] if b.get("active", True)]

    csv_dir.mkdir(parents=True, exist_ok=True)

    for buoy in buoys:
        buoy_id = buoy["buoy_id"]
        try:
            ts_rows, temp_rows = fetch_thermistor(buoy_id, base_url)
        except Exception as exc:
            logger.error("Failed to fetch buoy %s: %s", buoy_id, exc)
            continue

        # TS file: all columns as-is (lat, lon, pressure, air temp, tilt, compass)
        _write_csv(csv_dir / f"{buoy_id}_ts.csv", ts_rows)

        # TEMP file: time + T-sensor columns only (drops lat/lon/filter_flag)
        if temp_rows:
            temp_cols = [k for k in temp_rows[0].keys() if _TEMP_COL_RE.match(k)]
            _write_csv(csv_dir / f"{buoy_id}_temp.csv", temp_rows, cols=temp_cols)

        logger.info("Done: buoy %s (%d TS, %d TEMP rows)", buoy_id, len(ts_rows), len(temp_rows))
