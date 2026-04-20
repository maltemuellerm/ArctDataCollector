#!/usr/bin/env python3
"""Compute AROME Arctic NWP verification statistics.

For each observation source (ships, SIMBA, thermistor, ArctSum, SvalMIZ, IABP)
this script:
  1. Loads observation CSVs from <obs-dir>/<source>/*.csv (last --days days).
  2. For each AROME Arctic 2.5 km 00Z/12Z run in that period:
       - Opens the file via THREDDS OPeNDAP.
       - Loads lat/lon grid once (reused for all files on the same grid).
       - For every observation whose verification time falls in [T0, T0+66 h],
         finds the nearest grid point and fetches the forecast value.
  3. Caches raw pairs per run → <out-dir>/runs/YYYYMMDD_HH.json
     (skip if already present; use --force to recompute).
  4. Aggregates all in-window pairs and writes <out-dir>/verification.json
     with RMSE, MAE, BIAS per (source, variable, lead-time bucket, grouping).

Usage
-----
  python3 compute_arome_verification.py [--days 30] [--obs-dir PATH]
                                         [--out-dir PATH] [--force]

Requirements: netCDF4, numpy (already in requirements.txt)
"""

import argparse
import csv
import json
import logging
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import netCDF4
import numpy as np

logger = logging.getLogger(__name__)

# ── AROME OPeNDAP URL template ─────────────────────────────────────────────────
_THREDDS_TMPL = (
    "https://thredds.met.no/thredds/dodsC/aromearcticarchive"
    "/{y}/{m:02d}/{d:02d}"
    "/arome_arctic_det_2_5km_{y}{m:02d}{d:02d}T{h:02d}Z.nc"
)
_RUN_HOURS   = (0, 12)   # 00Z and 12Z runs
_MAX_LEAD_H  = 66        # AROME Arctic forecast horizon
_MAX_DIST    = 0.5       # degrees – reject obs if nearest point is farther
_MAX_SCATTER = 600       # max scatter pairs stored per source+variable (combined)
_TIME_TOL_S  = 5400      # 90 min – max acceptable time mismatch to AROME step

# ── Lead-time grouping schemes ─────────────────────────────────────────────────
_GROUPINGS: dict[str, list[tuple[int, int, str]]] = {
    "6h": [(i, i + 6,  f"{i}\u2013{i+6}\u200ah")  for i in range(0, _MAX_LEAD_H, 6)],
    "12h": [(i, i + 12, f"{i}\u2013{i+12}\u200ah") for i in range(0, _MAX_LEAD_H, 12)],
    "24h": [
        (0,  24, "Day 1  (0\u201324\u200ah)"),
        (24, 48, "Day 2  (24\u201348\u200ah)"),
        (48, _MAX_LEAD_H, f"Day 3  (48\u2013{_MAX_LEAD_H}\u200ah)"),
    ],
}

# ── Variable mapping: obs_col → ([arome candidates], converter|"wind") ─────────
# converter(raw_arome_value) → obs-compatible value
_VAR_MAP: dict[str, tuple] = {
    "air_temp":        (["air_temperature_2m"],        lambda v: v - 273.15),
    "air_pressure":    (["air_pressure_at_sea_level"], lambda v: v * 0.01),
    "wind_speed":      ("wind",                        None),   # special
    "humidity":        (["relative_humidity_2m"],
                        lambda v: v * 100.0 if v <= 2.0 else v),
    "sea_surface_temp":(["sea_surface_temperature", "surface_sea_water_temperature"],
                        lambda v: v - 273.15),
}

# ── Observation source configuration ───────────────────────────────────────────
_SOURCES: dict[str, dict] = {
    "ships":     {"variables": ["air_temp", "wind_speed", "air_pressure", "humidity"],
                  "pattern": "*.csv"},
    "simba":     {"variables": ["air_temp", "air_pressure"],
                  "pattern": "*.csv"},
    "thermistor":{"variables": ["air_temp", "air_pressure"],
                  "pattern": "*_ts.csv"},
    "arctsum":   {"variables": ["air_temp"],
                  "pattern": "*_ts.csv"},
    "svalmiz":   {"variables": ["air_temp"],
                  "pattern": "*_ts.csv"},
    "iabp":      {"variables": ["air_temp", "air_pressure"],
                  "pattern": "*.csv"},
}

_VAR_META: dict[str, dict] = {
    "air_temp":        {"label": "Air temperature",  "units": "\u00b0C"},
    "air_pressure":    {"label": "Air pressure",     "units": "hPa"},
    "wind_speed":      {"label": "Wind speed",       "units": "m/s"},
    "humidity":        {"label": "Humidity",         "units": "%"},
    "sea_surface_temp":{"label": "Sea surface temp", "units": "\u00b0C"},
}


# ── Grid helpers ───────────────────────────────────────────────────────────────

def _load_grid(nc: netCDF4.Dataset) -> tuple[np.ndarray, np.ndarray]:
    """Return (lat2d, lon2d) from an AROME file. Tries common variable names."""
    lat2d = lon2d = None
    for name in ("latitude", "lat", "Latitude", "LAT"):
        if name in nc.variables:
            lat2d = np.asarray(nc.variables[name][:])
            break
    for name in ("longitude", "lon", "Longitude", "LON"):
        if name in nc.variables:
            lon2d = np.asarray(nc.variables[name][:])
            break
    if lat2d is None or lon2d is None:
        raise KeyError(f"No lat/lon variables in AROME file. Available: {list(nc.variables)}")
    if lat2d.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon2d, lat2d)
    return lat2d, lon2d


def _nearest_grid(lat2d: np.ndarray, lon2d: np.ndarray,
                  lat_o: float, lon_o: float) -> tuple[int, int, float]:
    """Return (j, i, approx_dist_deg) of nearest AROME grid point."""
    cos_lat = math.cos(math.radians(lat_o))
    dist2 = (lat2d - lat_o) ** 2 + ((lon2d - lon_o) * cos_lat) ** 2
    flat = int(np.argmin(dist2))
    j, i = divmod(flat, lat2d.shape[1])
    return j, i, math.sqrt(float(dist2.flat[flat]))


def _domain_boundary(lat2d: np.ndarray, lon2d: np.ndarray,
                     step: int = 15) -> list[list[float]]:
    """Sample edge pixels to get an approximate domain boundary polygon.

    Returns list of [lat, lon] pairs going clockwise around the grid edge.
    """
    rows, cols = lat2d.shape
    pts: list[list[float]] = []
    # bottom row, left → right
    for i in range(0, cols, step):
        pts.append([round(float(lat2d[-1, i]), 3), round(float(lon2d[-1, i]), 3)])
    # right column, bottom → top
    for j in range(rows - 1, -1, -step):
        pts.append([round(float(lat2d[j, -1]), 3), round(float(lon2d[j, -1]), 3)])
    # top row, right → left
    for i in range(cols - 1, -1, -step):
        pts.append([round(float(lat2d[0, i]), 3), round(float(lon2d[0, i]), 3)])
    # left column, top → bottom
    for j in range(0, rows, step):
        pts.append([round(float(lat2d[j, 0]), 3), round(float(lon2d[j, 0]), 3)])
    return pts


# ── Time helpers ───────────────────────────────────────────────────────────────

def _parse_iso(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00"):
        try:
            return datetime.strptime(s[:19], fmt[:19]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _arome_times(nc: netCDF4.Dataset) -> list[datetime]:
    tvar = nc.variables["time"]
    dates = netCDF4.num2date(tvar[:], units=tvar.units,
                             calendar=getattr(tvar, "calendar", "standard"))
    return [
        datetime(d.year, d.month, d.day, d.hour, d.minute, d.second,
                 tzinfo=timezone.utc)
        for d in dates
    ]


def _time_index(times: list[datetime], target: datetime) -> int | None:
    diffs = [abs((t - target).total_seconds()) for t in times]
    idx = int(np.argmin(diffs))
    return idx if diffs[idx] <= _TIME_TOL_S else None


# ── Observation loading ────────────────────────────────────────────────────────

def _load_all_obs(obs_root: Path,
                  start: datetime, end: datetime) -> dict[str, list[dict]]:
    """Load observations from all sources within [start, end]."""
    result: dict[str, list[dict]] = {}
    for source, cfg in _SOURCES.items():
        src_dir = obs_root / source
        if not src_dir.is_dir():
            logger.debug("Missing obs directory: %s", src_dir)
            continue
        records: list[dict] = []
        for fp in sorted(src_dir.glob(cfg["pattern"])):
            instrument = fp.stem.replace("_ts", "")
            try:
                with fp.open(newline="", encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        ts = row.get("time", "")
                        if not ts:
                            continue
                        dt = _parse_iso(ts)
                        if dt is None or not (start <= dt <= end):
                            continue
                        try:
                            lat = float(row["latitude"])
                            lon = float(row["longitude"])
                        except (KeyError, ValueError):
                            continue
                        if not (math.isfinite(lat) and math.isfinite(lon)):
                            continue
                        for var in cfg["variables"]:
                            raw = row.get(var, "")
                            if not raw:
                                continue
                            try:
                                val = float(raw)
                            except ValueError:
                                continue
                            if not math.isfinite(val):
                                continue
                            records.append({
                                "instrument": instrument,
                                "variable": var,
                                "time": dt,
                                "lat": lat,
                                "lon": lon,
                                "obs": val,
                            })
            except OSError as exc:
                logger.warning("Cannot read %s: %s", fp, exc)
        result[source] = records
        logger.info("Loaded %d obs for source '%s'", len(records), source)
    return result


# ── AROME run processing ───────────────────────────────────────────────────────

def _fetch_series(nc: netCDF4.Dataset,
                  var_names: list[str],
                  j: int, i: int) -> np.ndarray | None:
    """Fetch all-time time series at grid point (j, i) for first matching var."""
    for name in var_names:
        if name not in nc.variables:
            continue
        v = nc.variables[name]
        ndim = v.ndim
        try:
            if ndim == 3:
                arr = v[:, j, i]
            elif ndim == 4:
                arr = v[:, 0, j, i]   # e.g. (time, 1, y, x)
            else:
                continue
        except Exception:
            continue
        return np.ma.filled(np.asarray(arr, dtype=float), np.nan)
    return None


def _process_run(run_time: datetime,
                 all_obs: dict[str, list[dict]],
                 lat2d: np.ndarray,
                 lon2d: np.ndarray) -> list[dict]:
    """Open one AROME run, match observations and return paired list."""
    url = _THREDDS_TMPL.format(
        y=run_time.year, m=run_time.month, d=run_time.day, h=run_time.hour)
    pairs: list[dict] = []

    try:
        nc = netCDF4.Dataset(url)
    except OSError as exc:
        logger.warning("Cannot open AROME run %s – %s", run_time.strftime("%Y%m%dT%HZ"), exc)
        return pairs

    try:
        atimes = _arome_times(nc)
        run_end = run_time + timedelta(hours=_MAX_LEAD_H)

        # Cache: (arome_var_name, j, i) → time-series array  (avoids re-fetching)
        ts_cache: dict[tuple, np.ndarray | None] = {}

        for source, obs_list in all_obs.items():
            window = [o for o in obs_list if run_time <= o["time"] <= run_end]
            if not window:
                continue

            # Cache nearest grid point per rounded (lat, lon)
            grid_cache: dict[tuple, tuple[int, int, float]] = {}

            for obs in window:
                loc_key = (round(obs["lat"], 2), round(obs["lon"], 2))
                if loc_key not in grid_cache:
                    j, i, dist = _nearest_grid(lat2d, lon2d, obs["lat"], obs["lon"])
                    grid_cache[loc_key] = (j, i, dist)
                j, i, dist = grid_cache[loc_key]
                if dist > _MAX_DIST:
                    continue

                t_idx = _time_index(atimes, obs["time"])
                if t_idx is None:
                    continue

                lead_h = (obs["time"] - run_time).total_seconds() / 3600.0
                var = obs["variable"]
                var_spec, converter = _VAR_MAP[var]

                if var_spec == "wind":
                    # fetch x and y components
                    def _ts(name: str) -> np.ndarray | None:
                        k = (name, j, i)
                        if k not in ts_cache:
                            ts_cache[k] = _fetch_series(nc, [name], j, i)
                        return ts_cache[k]
                    u = _ts("x_wind_10m")
                    v_ = _ts("y_wind_10m")
                    if u is None or v_ is None:
                        continue
                    uu, vv = float(u[t_idx]), float(v_[t_idx])
                    if not (math.isfinite(uu) and math.isfinite(vv)):
                        continue
                    model_val = math.sqrt(uu * uu + vv * vv)
                else:
                    k = (var_spec[0], j, i)
                    if k not in ts_cache:
                        ts_cache[k] = _fetch_series(nc, var_spec, j, i)
                    series = ts_cache[k]
                    if series is None:
                        continue
                    raw = float(series[t_idx])
                    if not math.isfinite(raw):
                        continue
                    model_val = float(converter(raw))

                if not math.isfinite(model_val):
                    continue

                pairs.append({
                    "source":     source,
                    "instrument": obs["instrument"],
                    "variable":   var,
                    "obs":        obs["obs"],
                    "model":      model_val,
                    "lead_h":     round(lead_h, 2),
                    "lat":        round(obs["lat"], 3),
                    "lon":        round(obs["lon"], 3),
                })
    finally:
        nc.close()

    logger.info("Run %s: %d pairs", run_time.strftime("%Y%m%dT%HZ"), len(pairs))
    return pairs


# ── Statistics ─────────────────────────────────────────────────────────────────

def _stats(obs_arr: np.ndarray, model_arr: np.ndarray) -> dict:
    err = model_arr - obs_arr
    return {
        "n":    int(len(err)),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mae":  float(np.mean(np.abs(err))),
        "bias": float(np.mean(err)),
    }


def _compute_verification(all_pairs: list[dict]) -> dict:
    """Aggregate pairs into stats + scatter data per (source, variable)."""

    # Group pairs: pairs_by[source][variable] = list of (obs, model, lead_h, lat, lon)
    pairs_by: dict[str, dict[str, list[tuple]]] = defaultdict(lambda: defaultdict(list))
    for p in all_pairs:
        pairs_by[p["source"]][p["variable"]].append(
            (p["obs"], p["model"], p["lead_h"], p.get("lat"), p.get("lon")))

    stats_out: dict[str, dict] = {}
    scatter_out: dict[str, dict] = {}

    for source, var_dict in pairs_by.items():
        stats_out[source] = {}
        scatter_out[source] = {}
        for var, triplets in var_dict.items():
            obs_all   = np.array([t[0] for t in triplets])
            model_all = np.array([t[1] for t in triplets])
            leads_all = np.array([t[2] for t in triplets])
            # t[3]=lat, t[4]=lon (may be None for legacy cached pairs)

            # Per-grouping statistics
            grp_stats: dict[str, list[dict]] = {}
            for grp_key, buckets in _GROUPINGS.items():
                grp_stats[grp_key] = []
                for lo, hi, label in buckets:
                    mask = (leads_all >= lo) & (leads_all < hi)
                    n = int(mask.sum())
                    if n < 2:
                        grp_stats[grp_key].append(
                            {"label": label, "n": n,
                             "rmse": None, "mae": None, "bias": None})
                    else:
                        s = _stats(obs_all[mask], model_all[mask])
                        grp_stats[grp_key].append({"label": label, **s})

            stats_out[source][var] = grp_stats

            # Scatter data: cap at _MAX_SCATTER, preserve lead info
            n_total = len(triplets)
            if n_total > _MAX_SCATTER:
                idx = random.sample(range(n_total), _MAX_SCATTER)
                samp = [triplets[i] for i in sorted(idx)]
            else:
                samp = triplets
            scatter_out[source][var] = {
                "obs":   [round(t[0], 4) for t in samp],
                "model": [round(t[1], 4) for t in samp],
                "lead":  [round(t[2], 2) for t in samp],
                "lat":   [t[3] for t in samp],
                "lon":   [t[4] for t in samp],
            }

    return {"stats": stats_out, "scatter": scatter_out}


# ── Main ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    _SCRIPT_DIR = Path(__file__).resolve().parent
    _BASE_DIR   = _SCRIPT_DIR.parent

    parser = argparse.ArgumentParser(description="Compute AROME Arctic verification.")
    parser.add_argument("--days",    type=int, default=30,
                        help="Number of days to look back (default: 30)")
    parser.add_argument("--obs-dir", type=Path,
                        default=_BASE_DIR / "data" / "processed" / "csv",
                        help="Root directory for observation CSVs")
    parser.add_argument("--out-dir", type=Path,
                        default=_BASE_DIR / "data" / "processed" / "csv" / "arome",
                        help="Output directory for verification JSON")
    parser.add_argument("--force",  action="store_true",
                        help="Reprocess all AROME runs (ignore cache)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    out_dir  = args.out_dir
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    now   = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = (now - timedelta(days=args.days)).replace(hour=0, minute=0)
    end   = now

    logger.info("Period: %s → %s", start.date(), end.date())

    # ── Load observations ───────────────────────────────────────────────────────
    all_obs = _load_all_obs(args.obs_dir, start, end)
    total_obs = sum(len(v) for v in all_obs.values())
    logger.info("Total obs loaded: %d across %d sources", total_obs, len(all_obs))
    if not all_obs:
        logger.error("No observations found in %s", args.obs_dir)
        sys.exit(1)

    # ── Iterate AROME runs ──────────────────────────────────────────────────────
    lat2d = lon2d = None   # loaded once from the first successfully opened file
    all_pairs: list[dict] = []

    current = start.replace(hour=0)
    while current <= end:
        for hour in _RUN_HOURS:
            run_time = current.replace(hour=hour, minute=0, second=0, microsecond=0)
            if run_time > end:
                continue

            cache_file = runs_dir / f"{run_time.strftime('%Y%m%d_%H')}.json"
            if cache_file.exists() and not args.force:
                # Load cached pairs
                try:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    all_pairs.extend(data)
                    logger.debug("Loaded %d cached pairs from %s",
                                 len(data), cache_file.name)
                    continue
                except Exception as exc:
                    logger.warning("Bad cache file %s: %s – reprocessing", cache_file, exc)

            # Load AROME grid on first successful open
            if lat2d is None:
                url = _THREDDS_TMPL.format(
                    y=run_time.year, m=run_time.month,
                    d=run_time.day,  h=run_time.hour)
                try:
                    nc_probe = netCDF4.Dataset(url)
                    lat2d, lon2d = _load_grid(nc_probe)
                    nc_probe.close()
                    logger.info("AROME grid loaded: shape %s", lat2d.shape)
                except OSError:
                    pass  # will be caught again in _process_run

            if lat2d is None:
                # Still None – try next run
                logger.debug("Grid not yet loaded, will retry next run")
                pairs = []
            else:
                pairs = _process_run(run_time, all_obs, lat2d, lon2d)

            # Save cache file (even empty, to avoid retrying unavailable dates)
            try:
                cache_file.write_text(
                    json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
            except OSError as exc:
                logger.warning("Cannot write cache %s: %s", cache_file, exc)

            all_pairs.extend(pairs)
        current += timedelta(days=1)

    logger.info("Total pairs collected: %d", len(all_pairs))

    # ── Compute and write verification.json ────────────────────────────────────
    result = _compute_verification(all_pairs)

    output = {
        "generated":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period":     {"start": start.date().isoformat(),
                       "end":   end.date().isoformat()},
        "groupings":  {k: [{"lo": lo, "hi": hi, "label": lbl}
                            for lo, hi, lbl in buckets]
                       for k, buckets in _GROUPINGS.items()},
        "variables":  _VAR_META,
        "domain":     _domain_boundary(lat2d, lon2d) if lat2d is not None else [],
        "stats":      result["stats"],
        "scatter":    result["scatter"],
    }

    out_file = out_dir / "verification.json"
    out_file.write_text(json.dumps(output, ensure_ascii=False, indent=None),
                        encoding="utf-8")
    logger.info("Wrote %s (%.1f KB)", out_file, out_file.stat().st_size / 1024)


if __name__ == "__main__":
    main()
