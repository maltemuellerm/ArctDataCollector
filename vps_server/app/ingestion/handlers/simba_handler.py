"""SIMBA ice buoy ingestion handler.

Loads buoy registry from config/simba_buoys.yaml and API key from
config/secrets.yaml, fetches each active deployment, merges with stored
data (deduplicating on deployment_id + timestamp), keeps last 30 days,
and writes CSV to data/processed/csv/simba/<deployment_id>.csv.

The raw JSON response is also saved to data/raw/simba/<deployment_id>.json
so the schema can be inspected after the first live run.
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

from ingestion.sources.cryosphere_simba import fetch_simba_deployment

logger = logging.getLogger(__name__)

_CONFIG_PATH  = Path(__file__).resolve().parents[3] / "config" / "simba_buoys.yaml"
_SECRETS_PATH = Path(__file__).resolve().parents[3] / "config" / "secrets.yaml"
_CSV_DIR      = Path(__file__).resolve().parents[3] / "data" / "processed" / "csv" / "simba"
_RAW_DIR      = Path(__file__).resolve().parents[3] / "data" / "raw" / "simba"

# SIMBA buoys run for months-years; keep the full deployment, no rolling window.


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _timestamp_value(row: dict) -> str:
    for k in ("time_stamp", "timestamp", "datetime", "time", "date", "created_at", "measured_at"):
        if row.get(k):
            return str(row[k])
    return ""


def _dedup_key(row: dict) -> tuple:
    return (row.get("deployment_id", ""), _timestamp_value(row))


def _merge_rows(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Merge existing and fresh rows, deduplicating on deployment_id + timestamp.
    All rows are kept (no time window) since SIMBA deployments are finite datasets."""
    by_key: dict[tuple, dict] = {}
    for row in existing + fresh:
        by_key[_dedup_key(row)] = row  # fresh wins on collision
    return sorted(by_key.values(), key=lambda r: _timestamp_value(r))


def _existing_csv_rows(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(csv_path: Path, rows: list[dict]) -> None:
    if not rows:
        logger.warning("No rows to write for %s", csv_path.name)
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows to %s", len(rows), csv_path)


def _save_raw_json(raw_dir: Path, deployment_id: str, raw_json) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{deployment_id}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(raw_json, fh, indent=2, default=str)
    logger.debug("Saved raw JSON to %s", path)


def run(
    config_path: Path = _CONFIG_PATH,
    secrets_path: Path = _SECRETS_PATH,
    csv_dir: Path = _CSV_DIR,
    raw_dir: Path = _RAW_DIR,
) -> None:
    config = _load_yaml(config_path)

    if not secrets_path.exists():
        raise FileNotFoundError(
            f"Secrets file not found: {secrets_path}\n"
            f"Copy config/secrets.example.yaml to config/secrets.yaml and fill in your API key."
        )
    secrets = _load_yaml(secrets_path)
    api_key = secrets.get("cryosphere_innovation_api_key", "")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        raise ValueError("cryosphere_innovation_api_key not set in config/secrets.yaml")

    base_url = config["cryosphere_innovation"]["base_url"]
    buoys = [b for b in config.get("buoys", []) if b.get("active", False)]

    if not buoys:
        logger.warning("No active SIMBA buoys in %s", config_path)
        return

    for buoy in buoys:
        dep_id = buoy["deployment_id"]
        name   = buoy.get("name", dep_id)
        csv_path = csv_dir / f"{dep_id}.csv"

        try:
            raw_json, fresh_rows = fetch_simba_deployment(dep_id, base_url, api_key)
        except RuntimeError as exc:
            logger.error("Failed to fetch %s (%s): %s", name, dep_id, exc)
            continue

        _save_raw_json(raw_dir, dep_id, raw_json)

        existing = _existing_csv_rows(csv_path)
        merged   = _merge_rows(existing, fresh_rows)
        _write_csv(csv_path, merged)
        logger.info("Updated %s (%s): %d rows", name, dep_id, len(merged))
