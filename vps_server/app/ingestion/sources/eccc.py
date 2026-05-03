"""Environment and Climate Change Canada (ECCC) MSC SWOB-realtime source.

Fetches surface weather observations from the MSC GeoMet OGC Features API for
fixed Canadian Arctic land stations.

API:    https://api.weather.gc.ca/collections/swob-realtime/items
Auth:   None (open data).
Filter: bbox ±0.3° around station lat/lon + datetime range.
Notes:  - Observations are minute-level; we aggregate to hourly.
        - Wind speed is reported in km/h; we convert to m/s.

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

_BASE_URL  = "https://api.weather.gc.ca/collections/swob-realtime/items"
_PAGE_LIMIT = 100_000   # request up to 100k records per page
_BBOX_PAD   = 0.3       # degrees (±) around station coords


def _eccc_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ArctDataCollector/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ECCC HTTP {exc.code}: {exc.reason}\n{body[:400]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ECCC request failed: {exc}") from exc


def _fv(props: dict, *keys) -> str:
    """Return the first non-None value from props for the given keys."""
    for k in keys:
        v = props.get(k)
        if v is not None:
            return str(v)
    return ""


def fetch_eccc(
    station_id: str,
    fixed_lat: float,
    fixed_lon: float,
    since: datetime,
) -> list[dict]:
    """Download and parse hourly observations from the ECCC SWOB-realtime API.

    Parameters
    ----------
    station_id:
        WMO synop station number (e.g. ``"71355"`` for Alert).
    fixed_lat / fixed_lon:
        Fixed station coordinates used for bbox filtering.
    since:
        Fetch observations at or after this UTC datetime.

    Returns
    -------
    list of dict
        One row per UTC hour, keyed by our standard column names.
    """
    now = datetime.now(tz=timezone.utc)
    dt_start = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    dt_end   = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    bbox = (
        f"{fixed_lon - _BBOX_PAD:.4f},{fixed_lat - _BBOX_PAD:.4f},"
        f"{fixed_lon + _BBOX_PAD:.4f},{fixed_lat + _BBOX_PAD:.4f}"
    )

    logger.info(
        "Fetching ECCC SWOB for %s (%s → %s)",
        station_id, since.date(), now.date(),
    )

    # Paginate through all minute-level records
    features = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "bbox":     bbox,
            "datetime": f"{dt_start}/{dt_end}",
            "limit":    _PAGE_LIMIT,
            "offset":   offset,
        })
        url = f"{_BASE_URL}?{params}"
        logger.debug("  Requesting offset=%d for %s", offset, station_id)
        payload = _eccc_get(url)
        batch = payload.get("features", [])
        features.extend(batch)
        total = payload.get("numberMatched", 0)
        if offset + len(batch) >= total or not batch:
            break
        offset += len(batch)

    logger.info("  %d raw minute records fetched for %s", len(features), station_id)

    # Aggregate to hourly: group by UTC hour, pick last record in each bucket.
    # Use 1-hour averaged fields where available, else instant fields.
    by_hour: dict[str, dict] = {}
    for feat in features:
        props = feat.get("properties", {})
        raw_ts = props.get("date_tm-value") or props.get("obs_date_tm") or ""
        if not raw_ts:
            continue
        # bucket = "YYYY-MM-DDTHH"
        hour_key = raw_ts[:13]
        by_hour[hour_key] = props  # last record in this hour wins

    rows = []
    for hour_key in sorted(by_hour):
        p = by_hour[hour_key]
        ts = hour_key + ":00:00"  # e.g. "2026-04-01T02:00:00"
        ts = ts.replace("T", " ")

        # Wind speed: prefer 10-min or 1-hr avg; convert km/h → m/s
        ws_raw = _fv(p, "avg_wnd_spd_10m_pst1hr", "avg_wnd_spd_10m_pst10mts",
                     "avg_wnd_spd_10m_pst2mts", "avg_wnd_spd_10m_pst1mt")
        if ws_raw:
            try:
                ws_ms = round(float(ws_raw) / 3.6, 2)
                wind_speed = str(ws_ms)
            except ValueError:
                wind_speed = ""
        else:
            wind_speed = ""

        rows.append({
            "time":          ts,
            "station_id":    station_id,
            "latitude":      str(fixed_lat),
            "longitude":     str(fixed_lon),
            "air_temp":      _fv(p, "avg_air_temp_pst1hr", "air_temp"),
            "dew_point_temp": _fv(p, "avg_dwpt_temp_pst1hr", "dwpt_temp"),
            "humidity":      _fv(p, "avg_rel_hum_pst1hr", "rel_hum"),
            "wind_direction": _fv(p, "avg_wnd_dir_10m_pst1hr",
                                  "avg_wnd_dir_10m_pst10mts",
                                  "avg_wnd_dir_10m_pst2mts",
                                  "avg_wnd_dir_10m_pst1mt"),
            "wind_speed":    wind_speed,
            "air_pressure":  _fv(p, "stn_pres"),
        })

    logger.info("  %d hourly rows assembled for %s", len(rows), station_id)
    return rows
