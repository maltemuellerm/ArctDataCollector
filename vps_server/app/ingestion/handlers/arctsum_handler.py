"""ArctSum 2025 thermistor string buoy ingestion handler.

Downloads the combined Thredds NetCDF, extracts data for each active
buoy, and writes two CSVs per buoy:
  data/processed/csv/arctsum/{buoy_id}_ts.csv   GPS + scalar variables
  data/processed/csv/arctsum/{buoy_id}_temp.csv  Temperature string profile
"""

import csv
import logging
import sys
from pathlib import Path

import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from ingestion.sources.arctsum_buoy import fetch_arctsum

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "arctsum_buoys.yaml"
_CSV_DIR     = Path(__file__).resolve().parents[3] / "data" / "processed" / "csv" / "arctsum"


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        logger.warning("No rows to write to %s", path)
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows → %s", len(rows), path)


def run(config_path: Path = _CONFIG_PATH, csv_dir: Path = _CSV_DIR) -> None:
    cfg      = _load_yaml(config_path)
    nc_url   = cfg["thredds"]["nc_url"]
    buoys    = {b["buoy_id"]: b["sensor_ice2"] for b in cfg["buoys"] if b.get("active", True)}

    csv_dir.mkdir(parents=True, exist_ok=True)

    results = fetch_arctsum(nc_url, buoys)

    for buoy_id, (ts_rows, temp_rows) in results.items():
        if buoy_id not in buoys:
            continue  # skip inactive buoys present in the NC file
        _write_csv(csv_dir / f"{buoy_id}_ts.csv",   ts_rows)
        _write_csv(csv_dir / f"{buoy_id}_temp.csv", temp_rows)
