"""Alaska ASOS observation source via Iowa Environmental Mesonet (IEM) API.

Fetches surface weather observations from the IEM ASOS archive API for
Alaskan Arctic stations (network AK_ASOS).

API:    https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
Auth:   None (open data, no key required).
Format: CSV with one row per observation, ~hourly ASOS reports.

Output CSV columns (shared land-station layout):
    time, station_id, latitude, longitude,
    air_temp, dew_point_temp, humidity,
    wind_direction, wind_speed, air_pressure
"""

import csv
import io
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_BASE_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

# IEM field names we request
_IEM_FIELDS = ["tmpf", "dwpf", "relh", "drct", "sknt", "mslp", "alti"]


def _iem_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ArctDataCollector/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"IEM HTTP {exc.code}: {exc.reason}\n{body[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"IEM request failed: {exc}") from exc


def _f2c(f_str: str) -> str:
    """Fahrenheit string → Celsius string, or '' on error."""
    try:
        return str(round((float(f_str) - 32.0) * 5.0 / 9.0, 2))
    except (ValueError, TypeError):
        return ""


def _kt2ms(kt_str: str) -> str:
    """Knots string → m/s string, or '' on error."""
    try:
        return str(round(float(kt_str) * 0.5144, 2))
    except (ValueError, TypeError):
        return ""


def _inhg2hpa(in_str: str) -> str:
    """Inches Hg string → hPa string, or '' on error."""
    try:
        return str(round(float(in_str) * 33.8639, 2))
    except (ValueError, TypeError):
        return ""


def _safe(val: str) -> str:
    return "" if val in ("M", "T", "None", "") else val


def fetch_alaska(
    station_id: str,
    fixed_lat: float,
    fixed_lon: float,
    since: datetime,
) -> list[dict]:
    """Download and parse ASOS observations from the IEM archive.

    Parameters
    ----------
    station_id:
        ICAO/FAA station code, e.g. ``"PABR"`` for Utqiagvik.
    fixed_lat / fixed_lon:
        Station coordinates (used as fallback if IEM doesn't return them).
    since:
        Fetch observations at or after this UTC datetime.

    Returns
    -------
    list of dict
        One row per observation, keyed by the shared land-station column names.
    """
    now = datetime.now(tz=timezone.utc)

    params = urllib.parse.urlencode({
        "station":    station_id,
        "data":       ",".join(_IEM_FIELDS),
        "year1":      since.year,
        "month1":     since.month,
        "day1":       since.day,
        "year2":      now.year,
        "month2":     now.month,
        "day2":       now.day,
        "tz":         "UTC",
        "format":     "onlycomma",
        "latlon":     "yes",
        "direct":     "no",
        "report_type": "3",   # routine hourly ASOS observations
    })
    url = f"{_BASE_URL}?{params}"
    logger.info("Fetching IEM ASOS for %s (%s → %s)", station_id, since.date(), now.date())

    raw = _iem_get(url)

    rows = []
    reader = csv.DictReader(io.StringIO(raw))
    for rec in reader:
        raw_ts = rec.get("valid", "").strip()
        if not raw_ts or raw_ts.startswith("#"):
            continue
        # IEM returns "YYYY-MM-DD HH:MM" in UTC — pad to full ISO format
        ts = raw_ts[:16]  # "YYYY-MM-DD HH:MM"
        if len(ts) < 16:
            continue
        ts = ts + ":00"  # → "YYYY-MM-DD HH:MM:00"

        lat_s = _safe(rec.get("lat", ""))
        lon_s = _safe(rec.get("lon", ""))
        lat = lat_s if lat_s else str(fixed_lat)
        lon = lon_s if lon_s else str(fixed_lon)

        tmpf  = _safe(rec.get("tmpf", ""))
        dwpf  = _safe(rec.get("dwpf", ""))
        relh  = _safe(rec.get("relh", ""))
        drct  = _safe(rec.get("drct", ""))
        sknt  = _safe(rec.get("sknt", ""))
        mslp  = _safe(rec.get("mslp", ""))
        alti  = _safe(rec.get("alti", ""))

        # Prefer MSL pressure; fall back to altimeter → hPa
        pressure = mslp if mslp else _inhg2hpa(alti)

        rows.append({
            "time":           ts,
            "station_id":     station_id,
            "latitude":       lat,
            "longitude":      lon,
            "air_temp":       _f2c(tmpf),
            "dew_point_temp": _f2c(dwpf),
            "humidity":       relh,
            "wind_direction": drct,
            "wind_speed":     _kt2ms(sknt),
            "air_pressure":   pressure,
        })

    logger.info("  %d observations parsed for %s", len(rows), station_id)
    return rows
