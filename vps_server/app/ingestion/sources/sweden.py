"""SMHI (Swedish Meteorological and Hydrological Institute) Open Data source.

Fetches surface weather observations from the SMHI Open Data REST API for
Swedish Arctic stations (Tarfala, Abisko, Karesuando, etc.).

API:    https://opendata-download-metobs.smhi.se/api/version/1.0
Auth:   None (open data, no API key required).
Docs:   https://opendata.smhi.se/apidocs/

The SMHI API serves one parameter at a time.  We query:
  parameter 1  = air temperature (°C, hourly corrected)
  parameter 4  = wind speed (m/s, 10 min average)
  parameter 3  = wind direction (°, 10 min average)
  parameter 9  = air pressure reduced to sea level (hPa, hourly)
  parameter 5  = precipitation (mm, ignored here)

Station IDs are SMHI station IDs (integer).

Output CSV columns (shared land-station layout):
    time, station_id, latitude, longitude,
    air_temp, dew_point_temp, humidity,
    wind_direction, wind_speed, air_pressure
"""

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_BASE = "https://opendata-download-metobs.smhi.se/api/version/1.0"

# SMHI parameter numbers → our column names
_PARAMS = {
    "1":  "air_temp",       # hourly air temperature (°C)
    "3":  "wind_direction", # wind direction (°)
    "4":  "wind_speed",     # wind speed m/s
    "9":  "air_pressure",   # sea-level pressure hPa
    "39": "humidity",       # relative humidity %
}


def _smhi_get(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ArctDataCollector/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"SMHI HTTP {exc.code}: {exc.reason}\n{body[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"SMHI request failed: {exc}") from exc


def fetch_sweden(
    station_id: str,
    fixed_lat: float,
    fixed_lon: float,
    since: datetime,
) -> list[dict]:
    """Download and parse observations from the SMHI Open Data API.

    Parameters
    ----------
    station_id:
        SMHI station ID string, e.g. ``"180960"`` (Tarfala).
    fixed_lat / fixed_lon:
        Station coordinates.
    since:
        Fetch observations at or after this UTC datetime.

    Returns
    -------
    list of dict
        One row per observation hour.
    """
    logger.info("Fetching SMHI observations for station %s", station_id)
    since_ms = int(since.timestamp() * 1000)

    by_time: dict[str, dict] = {}

    for param_id, col_name in _PARAMS.items():
        url = (
            f"{_BASE}/parameter/{param_id}/station/{station_id}"
            f"/period/latest-months/data.json"
        )
        logger.debug("  Fetching param %s (%s) for %s", param_id, col_name, station_id)
        try:
            payload = _smhi_get(url)
        except RuntimeError as exc:
            logger.warning("  Skipping param %s for %s: %s", param_id, station_id, exc)
            continue

        values = payload.get("value", [])
        for entry in values:
            date_ms = entry.get("date")
            val     = entry.get("value", "")
            quality = entry.get("quality", "")

            if date_ms is None or not val:
                continue
            if int(date_ms) < since_ms:
                continue
            # SMHI timestamps are Unix ms in UTC
            dt = datetime.fromtimestamp(int(date_ms) / 1000.0, tz=timezone.utc)
            ts = dt.strftime("%Y-%m-%d %H:%M:%S")

            if ts not in by_time:
                by_time[ts] = {}
            by_time[ts][col_name] = str(val)

    def _v(d: dict, k: str) -> str:
        return d.get(k, "")

    rows = []
    for ts in sorted(by_time):
        d = by_time[ts]
        rows.append({
            "time":           ts,
            "station_id":     station_id,
            "latitude":       str(fixed_lat),
            "longitude":      str(fixed_lon),
            "air_temp":       _v(d, "air_temp"),
            "dew_point_temp": "",
            "humidity":       _v(d, "humidity"),
            "wind_direction": _v(d, "wind_direction"),
            "wind_speed":     _v(d, "wind_speed"),
            "air_pressure":   _v(d, "air_pressure"),
        })

    logger.info("  %d observation hours parsed for station %s", len(rows), station_id)
    return rows
