"""Fetch and parse IABP buoy data from iabp.apl.uw.edu.

Each buoy's time-series is at:
    https://iabp.apl.uw.edu/WebData/{buoy_id}.dat

The .dat format is space-delimited with these fixed + optional columns:
    [0] BuoyID
    [1] Year
    [2] Hour
    [3] Minute
    [4] DOY        (day-of-year as decimal, integer part = calendar day)
    [5] POS_DOY    (DOY of the position fix)
    [6] Lat
    [7] Lon
    [8] BP         (if has_bp)
    [8 or 9] Ts    (if has_ts)
    [9 or 10] Ta   (if has_ta)

The YAML metadata tells us which sensors each buoy carries so columns
can be correctly labelled.
"""

import logging
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_DAT_BASE   = "https://iabp.apl.uw.edu/WebData/{buoy_id}.dat"
_TIMEOUT    = 30          # seconds per request
_FILL_VALUE = -999.0      # IABP missing-data sentinel
_KEEP_DAYS  = 30          # rolling window stored on disk

# Physical plausibility ranges — values outside these are sensor errors.
# Exact zero is always treated as bad data for sensors.
_VALID_RANGE = {
    "air_temp":      (-75.0,  50.0),
    "surface_temp":  ( -5.0,  35.0),
    "air_pressure":  (850.0, 1100.0),
}


def _doy_to_datetime(year: int, doy_frac: float) -> datetime:
    """Convert year + fractional DOY to a UTC datetime (minute precision)."""
    base = datetime(int(year), 1, 1, tzinfo=timezone.utc)
    return base + timedelta(days=doy_frac - 1.0)


def _parse_dat(text: str, has_bp: bool, has_ts: bool, has_ta: bool) -> list[dict]:
    """Parse .dat file text into a list of row dicts."""
    sensor_names = []
    if has_bp:
        sensor_names.append("air_pressure")
    if has_ts:
        sensor_names.append("surface_temp")
    if has_ta:
        sensor_names.append("air_temp")

    rows = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=_KEEP_DAYS)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            year    = int(parts[1])
            doy     = float(parts[4])
            lat     = float(parts[6])
            lon     = float(parts[7])
        except (ValueError, IndexError):
            continue

        # Reject clearly corrupt year values (some IABP files contain e.g. 4016)
        if not (2000 <= year <= 2050):
            continue

        dt = _doy_to_datetime(year, doy)
        if dt < cutoff:
            continue

        row: dict = {
            "time":         dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latitude":     round(lat, 5),
            "longitude":    round(lon, 5),
            "air_pressure": "",
            "surface_temp": "",
            "air_temp":     "",
        }

        # Map optional sensor columns
        for i, name in enumerate(sensor_names):
            col_idx = 8 + i
            if col_idx < len(parts):
                try:
                    val = float(parts[col_idx])
                    if abs(val - _FILL_VALUE) <= 1.0:      # fill sentinel (-999)
                        continue
                    if val == 0.0:                         # zero is always bad
                        continue
                    lo, hi = _VALID_RANGE.get(name, (-1e9, 1e9))
                    if not (lo < val < hi):                # out of physical range
                        continue
                    row[name] = round(val, 3)
                except ValueError:
                    pass

        rows.append(row)

    # Sort chronologically
    rows.sort(key=lambda r: r["time"])
    return rows


def fetch_iabp_buoy(buoy_id: str, has_bp: bool, has_ts: bool, has_ta: bool) -> list[dict]:
    """Download and parse the .dat file for one IABP buoy.

    Returns a list of row dicts (columns: time, latitude, longitude, bp,
    surface_temp, air_temp), filtered to the last _KEEP_DAYS days.
    """
    url = _DAT_BASE.format(buoy_id=buoy_id)
    logger.debug("Fetching %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ArctDataCollector/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            text = resp.read().decode("ascii", errors="replace")
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return []

    rows = _parse_dat(text, has_bp=has_bp, has_ts=has_ts, has_ta=has_ta)
    logger.info("Parsed %d rows (last %d days) for buoy %s", len(rows), _KEEP_DAYS, buoy_id)
    return rows
