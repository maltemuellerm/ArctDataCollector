#!/usr/bin/env python3
"""Discover land-based Frost API stations north of a given latitude threshold.

Queries the MET Norway Frost API /sources endpoint for fixed SensorSystem
stations and prints a table of candidate source IDs, names and coordinates.

Usage:
    python3 discover_frost_stations.py
    python3 discover_frost_stations.py --min-lat 70
    python3 discover_frost_stations.py --min-lat 65 --country NO
    python3 discover_frost_stations.py --log-level DEBUG

Credentials are read from  config/secrets.yaml  (frost.client_id /
frost.client_secret).
"""

import argparse
import json
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent
_SECRETS_FILE = _SCRIPT_DIR.parent / "config" / "secrets.yaml"
_SOURCES_URL = "https://frost.met.no/sources/v0.jsonld"

# Station types that correspond to land-based fixed installations.
_LAND_TYPES = {"SensorSystem"}


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
            f"Frost HTTP {exc.code}: {exc.reason}\n{body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Frost request failed: {exc}") from exc


def fetch_sources(headers: dict, country: str | None, min_lat: float) -> list[dict]:
    """Return all SensorSystem sources north of *min_lat* via the Frost sources API."""
    params: dict[str, str] = {
        "types": "SensorSystem",
        "fields": "id,name,geometry,country,municipality,county,stationHolders",
    }
    if country:
        params["country"] = country.upper()

    url = f"{_SOURCES_URL}?{urllib.parse.urlencode(params)}"
    logger.debug("GET %s", url)
    payload = _frost_get(url, headers)

    stations = []
    for src in payload.get("data", []):
        geom = src.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        if lat >= min_lat:
            stations.append(
                {
                    "id": src.get("id", ""),
                    "name": src.get("name", ""),
                    "lat": lat,
                    "lon": lon,
                    "country": src.get("country", ""),
                    "municipality": src.get("municipality", ""),
                    "county": src.get("county", ""),
                }
            )
    return stations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-lat",
        type=float,
        default=65.0,
        metavar="DEG",
        help="Minimum latitude (default: 65.0°N)",
    )
    parser.add_argument(
        "--country",
        default=None,
        metavar="CODE",
        help="ISO-3166 country code filter, e.g. NO (optional)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s  %(message)s",
        stream=sys.stderr,
    )

    # Load credentials
    if not _SECRETS_FILE.exists():
        logger.error("secrets.yaml not found at %s", _SECRETS_FILE)
        sys.exit(1)

    with _SECRETS_FILE.open() as fh:
        secrets = yaml.safe_load(fh)

    frost_cfg = secrets.get("frost", {})
    client_id = frost_cfg.get("client_id", "")
    client_secret = frost_cfg.get("client_secret", "")
    if not client_id or not client_secret:
        logger.error("frost.client_id / frost.client_secret missing in secrets.yaml")
        sys.exit(1)

    headers = _auth_header(client_id, client_secret)

    logger.info(
        "Querying Frost sources API (types=SensorSystem, min_lat=%.1f%s) …",
        args.min_lat,
        f", country={args.country}" if args.country else "",
    )

    stations = fetch_sources(headers, args.country, args.min_lat)
    stations.sort(key=lambda s: (-s["lat"], s["id"]))

    if not stations:
        logger.warning("No land-based stations found for the given filters.")
        sys.exit(0)

    logger.info("Found %d station(s).", len(stations))

    # Print human-readable table to stdout
    col_id   = max(len(s["id"])          for s in stations)
    col_name = max(len(s["name"])        for s in stations)
    col_mun  = max(len(s["municipality"]) for s in stations)
    col_id   = max(col_id,   10)
    col_name = max(col_name, 4)
    col_mun  = max(col_mun,  12)

    header = (
        f"{'Station ID':<{col_id}}  "
        f"{'Name':<{col_name}}  "
        f"{'  Lat':>7}  "
        f"{'  Lon':>8}  "
        f"{'Country':<7}  "
        f"{'Municipality':<{col_mun}}"
    )
    print(header)
    print("-" * len(header))
    for s in stations:
        print(
            f"{s['id']:<{col_id}}  "
            f"{s['name']:<{col_name}}  "
            f"{s['lat']:>7.3f}  "
            f"{s['lon']:>8.3f}  "
            f"{s['country']:<7}  "
            f"{s['municipality']:<{col_mun}}"
        )


if __name__ == "__main__":
    main()
