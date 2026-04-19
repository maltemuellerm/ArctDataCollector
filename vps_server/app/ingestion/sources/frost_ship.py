"""MET Norway Frost API ship observation source.

Fetches observations (position + met elements) for a ship identified by its
Frost station number (e.g. SN77035) and converts them to the same CSV column
layout used by the eSurfMar ship source so the handler and frontend can treat
all ships uniformly.

Frost API docs: https://frost.met.no/howto.html
Authentication: HTTP Basic Auth — client_id as username, client_secret as password.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Main meteorological + position elements (all PT10M).
_ELEMENTS_MAIN = (
    "latitude,longitude,"
    "air_temperature,dew_point_temperature,"
    "wind_speed,wind_from_direction,"
    "air_pressure_at_sea_level,sea_surface_temperature,"
    "relative_humidity"
)
# Solar irradiance (PT1M — fetched separately to avoid dropping main rows).
_ELEMENT_RADIATION = "mean(solar_irradiance PT1M)"
_BASE_URL = "https://frost.met.no/observations/v0.jsonld"


def _auth_header(client_id: str, client_secret: str) -> dict:
    token = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {"Authorization": f"Basic {token}", "User-Agent": "ArctDataCollector/1.0"}


def _frost_get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Frost request failed: {exc}") from exc


def _ts_key(ref: str) -> tuple | None:
    """Extract (year, month, day, hour, minute) from a Frost referenceTime string."""
    try:
        return (
            int(ref[0:4]), int(ref[5:7]), int(ref[8:10]),
            int(ref[11:13]), int(ref[14:16]),
        )
    except (ValueError, IndexError):
        return None


def _fetch_radiation(station_id: str, client_id: str, client_secret: str,
                     ref_time: str) -> dict:
    """Return {(y,mo,d,h,m): irradiance_W_m2} for all available solar records."""
    params = (
        f"sources={station_id}"
        f"&referencetime={urllib.parse.quote(ref_time, safe='/:')}"
        f"&elements={urllib.parse.quote(_ELEMENT_RADIATION, safe='()')}"
        "&limit=100000"
    )
    try:
        payload = _frost_get(
            f"{_BASE_URL}?{params}",
            _auth_header(client_id, client_secret),
        )
    except RuntimeError as exc:
        logger.warning("Solar irradiance unavailable for %s: %s", station_id, exc)
        return {}

    solar: dict = {}
    for record in payload.get("data", []):
        key = _ts_key(record.get("referenceTime", ""))
        if key is None:
            continue
        for obs in record.get("observations", []):
            if "solar_irradiance" in obs.get("elementId", ""):
                solar[key] = obs.get("value")
                break
    logger.info("Solar irradiance: %d records for %s", len(solar), station_id)
    return solar


def fetch_frost_ship(
    station_id: str,
    wmo_id: str,
    client_id: str,
    client_secret: str,
    since: datetime | None = None,
) -> list[dict]:
    """Download and parse observations from the Frost API.

    Parameters
    ----------
    station_id:
        Frost station identifier, e.g. ``"SN77035"``.
    wmo_id:
        Ship call sign written into the ``WMO id`` CSV column (e.g. ``"3YYQ"``).
    client_id:
        Frost API client ID (HTTP Basic Auth username).
    client_secret:
        Frost API client secret (HTTP Basic Auth password).
    since:
        Fetch observations at or after this UTC datetime.
        Defaults to 30 days ago.

    Returns
    -------
    list of dict
        Rows using the same column names as eSurfMar ship CSVs so both sources
        can be handled identically by the ship handler and frontend.

    Raises
    ------
    RuntimeError
        If the HTTP request fails.
    """
    if since is None:
        since = datetime.now(tz=timezone.utc) - timedelta(days=30)
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
        f"&elements={_ELEMENTS_MAIN}"
        "&limit=100000"
    )
    logger.info(
        "Fetching Frost observations for %s (%s → %s)",
        station_id, since.date(), now.date(),
    )
    payload = _frost_get(f"{_BASE_URL}?{params}", headers)

    # Solar irradiance — separate fetch, joined by timestamp key.
    solar = _fetch_radiation(station_id, client_id, client_secret, ref_time)

    def _fmt(v) -> str:
        return "" if v is None else str(v)

    rows = []
    for record in payload.get("data", []):
        ref = record.get("referenceTime", "")
        ts  = ref[:19].replace("T", " ") if len(ref) >= 19 else ref

        obs = {o["elementId"]: o.get("value") for o in record.get("observations", [])}

        lat = obs.get("latitude")
        lon = obs.get("longitude")
        if lat is None or lon is None:
            continue

        key       = _ts_key(ref)
        solar_val = solar.get(key) if key else None

        rows.append({
            "date":                            ts,
            "WMO id":                          wmo_id,
            "Latitude (deg)":                  _fmt(lat),
            "Longitude (deg)":                 _fmt(lon),
            "Sea level Pressure (hPa)":        _fmt(obs.get("air_pressure_at_sea_level")),
            "Air temperature (°C)":            _fmt(obs.get("air_temperature")),
            "Dew point temperature (°C)":      _fmt(obs.get("dew_point_temperature")),
            "Humidity (%)":                    _fmt(obs.get("relative_humidity")),
            "Wind direction (deg)":            _fmt(obs.get("wind_from_direction")),
            "Wind speed (m/s)":                _fmt(obs.get("wind_speed")),
            "SST (°C)":                        _fmt(obs.get("sea_surface_temperature")),
            "Solar irradiance (W/m²)":         _fmt(solar_val),
        })

    logger.info("Fetched %d rows for %s", len(rows), station_id)
    return rows
