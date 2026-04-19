#!/usr/bin/env python3
"""CLI entry point: fetch IABP buoy time-series data.

    python3 fetch_iabp_data.py
    python3 fetch_iabp_data.py --log-level DEBUG
"""

import argparse
import logging
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_DIR    = _SCRIPT_DIR.parent / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from ingestion.handlers.iabp_handler import run


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch IABP buoy data from iabp.apl.uw.edu.")
    parser.add_argument("--config", type=Path,
                        default=_SCRIPT_DIR.parent / "config" / "iabp_buoys.yaml")
    parser.add_argument("--output", type=Path,
                        default=_SCRIPT_DIR.parent / "data" / "processed" / "csv" / "iabp")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    run(config_path=args.config, csv_dir=args.output)


if __name__ == "__main__":
    main()
