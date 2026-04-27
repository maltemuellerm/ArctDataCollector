#!/usr/bin/env python3
"""
Minimal ECMWF MARS credential test.
Downloads a single field (2m temperature, analysis, one grid point area)
to verify that credentials work and the MARS API is reachable.
File is deleted after a successful download.
"""
import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    try:
        from ecmwfapi import ECMWFService
    except ImportError:
        print("ERROR: ecmwf-api-client not installed. Run: pip install ecmwf-api-client")
        return 1

    mars = ECMWFService("mars", verbose=True)

    target = Path(tempfile.mktemp(suffix=".nc"))
    print(f"\nTest target file: {target}")

    # Minimal request: IFS analysis, 2m temperature, single time step,
    # tiny 1°×1° box, NetCDF output.  Should be ~1 KB.
    try:
        mars.execute({
            "class"   : "od",
            "stream"  : "oper",
            "expver"  : "1",
            "type"    : "an",           # analysis (no lead time needed)
            "date"    : "2026-01-01",   # fixed recent date — always in archive
            "time"    : "00:00:00",
            "step"    : "0",
            "levtype" : "sfc",
            "param"   : "167",          # 2m temperature
            "area"    : "80/10/79/11",  # N/W/S/E  — 1°×1° box near Svalbard
            "grid"    : "1.0/1.0",
            "format"  : "netcdf",
        }, str(target))
    except Exception as exc:
        print(f"\nMARS request FAILED: {exc}")
        return 1

    if target.exists() and target.stat().st_size > 0:
        size = target.stat().st_size
        print(f"\n✓ SUCCESS — downloaded {size} bytes")
        target.unlink()
        print("Test file deleted.")
        return 0
    else:
        print("\nERROR: target file missing or empty after request")
        return 1


if __name__ == "__main__":
    sys.exit(main())
