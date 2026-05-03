#!/usr/bin/env python3
"""
Minimal ECMWF MARS credential test.
Downloads a single field (2m temperature, analysis, one grid point area)
to verify that credentials work and the MARS API is reachable.
Also probes the experimental IFS run archived under expver "80"
(typically class "rd" for Research & Development).
Files are deleted after successful downloads.
"""
import sys
import tempfile
from pathlib import Path


def _try_request(mars, request: dict, label: str) -> bool:
    """Execute a MARS request and return True on success."""
    target = Path(tempfile.mktemp(suffix=".nc"))
    print(f"\n[{label}] Target file: {target}")
    try:
        mars.execute(request, str(target))
    except Exception as exc:
        print(f"[{label}] MARS request FAILED: {exc}")
        return False

    if target.exists() and target.stat().st_size > 0:
        size = target.stat().st_size
        print(f"[{label}] ✓ SUCCESS — downloaded {size} bytes")
        target.unlink()
        return True
    else:
        print(f"[{label}] ERROR: target file missing or empty after request")
        if target.exists():
            target.unlink()
        return False


# Common parameters shared by all test requests.
_BASE = {
    "stream"  : "oper",
    "type"    : "an",           # analysis (no lead time needed)
    "date"    : "2026-01-01",   # fixed recent date — always in archive
    "time"    : "00:00:00",
    "step"    : "0",
    "levtype" : "sfc",
    "param"   : "167",          # 2m temperature
    "area"    : "80/10/79/11",  # N/W/S/E  — 1°×1° box near Svalbard
    "grid"    : "1.0/1.0",
    "format"  : "netcdf",
}

# Test cases: (label, class, expver)
_TESTS = [
    ("Operational IFS (od / expver=1)",          "od", "1"),
    ("Experimental IFS rd class (rd / expver=80)", "rd", "80"),
    ("Experimental IFS od class (od / expver=80)", "od", "80"),
]


def main() -> int:
    try:
        from ecmwfapi import ECMWFService
    except ImportError:
        print("ERROR: ecmwf-api-client not installed. Run: pip install ecmwf-api-client")
        return 1

    mars = ECMWFService("mars", verbose=True)

    results: dict[str, bool] = {}
    for label, cls, expver in _TESTS:
        print(f"\n{'='*60}")
        print(f"Testing: {label}")
        print(f"{'='*60}")
        req = {**_BASE, "class": cls, "expver": expver}
        results[label] = _try_request(mars, req, label)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    all_ok = True
    for label, ok in results.items():
        status = "✓ OK" if ok else "✗ FAILED"
        print(f"  {status}  {label}")
        if not ok:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
