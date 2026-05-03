"""Finnish Meteorological Institute (FMI) Open Data WFS source.

Fetches surface weather observations from the FMI WFS endpoint for
Arctic Finnish stations (Utsjoki, Saariselkä, Sodankylä, Enontekiö, etc.).

API:    https://opendata.fmi.fi/wfs
Auth:   None (open data, no API key required).
Docs:   https://en.ilmatieteenlaitos.fi/open-data-manual
Query:  storedQueryId = fmi::observations::weather::hourly::simple
        fmisid = <station id>

Output CSV columns (shared land-station layout):
    time, station_id, latitude, longitude,
    air_temp, dew_point_temp, humidity,
    wind_direction, wind_speed, air_pressure
"""

import logging
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_WFS_URL = "https://opendata.fmi.fi/wfs"

# FMI WFS maximum allowed query window
_MAX_CHUNK_HOURS = 720  # 30 days (API enforces ≤ 744 h; leave margin)

# FMI hourly storedquery parameter names → our column names
# (fmi::observations::weather::hourly::simple uses WMO-style coded names)
_PARAM_MAP = {
    "TA_PT1H_AVG":  "air_temp",        # air temperature 1-h average (°C)
    "RH_PT1H_AVG":  "humidity",        # relative humidity 1-h average (%)
    "WD_PT1H_AVG":  "wind_direction",  # wind direction 1-h average (°)
    "WS_PT1H_AVG":  "wind_speed",      # wind speed 1-h average (m/s)
    "PA_PT1H_AVG":  "air_pressure",    # air pressure 1-h average (hPa)
    # Legacy / alternative names kept for compatibility
    "Air temperature":       "air_temp",
    "Dew-point temperature": "dew_point_temp",
    "Relative humidity":     "humidity",
    "Wind direction":        "wind_direction",
    "Wind speed":            "wind_speed",
    "Air pressure":          "air_pressure",
    "temperature":           "air_temp",
    "dewPoint":              "dew_point_temp",
    "relativeHumidity":      "humidity",
    "windDirection":         "wind_direction",
    "windSpeed":             "wind_speed",
    "pressure":              "air_pressure",
}

_NS = {
    "wfs":   "http://www.opengis.net/wfs/2.0",
    "gml":   "http://www.opengis.net/gml/3.2",
    "BsWfs": "http://xml.fmi.fi/schema/wfs/2.0",
}


def _fmi_get(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "ArctDataCollector/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"FMI HTTP {exc.code}: {exc.reason}\n{body[:600]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"FMI request failed: {exc}") from exc


def fetch_finland(
    station_id: str,
    fixed_lat: float,
    fixed_lon: float,
    since: datetime,
) -> list[dict]:
    """Download and parse observations from the FMI WFS.

    Parameters
    ----------
    station_id:
        FMI station ID (FMISID), e.g. ``"101976"`` (Utsjoki).
    fixed_lat / fixed_lon:
        Station coordinates.
    since:
        Fetch observations at or after this UTC datetime.

    Returns
    -------
    list of dict
        One row per observation hour.
    """
    now = datetime.now(tz=timezone.utc)

    logger.info(
        "Fetching FMI observations for FMISID %s (%s → %s)",
        station_id, since.date(), now.date(),
    )

    # FMI WFS enforces a ≤744-hour window per request.  Split into chunks.
    chunk_delta = timedelta(hours=_MAX_CHUNK_HOURS)
    all_rows: dict[str, dict] = {}  # keyed by timestamp string

    chunk_start = since
    while chunk_start < now:
        chunk_end = min(chunk_start + chunk_delta, now)
        dt_start  = chunk_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        dt_end    = chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ")

        params = urllib.parse.urlencode({
            "service":        "WFS",
            "version":        "2.0.0",
            "request":        "getFeature",
            "storedquery_id": "fmi::observations::weather::hourly::simple",
            "fmisid":         station_id,
            "starttime":      dt_start,
            "endtime":        dt_end,
            "timestep":       "60",
        })
        url = f"{_WFS_URL}?{params}"
        logger.debug("  Chunk %s → %s  URL: %s", dt_start, dt_end, url)

        try:
            xml_text = _fmi_get(url)
        except RuntimeError as exc:
            logger.error("  Failed for FMISID %s chunk %s: %s", station_id, dt_start, exc)
            chunk_start = chunk_end
            continue

        # Parse WFS BsWfs response for this chunk
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.error("  XML parse error for %s chunk %s: %s", station_id, dt_start, exc)
            chunk_start = chunk_end
            continue

        for member in root.iter("{http://xml.fmi.fi/schema/wfs/2.0}BsWfsElement"):
            ts_el  = member.find("{http://xml.fmi.fi/schema/wfs/2.0}Time")
            par_el = member.find("{http://xml.fmi.fi/schema/wfs/2.0}ParameterName")
            val_el = member.find("{http://xml.fmi.fi/schema/wfs/2.0}ParameterValue")

            if ts_el is None or par_el is None or val_el is None:
                continue
            raw_ts = (ts_el.text or "").strip()
            param  = (par_el.text or "").strip()
            val    = (val_el.text or "").strip()

            ts = raw_ts[:19].replace("T", " ")
            if not ts or val in ("NaN", "", "nan"):
                continue
            col = _PARAM_MAP.get(param)
            if not col:
                continue
            if ts not in all_rows:
                all_rows[ts] = {}
            all_rows[ts][col] = val

        chunk_start = chunk_end

    def _v(d: dict, k: str) -> str:
        return d.get(k, "")

    rows = []
    for ts in sorted(all_rows):
        d = all_rows[ts]
        rows.append({
            "time":           ts,
            "station_id":     station_id,
            "latitude":       str(fixed_lat),
            "longitude":      str(fixed_lon),
            "air_temp":       _v(d, "air_temp"),
            "dew_point_temp": _v(d, "dew_point_temp"),
            "humidity":       _v(d, "humidity"),
            "wind_direction": _v(d, "wind_direction"),
            "wind_speed":     _v(d, "wind_speed"),
            "air_pressure":   _v(d, "air_pressure"),
        })

    logger.info("  %d observation hours parsed for FMISID %s", len(rows), station_id)
    return rows
