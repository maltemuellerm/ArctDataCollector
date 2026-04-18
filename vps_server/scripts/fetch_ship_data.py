#!/usr/bin/env python3
"""CLI entry point: fetch ship observations from EUMETNET eSurfMar.

Run manually or via the systemd timer (fetch-ship-data.timer):

    python3 fetch_ship_data.py

Optional arguments:
    --config PATH   Path to ships.yaml  (default: ../config/ships.yaml)
    --output DIR    Directory for CSV output  (default: ../data/processed/csv/ships)
    --log-level     DEBUG | INFO | WARNING  (default: INFO)
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure vps_server/app is importable regardless of working directory.
_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_DIR = _SCRIPT_DIR.parent / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from ingestion.handlers.ship_handler import run


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch EUMETNET ship observation CSVs.")
    parser.add_argument(
        "--config",
        type=Path,
        default=_SCRIPT_DIR.parent / "config" / "ships.yaml",
        help="Path to ships.yaml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_SCRIPT_DIR.parent / "data" / "processed" / "csv" / "ships",
        help="Output directory for ship CSV files",
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
    run(config_path=args.config, output_dir=args.output)


if __name__ == "__main__":
    main()
