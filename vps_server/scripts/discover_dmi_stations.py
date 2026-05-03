#!/usr/bin/env python3
"""Discover DMI (Danish Meteorological Institute) weather stations in the Arctic.

Queries the DMI Open Data /metObs/collections/station/items endpoint and
filters for stations north of a given latitude threshold.

Requirements:
  - DMI API key (register free at https://opendatadocs.dmi.govcloud.dk/en/Authentication)

Usage:
    python3 discover_dmi_stations.py --api-key YOUR_KEY
    python3 discover_dmi_stations.py --api-key YOUR_KEY --min-lat 65
    python3 discover_dmi_stations.py --api-key YOUR_KEY --min-lat 60 --country GL

DMI station IDs follow WMO numbering; Greenland stations are 04xxx series.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_BASE_URL = "https://opendataapi.dmi.dk/v2/metObs"


def _get(url: str) -> dict:
    full = f"{url}?limit=1000"
    req = urllib.request.Request(full, headers={"User-Agent": "ArctDataCollector/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {exc.reason}\n{body[:400]}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover DMI Arctic weather stations.")
    parser.add_argument("--min-lat", type=float, default=65.0,
                        help="Minimum latitude filter (default: 65.0)")
    parser.add_argument("--country", default=None,
                        help="Filter by country code, e.g. GL for Greenland, DK for Denmark")
    parser.add_argument("--active-only", action="store_true", default=True,
                        help="Only show currently active stations (default: true)")
    args = parser.parse_args()

    data = _get(f"{_BASE_URL}/collections/station/items")
    features = data.get("features", [])
    print(f"Total stations returned: {len(features)}", file=sys.stderr)

    stations = []
    for feat in features:
        props = feat.get("properties", {})
        geom  = feat.get("geometry") or {}
        coords = geom.get("coordinates", [None, None])
        lon, lat = (float(coords[0]) if coords[0] is not None else None,
                    float(coords[1]) if coords[1] is not None else None)

        if lat is None or lon is None:
            continue
        if lat < args.min_lat:
            continue
        if args.country and props.get("country", "").upper() != args.country.upper():
            continue
        if args.active_only:
            status = props.get("operationTo", None)
            # operationTo is None/null for active stations; if set, station is closed
            if status is not None:
                continue

        stations.append({
            "station_id":  props.get("stationId", ""),
            "name":        props.get("name", ""),
            "latitude":    lat,
            "longitude":   lon,
            "country":     props.get("country", ""),
            "wmo_id":      props.get("wmoStationId", ""),
            "type":        props.get("type", ""),
            "operation_from": props.get("operationFrom", ""),
        })

    stations.sort(key=lambda s: -s["latitude"])

    print(f"\nFound {len(stations)} active stations north of {args.min_lat}°N"
          + (f" in {args.country}" if args.country else "") + ":\n")
    print(f"{'Station ID':<14} {'WMO':^8} {'Lat':>7} {'Lon':>8}  {'Country':^4}  Name")
    print("-" * 80)
    for s in stations:
        print(
            f"{s['station_id']:<14} {(s['wmo_id'] or '-'):^8}"
            f" {s['latitude']:>7.3f} {s['longitude']:>8.3f}"
            f"  {s['country']:^4}  {s['name']}"
        )

    # Write YAML skeleton for easy copy-paste into config
    yaml_path = Path(__file__).parent.parent / "config" / "greenland_stations_discovered.yaml"
    lines = ["stations:\n"]
    for s in stations:
        lines.append(
            f"  - station_id: \"{s['station_id']}\"\n"
            f"    name: \"{s['name']}\"\n"
            f"    latitude: {s['latitude']:.4f}\n"
            f"    longitude: {s['longitude']:.4f}\n"
            f"    active: true\n"
            f"    # WMO: {s['wmo_id'] or 'n/a'}  country: {s['country']}\n\n"
        )
    yaml_path.write_text("".join(lines), encoding="utf-8")
    print(f"\nYAML skeleton written to: {yaml_path}")


if __name__ == "__main__":
    main()
