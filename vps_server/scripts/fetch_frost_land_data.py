#!/usr/bin/env python3
"""Fetch land-based station observations from the MET Norway Frost API.

Runs for all three categories (Svalbard, Northern Norway, Offshore platforms)
in sequence.  Invoked manually or via the systemd timer:

    python3 fetch_frost_land_data.py

Optional arguments:
    --config-dir DIR    Directory containing the YAML station configs
                        (default: ../config)
    --output-dir DIR    Root directory for CSV output
                        (default: ../data/processed/csv)
    --categories        Comma-separated subset: svalbard,north_norway,offshore
                        (default: all three)
    --log-level         DEBUG | INFO | WARNING  (default: INFO)
"""

import argparse
import logging
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_DIR    = _SCRIPT_DIR.parent / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from ingestion.handlers.frost_land_handler import run

# Mapping: category key → (config filename, output sub-directory)
_CATEGORIES = {
    "svalbard":     ("svalbard_stations.yaml",     "svalbard"),
    "north_norway": ("north_norway_stations.yaml", "north_norway"),
    "offshore":     ("offshore_stations.yaml",     "offshore"),
    "norway_buoys": ("norway_buoys.yaml",          "norway_buoys"),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Frost land-station observation CSVs (all categories)."
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=_SCRIPT_DIR.parent / "config",
        help="Directory containing svalbard_stations.yaml etc.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_SCRIPT_DIR.parent / "data" / "processed" / "csv",
        help="Root directory for CSV output (sub-dirs per category are created here)",
    )
    parser.add_argument(
        "--categories",
        default="svalbard,north_norway,offshore,norway_buoys",
        help="Comma-separated list of categories to process",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    selected = [c.strip() for c in args.categories.split(",") if c.strip()]
    for key in selected:
        if key not in _CATEGORIES:
            logging.warning("Unknown category %r — skipping", key)
            continue
        cfg_name, out_sub = _CATEGORIES[key]
        config_path = args.config_dir / cfg_name
        output_dir  = args.output_dir / out_sub
        logging.info("--- Processing category: %s ---", key)
        run(config_path=config_path, output_dir=output_dir)


if __name__ == "__main__":
    main()
