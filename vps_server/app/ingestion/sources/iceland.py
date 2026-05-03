"""Icelandic Meteorological Office (IMO / Veðurstofa) open data source.

Fetches surface weather observations from the IMO Weather API.

API:    https://api.vedur.is/weather/observations/aws/{aggregation}
Auth:   None (open access).
Docs:   https://api.vedur.is/  (Swagger UI)

Station IDs are IMO station numbers (integer strings).

Output CSV columns (shared land-station layout):
    time, station_id, latitude, longitude,
    air_temp, dew_point_temp, humidity,
    wind_direction, wind_speed, air_pressure
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_AWS_URL   = "https://api.vedur.is/weather/observations/aws/hour"
_SYNOP_URL = "https://api.vedur.is/weather/observations/synop/clock"


def _imo_get(url: str) -> list:
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
            f"IMO HTTP {exc.code}: {exc.reason}\n{body[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"IMO request failed: {exc}") from exc


def fetch_iceland(
    station_id: str,
    fixed_lat: float,
    fixed_lon: float,
    since: datetime,
) -> list[dict]:
    """Download and parse observations from the IMO Weather API.

    Parameters
    ----------
    station_id:
        IMO station number string, e.g. ``"3976"`` (Grímsey).
    fixed_lat / fixed_lon:
        Station coordinates.
    since:
        Fetch observations at or after this UTC datetime.

    Returns
    -------
    list of dict
        One row per observation hour, keyed by shared land-station column names.
    """
    now = datetime.now(tz=timezone.utc)
    day_from = since.strftime("%Y-%m-%d")
    day_to   = now.strftime("%Y-%m-%d")

    logger.info(
        "Fetching IMO observations for station %s (%s → %s)",
        station_id, day_from, day_to,
    )

    params = urllib.parse.urlencode({
        "station_id": station_id,
        "day_from":   day_from,
        "day_to":     day_to,
    })

    # Try AWS hourly endpoint first (works for automatic/AWS-type stations).
    # Fall back to synop/clock for manned/urban stations that are not in the AWS network.
    records = None
    for base_url in (_AWS_URL, _SYNOP_URL):
        url = f"{base_url}?{params}"
        logger.debug("  URL: %s", url)
        try:
            data = _imo_get(url)
        except RuntimeError as exc:
            logger.debug("  %s failed: %s", base_url, exc)
            continue
        if isinstance(data, list) and len(data) > 0:
            records = data
            break
        # {"message": "No data found."} — try next endpoint
    if records is None:
        logger.warning("  No data from any endpoint for station %s", station_id)
        return []

    # Response fields (lowercase):
    #   t   = air temperature (°C)
    #   td  = dew point temperature (°C)
    #   rh  = relative humidity (%)
    #   f   = wind speed (m/s)
    #   d   = wind direction (degrees)
    #   p   = mean sea-level pressure (hPa)
    def _v(rec: dict, key: str) -> str:
        val = rec.get(key)
        if val is None or val == "":
            return ""
        try:
            # Guard against NaN
            if float(val) != float(val):
                return ""
        except (TypeError, ValueError):
            return ""
        return str(val)

    rows = []
    for rec in records:
        raw_ts = rec.get("time", "")
        if not raw_ts:
            continue
        ts = raw_ts[:19].replace("T", " ")
        rows.append({
            "time":           ts,
            "station_id":     station_id,
            "latitude":       str(fixed_lat),
            "longitude":      str(fixed_lon),
            "air_temp":       _v(rec, "t"),
            "dew_point_temp": _v(rec, "td"),
            "humidity":       _v(rec, "rh"),
            "wind_direction": _v(rec, "d"),
            "wind_speed":     _v(rec, "f"),
            "air_pressure":   _v(rec, "p"),
        })

    logger.info("  %d observation hours parsed for station %s", len(rows), station_id)
    return rows

