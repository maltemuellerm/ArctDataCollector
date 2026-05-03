"""ECCC Canadian Arctic station observation handler.

Reads a YAML config containing a ``stations:`` list, then for each active
station fetches observations from the MSC GeoMet SWOB-realtime API and
persists them as CSV files (one per station, named ``<station_id>.csv``).

CSV format (matches the shared land-station layout)::

    time, station_id, latitude, longitude,
    air_temp, dew_point_temp, humidity,
    wind_direction, wind_speed, air_pressure

On each run:
- If the station CSV is empty / missing : fetch from CAMPAIGN_START to now.
- If existing rows are present          : fetch from the latest timestamp to now
  and merge, deduplicating on (time, station_id).
"""

import csv
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from ingestion.sources.eccc import fetch_eccc

logger = logging.getLogger(__name__)

# Earliest date for which we want observations.
CAMPAIGN_START = datetime(2026, 4, 1, tzinfo=timezone.utc)

_CSV_FIELDS = [
    "time", "station_id", "latitude", "longitude",
    "air_temp", "dew_point_temp", "humidity",
    "wind_direction", "wind_speed", "air_pressure",
]


def _load_config(config_path: Path) -> list[dict]:
    with config_path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return cfg.get("stations", [])


def _existing_rows(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _last_timestamp(rows: list[dict]) -> datetime | None:
    latest = None
    for row in rows:
        ts_str = row.get("time", "").strip()
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            if latest is None or ts > latest:
                latest = ts
        except ValueError:
            continue
    return latest


def _merge_rows(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Merge and deduplicate on (time, station_id); keep everything >= CAMPAIGN_START."""
    by_key: dict[tuple, dict] = {}
    for row in existing + fresh:
        key = (row.get("time", "").strip(), row.get("station_id", "").strip())
        by_key[key] = row  # fresh wins on collision

    merged = sorted(by_key.values(), key=lambda r: r.get("time", ""))

    filtered = []
    for row in merged:
        ts_str = row.get("time", "").strip()
        try:
            ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            if ts >= CAMPAIGN_START:
                filtered.append(row)
        except ValueError:
            filtered.append(row)
    return filtered


def _write_csv(csv_path: Path, rows: list[dict]) -> None:
    if not rows:
        logger.warning("No rows to write for %s", csv_path.name)
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows → %s", len(rows), csv_path)


def run(config_path: Path, output_dir: Path) -> None:
    """Fetch and persist observations for all active stations in *config_path*."""
    stations = _load_config(config_path)
    active = [s for s in stations if s.get("active", False)]
    if not active:
        logger.warning("No active stations in %s", config_path)
        return

    for station in active:
        station_id = station["station_id"]
        name       = station.get("name", station_id)
        fixed_lat  = float(station["latitude"])
        fixed_lon  = float(station["longitude"])
        csv_path   = output_dir / f"{station_id}.csv"

        existing = _existing_rows(csv_path)
        last_ts  = _last_timestamp(existing)
        since    = max(last_ts, CAMPAIGN_START) if last_ts else CAMPAIGN_START

        try:
            fresh = fetch_eccc(
                station_id=station_id,
                fixed_lat=fixed_lat,
                fixed_lon=fixed_lon,
                since=since,
            )
        except RuntimeError as exc:
            logger.error("Failed to fetch %s (%s): %s", name, station_id, exc)
            continue

        merged = _merge_rows(existing, fresh)
        _write_csv(csv_path, merged)
