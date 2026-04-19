#!/usr/bin/env python3
"""Weekly discovery: find newly active Arctic IABP buoys and add them to the registry.

Fetches https://iabp.apl.uw.edu/TABLES/ArcticTables.js and applies the same
filters used when building the initial registry:

    - lat >= 65 N
    - Latest report within ACTIVE_DAYS days
    - Has air temperature (Ta) — BP/Ts-only buoys excluded

New buoys are appended to iabp_buoys.yaml.  Existing entries are never
removed (they may become active again).  A summary of changes is logged.

Usage:
    python3 discover_iabp_buoys.py
    python3 discover_iabp_buoys.py --log-level DEBUG
    python3 discover_iabp_buoys.py --dry-run        (report only, no writes)
"""

import argparse
import logging
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_SCRIPT_DIR    = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _SCRIPT_DIR.parent / "config" / "iabp_buoys.yaml"
_TABLE_JS_URL  = "https://iabp.apl.uw.edu/TABLES/ArcticTables.js"
_TIMEOUT       = 20
_MIN_LAT       = 65.0
_ACTIVE_DAYS   = 5       # days since last report to count as "active"
_FILL_VALUE    = -999.0
# Only register buoys that measure air temperature (Ta).
# Buoys with surface temperature (Ts) or pressure (BP) only are excluded.
_REQUIRE_TA = True

# Regex to match one buoy row from ArcticTables.js
# Columns: BuoyID, WMO, Year, Type, Owner, Campaign, LastReport, Lat, Lon, BP, Ts, Ta
_ROW_RE = re.compile(
    r'\["([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",'
    r'\s*"([^"]*)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]*)",'
    r'\s*"([^"]*)",\s*"([^"]*)"'
)


def _valid_sensor(v: str) -> bool:
    """Return True if value represents a real measurement (not NA or fill)."""
    v = v.strip()
    if not v or v in ("NA", "N/A", ""):
        return False
    try:
        fv = float(v)
        # Exclude the -999 fill sentinel and exact zero.
        return abs(fv - _FILL_VALUE) > 1.0 and fv != 0.0
    except ValueError:
        return False


def _fetch_table() -> list[tuple]:
    """Download ArcticTables.js and return parsed row tuples."""
    logger.info("Fetching %s", _TABLE_JS_URL)
    req = urllib.request.Request(_TABLE_JS_URL, headers={"User-Agent": "ArctDataCollector/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    rows = _ROW_RE.findall(data)
    logger.info("Parsed %d rows from ArcticTables.js", len(rows))
    return rows


def _discover_active(rows: list[tuple], threshold: datetime) -> list[dict]:
    """Filter table rows to active Arctic buoys with at least one sensor."""
    active = []
    for e in rows:
        buoy_id, wmo, year, btype, owner, campaign, last_str, lat_s, lon_s, bp, ts_v, ta = e
        try:
            lat = float(lat_s)
        except ValueError:
            continue
        if lat < _MIN_LAT:
            continue
        try:
            last = datetime.strptime(last_str, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if last < threshold:
            continue
        has_bp = _valid_sensor(bp)
        has_ts = _valid_sensor(ts_v)
        has_ta = _valid_sensor(ta)
        if _REQUIRE_TA and not has_ta:
            continue
        if not (has_bp or has_ts or has_ta):
            continue
        active.append({
            "buoy_id":   buoy_id,
            "wmo":       wmo,
            "buoy_type": btype,
            "owner":     owner,
            "campaign":  campaign,
            "has_bp":    has_bp,
            "has_ts":    has_ts,
            "has_ta":    has_ta,
        })
    return active


def _load_registry(path: Path) -> tuple[list[dict], list[str]]:
    """Load existing YAML.  Returns (buoy_list, comment_header_lines)."""
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8") as fh:
        raw = fh.read()
    # Preserve leading comment lines
    header = [ln for ln in raw.splitlines() if ln.startswith("#")]
    cfg = yaml.safe_load(raw)
    return cfg.get("buoys", []), header


def _write_registry(path: Path, buoys: list[dict], header_lines: list[str]) -> None:
    """Write the full buoy list back to YAML, preserving comment header."""
    lines = header_lines[:] + ["", "buoys:"]
    for b in buoys:
        lines.append(f'  - buoy_id: "{b["buoy_id"]}"')
        for k in ("wmo", "buoy_type", "owner", "campaign"):
            v = b.get(k, "")
            if v:
                lines.append(f'    {k}: "{v}"')
        lines.append(f'    added: "{b["added"]}"')
        lines.append(f'    has_bp: {"true" if b.get("has_bp") else "false"}')
        lines.append(f'    has_ts: {"true" if b.get("has_ts") else "false"}')
        lines.append(f'    has_ta: {"true" if b.get("has_ta") else "false"}')
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def run(config_path: Path = _DEFAULT_CONFIG, dry_run: bool = False) -> None:
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=_ACTIVE_DAYS)

    rows    = _fetch_table()
    found   = _discover_active(rows, threshold)
    existing, header = _load_registry(config_path)

    existing_ids = {b["buoy_id"] for b in existing}
    new_buoys = [b for b in found if b["buoy_id"] not in existing_ids]

    if not new_buoys:
        logger.info("No new active buoys found — registry unchanged (%d entries)", len(existing))
        return

    logger.info("Found %d new active buoy(s):", len(new_buoys))
    for b in new_buoys:
        logger.info("  + %s (%s / %s / %s)", b["buoy_id"], b["buoy_type"], b["owner"], b["campaign"])

    if dry_run:
        logger.info("Dry-run: no changes written.")
        return

    today = now.strftime("%Y-%m-%d")
    for b in new_buoys:
        b["added"] = today

    updated = existing + new_buoys
    updated.sort(key=lambda b: b["buoy_id"])

    # Update the count comment in the header
    new_header = []
    for ln in header:
        if "buoys currently tracked" in ln:
            new_header.append(f"# {len(updated)} buoys currently tracked")
        else:
            new_header.append(ln)
    if not new_header:
        new_header = [
            f"# Active Arctic IABP buoys",
            f"# Managed by discover_iabp_buoys.py — do not manually reorder entries",
            f"# Filters: lat>={_MIN_LAT}N, last report within {_ACTIVE_DAYS} days, has air temp (Ta) or pressure (BP)",
            f"# {len(updated)} buoys currently tracked",
        ]

    _write_registry(config_path, updated, new_header)
    logger.info("Registry updated — %d total buoys (%d new)", len(updated), len(new_buoys))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover and register new active IABP buoys.")
    parser.add_argument("--config",    type=Path, default=_DEFAULT_CONFIG)
    parser.add_argument("--dry-run",   action="store_true",
                        help="Report new buoys without writing to disk.")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    run(config_path=args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
