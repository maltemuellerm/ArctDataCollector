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
_MAX_SCATTER = None     # no cap – store all pairs for unbiased lead-time coverage
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
    "ships":        {"variables": ["air_temp", "wind_speed", "air_pressure", "humidity"],
                     "pattern": "*.csv"},
    "simba":        {"variables": ["air_temp", "air_pressure"],
                     "pattern": "*.csv"},
    "thermistor":   {"variables": ["air_temp", "air_pressure"],
                     "pattern": "*_ts.csv"},
    "arctsum":      {"variables": ["air_temp"],
                     "pattern": "*_ts.csv"},
    "svalmiz":      {"variables": ["air_temp"],
                     "pattern": "*_ts.csv"},
    "iabp":         {"variables": ["air_temp", "air_pressure"],
                     "pattern": "*.csv"},
    "svalbard":     {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "north_norway": {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "offshore":     {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "greenland":    {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "canada":       {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "alaska":       {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "russia":       {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "iceland":      {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "finland":      {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "sweden":       {"variables": ["air_temp", "wind_speed", "air_pressure"],
                     "pattern": "*.csv"},
    "norway_buoys": {"variables": ["air_temp", "wind_speed", "air_pressure"],
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
                    "time":       obs["time"].strftime("%Y-%m-%dT%H:%M"),
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


_GROSS_ERROR_SIGMA = 3.0   # reject pairs with |error| > N * std(errors)

def _gross_error_filter(triplets: list[tuple]) -> tuple[list[tuple], int]:
    """Remove pairs where |error| > _GROSS_ERROR_SIGMA * std(errors).
    Uses a single pass (not iterative) for speed; robust against outlier pull
    because std is dominated by the bulk distribution when n is large.
    Returns (filtered_triplets, n_rejected).
    """
    if len(triplets) < 10:
        return triplets, 0
    errors = np.array([t[1] - t[0] for t in triplets])
    mu  = float(np.mean(errors))
    sig = float(np.std(errors))
    if sig == 0:
        return triplets, 0
    keep = np.abs(errors - mu) <= _GROSS_ERROR_SIGMA * sig
    filtered = [t for t, k in zip(triplets, keep) if k]
    return filtered, len(triplets) - len(filtered)


def _build_timeseries(all_pairs: list[dict]) -> dict:
    """Build per-instrument 0–24 h stitched forecast timeseries, averaged across runs."""
    ts_raw: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for p in all_pairs:
        if p.get("lead_h", 999) > 24:
            continue
        t = p.get("time")
        if not t:
            continue
        ts_raw[p["source"]][p["variable"]][p.get("instrument", "")].append((t, p["model"]))
    ts_out: dict = {}
    for src, var_dict in ts_raw.items():
        ts_out[src] = {}
        for var, inst_dict in var_dict.items():
            ts_out[src][var] = {}
            for inst, pts in inst_dict.items():
                if not inst:
                    continue
                by_time: dict = defaultdict(list)
                for t, m in pts:
                    by_time[t].append(m)
                times = sorted(by_time)
                ts_out[src][var][inst] = {
                    "t": times,
                    "m": [round(sum(by_time[t]) / len(by_time[t]), 4) for t in times],
                }
    return ts_out


def _compute_variogram(all_pairs: list[dict]) -> dict:
    """Pre-compute spatial semivariogram per source/variable/lead-window.

    Pairs observations only within the *same valid-time snapshot* (same hour)
    to avoid temporal variability contaminating the spatial signal.
    Returns {source: {var: {window_key: {"obs": [...], "model": [...]}}}}
    where each list element is {"d": dist_km, "g": semivariance, "n": n_pairs}.
    """
    _VARIO_BINS_PY   = [0, 50, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000]
    _VARIO_WINDOWS_PY = [("0-12h", 0, 12), ("48-60h", 48, 60)]
    n_bins  = len(_VARIO_BINS_PY) - 1
    max_d   = _VARIO_BINS_PY[-1]

    def _hav_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(dlon / 2) ** 2)
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # grouped[source][var][window_key][valid_time_hour] = [(lat,lon,obs,model)]
    grouped: dict = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))

    for p in all_pairs:
        t   = p.get("time")
        lat = p.get("lat")
        lon = p.get("lon")
        if not t or lat is None or lon is None:
            continue
        t_hour = t[:13]  # YYYY-MM-DDTHH
        for wkey, wlo, whi in _VARIO_WINDOWS_PY:
            if wlo <= p["lead_h"] < whi:
                grouped[p["source"]][p["variable"]][wkey][t_hour].append(
                    (lat, lon, p["obs"], p["model"]))

    out: dict = {}
    for src, vd in grouped.items():
        out[src] = {}
        for var, wd in vd.items():
            out[src][var] = {}
            for wkey, snaps in wd.items():
                sums_o = [0.0] * n_bins
                sums_m = [0.0] * n_bins
                cnts   = [0]   * n_bins
                for pts in snaps.values():
                    step = max(1, len(pts) // 80)
                    sp   = pts[::step]
                    n    = len(sp)
                    for i in range(n - 1):
                        for j in range(i + 1, n):
                            d = _hav_km(sp[i][0], sp[i][1], sp[j][0], sp[j][1])
                            if d >= max_d:
                                continue
                            for b in range(n_bins):
                                if _VARIO_BINS_PY[b] <= d < _VARIO_BINS_PY[b + 1]:
                                    sums_o[b] += 0.5 * (sp[i][2] - sp[j][2]) ** 2
                                    sums_m[b] += 0.5 * (sp[i][3] - sp[j][3]) ** 2
                                    cnts[b]   += 1
                                    break
                dc = [(_VARIO_BINS_PY[b] + _VARIO_BINS_PY[b + 1]) / 2
                      for b in range(n_bins)]
                obs_pts   = [{"d": dc[b], "g": round(sums_o[b] / cnts[b], 4), "n": cnts[b]}
                             for b in range(n_bins) if cnts[b] >= 5]
                model_pts = [{"d": dc[b], "g": round(sums_m[b] / cnts[b], 4), "n": cnts[b]}
                             for b in range(n_bins) if cnts[b] >= 5]
                out[src][var][wkey] = {"obs": obs_pts, "model": model_pts}
    return out


def _compute_verification(all_pairs: list[dict]) -> dict:
    """Aggregate pairs into stats + scatter data per (source, variable)."""

    # Group pairs: pairs_by[source][variable] = list of (obs, model, lead_h, lat, lon)
    pairs_by: dict[str, dict[str, list[tuple]]] = defaultdict(lambda: defaultdict(list))
    for p in all_pairs:
        pairs_by[p["source"]][p["variable"]].append(
            (p["obs"], p["model"], p["lead_h"], p.get("lat"), p.get("lon"), p.get("time", "")))

    stats_out: dict[str, dict] = {}
    scatter_out: dict[str, dict] = {}

    for source, var_dict in pairs_by.items():
        stats_out[source] = {}
        scatter_out[source] = {}
        for var, triplets in var_dict.items():
            # Gross error filter before any stats or scatter sampling
            triplets, n_rej = _gross_error_filter(triplets)
            if n_rej:
                logger.info("Gross error filter: %s/%s removed %d pairs (%.1f%%)",
                            source, var, n_rej,
                            100.0 * n_rej / (len(triplets) + n_rej))

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

            # Scatter data: store all pairs (no sampling)
            scatter_out[source][var] = {
                "obs":   [round(t[0], 4) for t in triplets],
                "model": [round(t[1], 4) for t in triplets],
                "lead":  [round(t[2], 2) for t in triplets],
                "lat":   [t[3] for t in triplets],
                "lon":   [t[4] for t in triplets],
                "time":  [t[5] for t in triplets],
            }

    return {"stats": stats_out, "scatter": scatter_out,
            "timeseries": _build_timeseries(all_pairs),
            "variogram":  _compute_variogram(all_pairs)}


# ── Main ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    _SCRIPT_DIR = Path(__file__).resolve().parent
    _BASE_DIR   = _SCRIPT_DIR.parent

    parser = argparse.ArgumentParser(description="Compute AROME Arctic verification.")
    parser.add_argument("--days",    type=int, default=30,
                        help="Number of days to look back (default: 30)")
    parser.add_argument("--suffix",  type=str, default="",
                        help="Suffix appended to output filename before .json "
                             "(e.g. '_7d' → verification_7d.json). Default: empty = verification.json")
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
    parser.add_argument(
        "--cache-only", action="store_true", dest="cache_only",
        help="Skip THREDDS downloads; slice the main verification.json for the suffix period."
    )
    return parser.parse_args()


def _slice_arome_main_json(
    out_dir: Path,
    now:     datetime,
    suffix:  str,
    days:    int,
) -> bool:
    """Slice the main verification.json to produce a period-specific file."""
    main_file = out_dir / "verification.json"
    if not main_file.exists():
        logger.warning("Main file %s not found – cannot slice for %s", main_file, suffix)
        return False
    try:
        main_data = json.loads(main_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read %s: %s", main_file, exc)
        return False

    scatter = main_data.get("scatter", {})
    all_times: list[datetime] = []
    for src_dict in scatter.values():
        for var_dict in src_dict.values():
            for t_str in var_dict.get("time", []):
                try:
                    all_times.append(datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc))
                except Exception:
                    pass

    if not all_times:
        logger.warning("No time data in main AROME file for slicing")
        return False

    max_time    = max(all_times)
    slice_start = max_time - timedelta(days=days)
    logger.info("AROME slice: data up to %s, keeping last %d days (from %s)",
                max_time.date(), days, slice_start.date())

    all_pairs: list[dict] = []
    for source, src_dict in scatter.items():
        for variable, var_data in src_dict.items():
            obs_vals   = var_data.get("obs", [])
            model_vals = var_data.get("model", [])
            lead_vals  = var_data.get("lead", [])
            lat_vals   = var_data.get("lat", [])
            lon_vals   = var_data.get("lon", [])
            time_vals  = var_data.get("time", [])
            n = min(len(obs_vals), len(model_vals), len(lead_vals), len(time_vals))
            for i in range(n):
                try:
                    t = datetime.fromisoformat(time_vals[i]).replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if t < slice_start:
                    continue
                all_pairs.append({
                    "obs":      obs_vals[i],
                    "model":    model_vals[i],
                    "lead_h":   lead_vals[i],
                    "source":   source,
                    "variable": variable,
                    "time":     time_vals[i],
                    "lat":      lat_vals[i] if i < len(lat_vals) else None,
                    "lon":      lon_vals[i] if i < len(lon_vals) else None,
                })

    logger.info("AROME sliced %d pairs for last %d days", len(all_pairs), days)
    if not all_pairs:
        logger.warning("No pairs after slicing – skipping %s", suffix)
        return False

    result   = _compute_verification(all_pairs)
    output   = {
        "generated":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period":     {"start": slice_start.date().isoformat(), "end": max_time.date().isoformat()},
        "groupings":  {k: [{"lo": lo, "hi": hi, "label": lbl} for lo, hi, lbl in buckets]
                       for k, buckets in _GROUPINGS.items()},
        "variables":  _VAR_META,
        "domain":     main_data.get("domain", []),
        "stats":      result["stats"],
        "scatter":    result["scatter"],
        "timeseries": result.get("timeseries", {}),
        "variogram":  result.get("variogram", {}),
    }
    out_file = out_dir / f"verification{suffix}.json"
    out_file.write_text(json.dumps(output, ensure_ascii=False, indent=None), encoding="utf-8")
    logger.info("Wrote %s (%.1f KB)", out_file, out_file.stat().st_size / 1024)
    return True


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    out_dir  = args.out_dir
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Fast-path: slice existing main JSON for period-specific output
    if args.cache_only and args.suffix:
        now = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
        _slice_arome_main_json(out_dir, now, args.suffix, args.days)
        return

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

    # Latest observation timestamp across all sources (used for cache validity).
    obs_max_time: datetime = max(
        (row["time"] for obs_list in all_obs.values() for row in obs_list),
        default=start,
    )
    logger.info("Obs time range: %s → %s", start, obs_max_time)

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
            run_end_dt = run_time + timedelta(hours=_MAX_LEAD_H)
            # Obs fully cover this run's window if obs extend to within 12 h of run_end.
            obs_covers_run = obs_max_time >= run_end_dt - timedelta(hours=12)
            if cache_file.exists() and not args.force:
                # Load cached pairs
                try:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    cache_max_lead = (
                        max(p["lead_h"] for p in data) if data else 0
                    )
                    # Invalidate if coverage is poor AND obs can now do better
                    if cache_max_lead >= _MAX_LEAD_H - 12 or not obs_covers_run:
                        # Reconstruct "time" from filename + lead_h for legacy cached pairs
                        _rdt = datetime.strptime(cache_file.stem, "%Y%m%d_%H").replace(tzinfo=timezone.utc)
                        for _p in data:
                            if "time" not in _p:
                                _p["time"] = (_rdt + timedelta(hours=_p["lead_h"])).strftime("%Y-%m-%dT%H:%M")
                        all_pairs.extend(data)
                        logger.debug("Loaded %d cached pairs from %s",
                                     len(data), cache_file.name)
                        continue
                    logger.info(
                        "Stale cache %s (max_lead=%dh, obs now to %s) – reprocessing",
                        cache_file.name, int(cache_max_lead), obs_max_time.strftime("%Y-%m-%d %H:%M"),
                    )
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

            # Only write cache when obs fully cover this run's window.
            # If they don't, leave uncached so the next cron pass can fill in more obs.
            if obs_covers_run or not pairs:
                try:
                    cache_file.write_text(
                        json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
                except OSError as exc:
                    logger.warning("Cannot write cache %s: %s", cache_file, exc)
            else:
                logger.debug("Not caching %s: obs only to %s, run_end %s",
                             cache_file.name,
                             obs_max_time.strftime("%Y-%m-%d %H:%M"),
                             run_end_dt.strftime("%Y-%m-%d %H:%M"))

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
        "timeseries": result.get("timeseries", {}),
        "variogram":  result.get("variogram", {}),
    }

    out_file = out_dir / f"verification{args.suffix}.json"
    out_file.write_text(json.dumps(output, ensure_ascii=False, indent=None),
                        encoding="utf-8")
    logger.info("Wrote %s (%.1f KB)", out_file, out_file.stat().st_size / 1024)

    # Write a lightweight timeseries-only file for the map explorer overlay.
    # Only written for the main (no-suffix) run to avoid duplicating large files.
    if not args.suffix:
        ts_file = out_dir / "timeseries.json"
        ts_output = {
            "generated":  output["generated"],
            "model":      "AROME Arctic",
            "timeseries": result.get("timeseries", {}),
        }
        ts_file.write_text(json.dumps(ts_output, ensure_ascii=False, indent=None),
                           encoding="utf-8")
        logger.info("Wrote %s (%.1f KB)", ts_file, ts_file.stat().st_size / 1024)


if __name__ == "__main__":
    main()
