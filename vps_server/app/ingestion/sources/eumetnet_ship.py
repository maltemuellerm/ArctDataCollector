"""EUMETNET eSurfMar ship CSV source.

Fetches the pre-formatted CSV from the eSurfMar download portal for a single
ship identified by its WMO call sign, cleans missing-value markers and returns
the rows as a list of dicts ready for the handler to persist.
"""

import csv
import io
import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# EUMETNET encodes missing / unavailable values as "/" in every field.
_MISSING = "/"
_MAX_RETRIES = 3
_RETRY_DELAY = 5  # seconds


def fetch_ship_csv(wmo_id: str, url_template: str) -> list[dict]:
    """Download and parse the CSV for *wmo_id*.

    Parameters
    ----------
    wmo_id:
        WMO call sign of the ship (e.g. ``"MBBJ7YM"``).
    url_template:
        URL pattern with a ``{wmo_id}`` placeholder.

    Returns
    -------
    list of dict
        Each dict represents one observation row; "/" values are replaced with
        an empty string ``""`` so downstream code never has to handle them.

    Raises
    ------
    RuntimeError
        If the HTTP request fails or the response is empty.
    """
    url = url_template.format(wmo_id=wmo_id)
    logger.info("Fetching ship data for %s from %s", wmo_id, url)

    req = urllib.request.Request(url, headers={"User-Agent": "ArctDataCollector/1.0"})
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw_bytes = response.read()
            break
        except Exception as exc:
            last_exc = exc
            logger.warning("Attempt %d/%d failed for %s: %s", attempt, _MAX_RETRIES, wmo_id, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
    else:
        raise RuntimeError(f"Failed to fetch {url} after {_MAX_RETRIES} attempts: {last_exc}") from last_exc

    text = raw_bytes.decode("utf-8", errors="replace")
    if not text.strip():
        raise RuntimeError(f"Empty response from {url}")

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        cleaned = {k.strip(): (v.strip() if v.strip() != _MISSING else "") for k, v in row.items()}
        rows.append(cleaned)

    logger.info("Fetched %d rows for %s", len(rows), wmo_id)
    return rows
