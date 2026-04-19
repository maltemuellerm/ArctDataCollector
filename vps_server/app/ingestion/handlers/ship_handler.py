"""Ship observation handler.

Loads the ship registry from ``config/ships.yaml``, fetches fresh CSV data via
the EUMETNET eSurfMar source for every active ship, merges with any
previously stored rows (deduplicating on *date* + *WMO id*), and writes the
result back to ``data/processed/csv/ships/<wmo_id>.csv``.
"""

import csv
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# Allow running this file directly from the scripts directory.
_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from ingestion.sources.eumetnet_ship import fetch_ship_csv
from ingestion.sources.frost_ship import fetch_frost_ship

logger = logging.getLogger(__name__)

# EUMETNET / upstream column names → standard names.
_SHIP_RENAME = {
    "date":                       "time",
    "Latitude (deg)":             "latitude",
    "Longitude (deg)":            "longitude",
    "Sea level Pressure (hPa)":   "air_pressure",
    "Air temperature (\u00b0C)": "air_temp",
    "Humidity (%)": "humidity",
    "Wind direction (deg)":       "wind_direction",
    "Wind speed (m/s)":           "wind_speed",
    "SST (\u00b0C)":              "sea_surface_temp",
    "Dew point temperature (\u00b0C)": "dew_point_temp",
}


def _normalize_ship_rows(rows: list[dict]) -> list[dict]:
    """Rename EUMETNET column headers to standard names (idempotent)."""
    return [{_SHIP_RENAME.get(k, k): v for k, v in r.items()} for r in rows]

_CONFIG_PATH  = Path(__file__).resolve().parents[3] / "config" / "ships.yaml"
_SECRETS_PATH = Path(__file__).resolve().parents[3] / "config" / "secrets.yaml"
_OUTPUT_DIR   = Path(__file__).resolve().parents[3] / "data" / "processed" / "csv" / "ships"
_WINDOW_DAYS  = 30


def _load_config(config_path: Path = _CONFIG_PATH) -> dict:
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _existing_rows(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _merge_rows(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Merge *existing* and *fresh* rows, deduplicate, keep last 30 days."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_WINDOW_DAYS)

    by_key: dict[str, dict] = {}
    for row in existing + fresh:
        # Support both old 'date' key (pre-normalisation) and new 'time' key.
        ts_val = row.get("time", row.get("date", "")).strip()
        key = (ts_val, row.get("WMO id", "").strip())
        by_key[key] = row  # fresh wins on duplicate key

    merged = sorted(
        by_key.values(),
        key=lambda r: r.get("time", r.get("date", "")),
        reverse=True,
    )

    filtered = []
    for row in merged:
        try:
            ts_str = row.get("time", row.get("date", ""))
            ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                filtered.append(row)
        except (KeyError, ValueError):
            filtered.append(row)

    return filtered


def _write_csv(csv_path: Path, rows: list[dict]) -> None:
    if not rows:
        logger.warning("No rows to write for %s", csv_path.name)
        return

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Wrote %d rows to %s", len(rows), csv_path)


def _load_secrets(secrets_path: Path = _SECRETS_PATH) -> dict:
    if not secrets_path.exists():
        return {}
    with secrets_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def run(config_path: Path = _CONFIG_PATH, output_dir: Path = _OUTPUT_DIR) -> None:
    """Fetch and save data for all active ships."""
    config = _load_config(config_path)
    url_template = config["eumetnet"]["url_template"]
    ships = [s for s in config.get("ships", []) if s.get("active", False)]

    if not ships:
        logger.warning("No active ships found in %s", config_path)
        return

    # Load secrets once; only needed if any ship uses the Frost source.
    secrets = _load_secrets() if any(s.get("source") == "frost" for s in ships) else {}

    for ship in ships:
        wmo_id = ship["wmo_id"]
        name = ship.get("name", wmo_id)
        source = ship.get("source", "eumetnet")
        csv_path = output_dir / f"{wmo_id}.csv"

        existing = _normalize_ship_rows(_existing_rows(csv_path))
        try:
            if source == "frost":
                frost_cfg = secrets.get("frost", {})
                client_id = frost_cfg.get("client_id", "")
                client_secret = frost_cfg.get("client_secret", "")
                if not client_id or not client_secret:
                    logger.error(
                        "Frost credentials missing in secrets.yaml — skipping %s", name
                    )
                    continue
                fresh = fetch_frost_ship(
                    station_id=ship["station_id"],
                    wmo_id=wmo_id,
                    client_id=client_id,
                    client_secret=client_secret,
                )
            else:
                fresh = fetch_ship_csv(wmo_id=wmo_id, url_template=url_template)
        except RuntimeError as exc:
            logger.error("Failed to fetch data for %s (%s): %s", name, wmo_id, exc)
            continue

        fresh = _normalize_ship_rows(fresh)
        merged = _merge_rows(existing, fresh)
        _write_csv(csv_path, merged)
        logger.info(
            "Updated %s (%s): %d rows stored in %s",
            name, wmo_id, len(merged), csv_path,
        )
