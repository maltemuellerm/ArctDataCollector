"""Sea Ice Portal thermistor chain buoy source.

Downloads the ZIP file for a given buoy_id and extracts:
  - *_TS.csv                       2-hourly: lat, lon, pressure, air temp, tilt
  - *_TEMP_raw+filterflag.csv      6-hourly: T1 … T240 thermistor profile

Returns (ts_rows, temp_rows) as lists of flat dicts.
"""

import csv
import io
import logging
import zipfile

import requests

logger = logging.getLogger(__name__)

_SUFFIX_TS   = "_TS.csv"
_SUFFIX_TEMP = "_TEMP_raw+filterflag.csv"


def fetch_thermistor(buoy_id: str, base_url: str) -> tuple[list[dict], list[dict]]:
    """Download and parse thermistor buoy data for *buoy_id*.

    Returns
    -------
    (ts_rows, temp_rows)
        Both are lists of flat dicts ready for CSV writing.
    """
    url = f"{base_url.rstrip('/')}/{buoy_id}_data.zip"
    logger.info("Fetching thermistor buoy %s from %s", buoy_id, url)

    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        ts_file   = next((n for n in names if n.endswith(_SUFFIX_TS)),   None)
        temp_file = next((n for n in names if n.endswith(_SUFFIX_TEMP)), None)

        if not ts_file:
            raise RuntimeError(f"No *_TS.csv found in ZIP for buoy {buoy_id}")
        if not temp_file:
            raise RuntimeError(f"No *_TEMP_raw+filterflag.csv found in ZIP for buoy {buoy_id}")

        ts_rows   = _parse_csv(zf.read(ts_file).decode("utf-8", errors="replace"))
        temp_rows = _parse_csv(zf.read(temp_file).decode("utf-8", errors="replace"))

    logger.info("Buoy %s: %d TS rows, %d TEMP rows", buoy_id, len(ts_rows), len(temp_rows))
    return ts_rows, temp_rows


def _parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.strip()))
    return list(reader)
