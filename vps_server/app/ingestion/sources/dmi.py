"""DMI (Danish Meteorological Institute) Open Data observation source.

Fetches meteorological observations from the DMI metObs API for a fixed
land-based station.  Greenland stations are identified by their DMI
stationId (mostly matching WMO numbers: 04xxx series).

API docs:  https://opendatadocs.dmi.govcloud.dk/en/Data/Meteorological_Observations
Auth:      API key passed as query parameter ``api-key``.
Endpoint:  https://dmigw.govcloud.dk/v2/metObs/collections/observation/items

Output columns match the shared land-station CSV layout so the frontend
can render them with the existing ship/station plot renderer:
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

_BASE_URL  = "https://opendataapi.dmi.dk/v2/metObs"
_OBS_URL   = f"{_BASE_URL}/collections/observation/items"

# DMI parameter IDs → our column names
# Valid parameter IDs confirmed from API error response.
_PARAM_MAP = {
    "temp_dry":         "air_temp",
    "humidity_past1h":  "humidity",
    "wind_dir_past1h":  "wind_direction",
    "wind_speed_past1h":"wind_speed",
    "pressure":         "air_pressure",
}
_PARAMS = list(_PARAM_MAP.keys())

# DMI returns up to 300 000 rows per request; we use a high limit.
_PAGE_LIMIT = 300_000


def _dmi_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ArctDataCollector/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"DMI HTTP {exc.code}: {exc.reason}\n{body[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DMI request failed: {exc}") from exc


def fetch_dmi(
    station_id: str,
    fixed_lat: float,
    fixed_lon: float,
    since: datetime,
) -> list[dict]:
    """Download and parse observations from the DMI metObs API.

    Parameters
    ----------
    station_id:
        DMI station identifier, e.g. ``"04206"`` (Station Nord).
    fixed_lat:
        Fixed latitude of the station in decimal degrees N.
    fixed_lon:
        Fixed longitude of the station in decimal degrees E.
    since:
        Fetch observations at or after this UTC datetime.

    Returns
    -------
    list of dict
        One row per observation time, keyed by our standard column names.

    Raises
    ------
    RuntimeError
        If the HTTP request fails.
    """
    now = datetime.now(tz=timezone.utc)
    dt_start = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    dt_end   = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    dt_range = f"{dt_start}/{dt_end}"

    # DMI API only accepts one parameterId per request — fetch each in turn.
    by_time: dict[str, dict] = {}
    logger.info(
        "Fetching DMI observations for %s (%s → %s)",
        station_id, since.date(), now.date(),
    )
    for param, col in _PARAM_MAP.items():
        query = urllib.parse.urlencode({
            "stationId":   station_id,
            "parameterId": param,
            "datetime":    dt_range,
            "limit":       _PAGE_LIMIT,
        })
        url = f"{_OBS_URL}?{query}"
        logger.debug("  Fetching %s for %s", param, station_id)
        try:
            payload = _dmi_get(url)
        except RuntimeError as exc:
            logger.warning("  Skipping %s for %s: %s", param, station_id, exc)
            continue
        for feat in payload.get("features", []):
            props = feat.get("properties", {})
            raw_ts = props.get("observed", "")
            ts = raw_ts[:19].replace("T", " ")
            if not ts:
                continue
            val = props.get("value")
            if ts not in by_time:
                by_time[ts] = {}
            by_time[ts][col] = "" if val is None else str(val)

    # Build one row per timestamp
    def _v(d: dict, k: str) -> str:
        return d.get(k, "")

    rows = []
    for ts in sorted(by_time):
        d = by_time[ts]
        rows.append({
            "time":          ts,
            "station_id":    station_id,
            "latitude":      str(fixed_lat),
            "longitude":     str(fixed_lon),
            "air_temp":      _v(d, "air_temp"),
            "dew_point_temp": "",
            "humidity":      _v(d, "humidity"),
            "wind_direction": _v(d, "wind_direction"),
            "wind_speed":    _v(d, "wind_speed"),
            "air_pressure":  _v(d, "air_pressure"),
        })

    logger.info("  %d observation timestamps parsed for %s", len(rows), station_id)
    return rows
