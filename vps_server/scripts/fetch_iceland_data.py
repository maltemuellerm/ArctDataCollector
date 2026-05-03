#!/usr/bin/env python3
"""Fetch Icelandic weather station observations from the IMO open data API.

Runs for all active stations in iceland_stations.yaml and writes CSV files
to data/processed/csv/iceland/.  Invoked manually or via the systemd timer.
"""

import argparse
import logging
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_DIR    = _SCRIPT_DIR.parent / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from ingestion.handlers.iceland_handler import run


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Iceland IMO station observation CSVs."
    )
    parser.add_argument("--config-dir", type=Path, default=_SCRIPT_DIR.parent / "config")
    parser.add_argument("--output-dir", type=Path, default=_SCRIPT_DIR.parent / "data" / "processed" / "csv")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    config_path = args.config_dir / "iceland_stations.yaml"
    output_dir  = args.output_dir / "iceland"
    if not config_path.exists():
        logging.error("Config not found: %s", config_path)
        sys.exit(1)
    logging.info("=== Iceland IMO fetch ===")
    run(config_path, output_dir)
    logging.info("=== Done ===")


if __name__ == "__main__":
    main()
