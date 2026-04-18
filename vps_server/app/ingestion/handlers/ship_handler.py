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

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "ships.yaml"
_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "processed" / "csv" / "ships"
_WINDOW_DAYS = 30


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
        key = (row.get("date", "").strip(), row.get("WMO id", "").strip())
        by_key[key] = row  # fresh wins on duplicate key

    merged = sorted(by_key.values(), key=lambda r: r.get("date", ""), reverse=True)

    filtered = []
    for row in merged:
        try:
            ts = datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                filtered.append(row)
        except (KeyError, ValueError):
            filtered.append(row)  # keep rows we cannot parse rather than drop them

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


def run(config_path: Path = _CONFIG_PATH, output_dir: Path = _OUTPUT_DIR) -> None:
    """Fetch and save data for all active ships."""
    config = _load_config(config_path)
    url_template = config["eumetnet"]["url_template"]
    ships = [s for s in config.get("ships", []) if s.get("active", False)]

    if not ships:
        logger.warning("No active ships found in %s", config_path)
        return

    for ship in ships:
        wmo_id = ship["wmo_id"]
        name = ship.get("name", wmo_id)
        csv_path = output_dir / f"{wmo_id}.csv"

        try:
            fresh = fetch_ship_csv(wmo_id=wmo_id, url_template=url_template)
        except RuntimeError as exc:
            logger.error("Failed to fetch data for %s (%s): %s", name, wmo_id, exc)
            continue

        existing = _existing_rows(csv_path)
        merged = _merge_rows(existing, fresh)
        _write_csv(csv_path, merged)
        logger.info(
            "Updated %s (%s): %d rows stored in %s",
            name, wmo_id, len(merged), csv_path,
        )
