"""MET Norway Frost API land-station observation source.

Fetches met observations for a fixed land-based station identified by its
Frost station number (e.g. SN99910) and writes rows with fixed coordinates
from the station registry (land stations do not report position as observations).

Output columns match the ship CSV layout so the frontend can render them
with the same plot renderer.

Frost API docs: https://frost.met.no/howto.html
Authentication: HTTP Basic Auth — client_id as username, client_secret as password.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Meteorological elements available at fixed land stations.
_ELEMENTS_LAND = (
    "air_temperature,dew_point_temperature,"
    "wind_speed,wind_from_direction,"
    "air_pressure_at_sea_level,relative_humidity"
)
_BASE_URL = "https://frost.met.no/observations/v0.jsonld"


def _auth_header(client_id: str, client_secret: str) -> dict:
    token = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {"Authorization": f"Basic {token}", "User-Agent": "ArctDataCollector/1.0"}


def _frost_get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Frost HTTP {exc.code}: {exc.reason}\n{body[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Frost request failed: {exc}") from exc


def fetch_frost_land(
    station_id: str,
    fixed_lat: float,
    fixed_lon: float,
    client_id: str,
    client_secret: str,
    since: datetime | None = None,
) -> list[dict]:
    """Download and parse met observations from the Frost API for a land station.

    Parameters
    ----------
    station_id:
        Frost station identifier, e.g. ``"SN99910"``.
    fixed_lat:
        Fixed latitude of the station (decimal degrees N).
    fixed_lon:
        Fixed longitude of the station (decimal degrees E).
    client_id:
        Frost API client ID (HTTP Basic Auth username).
    client_secret:
        Frost API client secret (HTTP Basic Auth password).
    since:
        Fetch observations at or after this UTC datetime.

    Returns
    -------
    list of dict
        One row per observation time, with columns:
        time, station_id, latitude, longitude,
        air_temp, dew_point_temp, humidity,
        wind_direction, wind_speed, air_pressure.

    Raises
    ------
    RuntimeError
        If the HTTP request fails.
    """
    if since is None:
        raise ValueError("'since' is required for land stations")

    now = datetime.now(tz=timezone.utc)
    ref_time = (
        since.strftime("%Y-%m-%dT%H:%M:%SZ")
        + "/"
        + now.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    headers = _auth_header(client_id, client_secret)
    params = (
        f"sources={station_id}"
        f"&referencetime={urllib.parse.quote(ref_time, safe='/:')}"
        f"&elements={_ELEMENTS_LAND}"
        "&limit=100000"
    )
    logger.info(
        "Fetching Frost land observations for %s (%s → %s)",
        station_id, since.date(), now.date(),
    )
    payload = _frost_get(f"{_BASE_URL}?{params}", headers)

    def _fmt(v) -> str:
        return "" if v is None else str(v)

    rows = []
    for record in payload.get("data", []):
        ref = record.get("referenceTime", "")
        ts  = ref[:19].replace("T", " ") if len(ref) >= 19 else ref
        obs = {o["elementId"]: o.get("value") for o in record.get("observations", [])}

        rows.append({
            "time":           ts,
            "station_id":     station_id,
            "latitude":       _fmt(fixed_lat),
            "longitude":      _fmt(fixed_lon),
            "air_temp":       _fmt(obs.get("air_temperature")),
            "dew_point_temp": _fmt(obs.get("dew_point_temperature")),
            "humidity":       _fmt(obs.get("relative_humidity")),
            "wind_direction": _fmt(obs.get("wind_from_direction")),
            "wind_speed":     _fmt(obs.get("wind_speed")),
            "air_pressure":   _fmt(obs.get("air_pressure_at_sea_level")),
        })

    logger.info("Fetched %d rows for %s", len(rows), station_id)
    return rows
