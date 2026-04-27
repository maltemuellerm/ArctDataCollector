#!/usr/bin/env python3
"""Compute ECMWF IFS / AIFS NWP verification statistics against Arctic observations.

For each model (IFS HRES and AIFS) and each 00Z/12Z run in the last --days days:
  1. Downloads a NetCDF file from MARS (ECMWFService) for the Arctic domain.
  2. Matches observation CSVs (ships, SIMBA, thermistor, ArctSum, SvalMIZ, IABP)
     to the nearest grid point and time step.
  3. Caches raw pairs per run → <out-dir>/runs_{model}/YYYYMMDD_HH.json
     (uses obs-coverage-aware invalidation: same logic as compute_arome_verification.py)
  4. Aggregates pairs and writes <out-dir>/verification_{model}.json

The downloaded NetCDF file is deleted immediately after processing each run.

Usage
-----
  python3 compute_ecmwf_verification.py [--model ifs|aifs|both] [--days 30]
                                         [--obs-dir PATH] [--out-dir PATH]
                                         [--force] [--log-level INFO]

Requirements: ecmwf-api-client, netCDF4, numpy  (cfgrib not needed: format=netcdf)
ECMWF credentials: ~/.ecmwfapirc  (url, key, email)

NOTE on AIFS MARS keywords
--------------------------
The class/stream/expver for AIFS may change as ECMWF operationalises the model.
Verify current keywords at: https://apps.ecmwf.int/mars-catalogue/
Update _MODELS["aifs"] below if requests fail.
"""

import argparse
import csv
import json
import logging
import math
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import netCDF4
import numpy as np

logger = logging.getLogger(__name__)

# ── Model configurations ───────────────────────────────────────────────────────
_MODELS: dict[str, dict] = {
    "ifs": {
        "label":      "IFS HRES",
        "mars_class": "od",
        "stream":     "oper",
        "expver":     "1",
        "type":       "fc",
        # Hourly steps 0–72; produces ~25 MB NetCDF per run at 0.25° Arctic domain
        "steps":      "/".join(str(s) for s in range(0, 73)),
        "run_hours":  (0, 12),
        "max_lead_h": 72,
        "time_tol_s": 5400,    # ±90 min — same as AROME (hourly steps)
    },
    "aifs": {
        "label":      "AIFS",
        # NOTE: verify these MARS keywords for AIFS at https://apps.ecmwf.int/mars-catalogue/
        # They may require class="ml" or a specific expver once AIFS is fully operational.
        "mars_class": "od",
        "stream":     "oper",
        "expver":     "1",
        "type":       "fc",
        # AIFS produces 6-hourly steps
        "steps":      "0/6/12/18/24/30/36/42/48/54/60/66/72",
        "run_hours":  (0, 12),
        "max_lead_h": 72,
        "time_tol_s": 10800,   # ±3 h (wider tolerance for 6-hourly steps)
    },
}

# Pan-Arctic domain — N/W/S/E format for MARS "area" keyword.
# Full 360° longitude coverage north of 60°N so that all Arctic obs sources
# (including North America, Russia east, Bering Strait) are included.
_AREA   = "90/-180/60/180"
_GRID   = "0.25/0.25"
# GRIB parameter codes: 2m temp, skin temp, MSLP, 10m u-wind, 10m v-wind
_PARAMS = "167/235/151/165/166"

_MAX_DIST = 0.5   # degrees — reject obs if nearest grid point is farther away

# ── Variable mapping: obs_col → ([netcdf var names], converter | "wind") ──────
# MARS grib→netcdf conversion uses ECMWF short names (t2m, skt, msl, u10, v10)
_VAR_MAP: dict[str, tuple] = {
    "air_temp":         (["t2m"],  lambda v: v - 273.15),
    "air_pressure":     (["msl"],  lambda v: v * 0.01),
    "wind_speed":       ("wind",   None),    # special: sqrt(u10² + v10²)
    "sea_surface_temp": (["skt"],  lambda v: v - 273.15),
}

# ── Observation source configuration (identical to compute_arome_verification) ─
_SOURCES: dict[str, dict] = {
    "ships":      {"variables": ["air_temp", "wind_speed", "air_pressure"],
                   "pattern": "*.csv"},
    "simba":      {"variables": ["air_temp", "air_pressure"],
                   "pattern": "*.csv"},
    "thermistor": {"variables": ["air_temp", "air_pressure"],
                   "pattern": "*_ts.csv"},
    "arctsum":    {"variables": ["air_temp"],
                   "pattern": "*_ts.csv"},
    "svalmiz":    {"variables": ["air_temp"],
                   "pattern": "*_ts.csv"},
    "iabp":       {"variables": ["air_temp", "air_pressure"],
                   "pattern": "*.csv"},
}

_VAR_META: dict[str, dict] = {
    "air_temp":         {"label": "Air temperature",  "units": "\u00b0C"},
    "air_pressure":     {"label": "Air pressure",     "units": "hPa"},
    "wind_speed":       {"label": "Wind speed",       "units": "m/s"},
    "sea_surface_temp": {"label": "Sea surface temp", "units": "\u00b0C"},
}

_GROSS_ERROR_SIGMA = 3.0


# ── Grid helpers ───────────────────────────────────────────────────────────────

def _load_grid(nc: netCDF4.Dataset) -> tuple[np.ndarray, np.ndarray]:
    """Return (lat2d, lon2d) from an ECMWF NetCDF file."""
    lat_arr = lon_arr = None
    for name in ("latitude", "lat", "Latitude", "LAT"):
        if name in nc.variables:
            lat_arr = np.asarray(nc.variables[name][:])
            break
    for name in ("longitude", "lon", "Longitude", "LON"):
        if name in nc.variables:
            lon_arr = np.asarray(nc.variables[name][:])
            break
    if lat_arr is None or lon_arr is None:
        raise KeyError(
            f"No lat/lon variables in NetCDF. Available: {list(nc.variables)}"
        )
    if lat_arr.ndim == 1:
        lon_arr, lat_arr = np.meshgrid(lon_arr, lat_arr)
    return lat_arr, lon_arr


def _nearest_grid(lat2d: np.ndarray, lon2d: np.ndarray,
                  lat_o: float, lon_o: float) -> tuple[int, int, float]:
    """Return (j, i, approx_dist_deg) of the nearest grid point."""
    cos_lat = math.cos(math.radians(lat_o))
    dist2 = (lat2d - lat_o) ** 2 + ((lon2d - lon_o) * cos_lat) ** 2
    flat = int(np.argmin(dist2))
    j, i = divmod(flat, lat2d.shape[1])
    return j, i, math.sqrt(float(dist2.flat[flat]))


# ── Time helpers ───────────────────────────────────────────────────────────────

def _parse_iso(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00"):
        try:
            return datetime.strptime(s[:19], fmt[:19]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _nc_times(nc: netCDF4.Dataset) -> list[datetime]:
    """Decode forecast valid times from an ECMWF NetCDF file.

    MARS grib→netcdf places valid times in 'valid_time' or 'time'.
    Returns a list of UTC datetimes (one per forecast step).
    """
    for tname in ("valid_time", "time"):
        if tname not in nc.variables:
            continue
        tvar = nc.variables[tname]
        raw = tvar[:]
        dates = netCDF4.num2date(
            raw, units=tvar.units,
            calendar=getattr(tvar, "calendar", "standard"),
        )
        # num2date may return a scalar when there's only one time step
        if not hasattr(dates, "__iter__"):
            dates = [dates]
        return [
            datetime(d.year, d.month, d.day, d.hour, d.minute, d.second,
                     tzinfo=timezone.utc)
            for d in dates
        ]
    raise KeyError(
        f"No time/valid_time variable in NetCDF. Available: {list(nc.variables)}"
    )


def _time_index(times: list[datetime], target: datetime, tol_s: int) -> int | None:
    diffs = [abs((t - target).total_seconds()) for t in times]
    idx = int(np.argmin(diffs))
    return idx if diffs[idx] <= tol_s else None


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
                                "variable":   var,
                                "time":       dt,
                                "lat":        lat,
                                "lon":        lon,
                                "obs":        val,
                            })
            except OSError as exc:
                logger.warning("Cannot read %s: %s", fp, exc)
        result[source] = records
        logger.info("Loaded %d obs for source '%s'", len(records), source)
    return result


# ── MARS fetch ─────────────────────────────────────────────────────────────────

def _mars_fetch(run_time: datetime, model_cfg: dict, target_path: Path) -> bool:
    """Download one ECMWF model run via MARS to target_path.

    Returns True on success (file exists and non-empty), False otherwise.
    """
    try:
        from ecmwfapi import ECMWFService
    except ImportError:
        logger.error("ecmwf-api-client not installed. Run: pip install ecmwf-api-client")
        return False

    service = ECMWFService("mars")
    request = {
        "class":   model_cfg["mars_class"],
        "stream":  model_cfg["stream"],
        "expver":  model_cfg["expver"],
        "type":    model_cfg["type"],
        "date":    run_time.strftime("%Y-%m-%d"),
        "time":    f"{run_time.hour:02d}:00:00",
        "step":    model_cfg["steps"],
        "levtype": "sfc",
        "param":   _PARAMS,
        "area":    _AREA,
        "grid":    _GRID,
        "format":  "netcdf",
    }
    logger.info(
        "MARS request: %s %sZ (steps: %s…)",
        model_cfg["label"],
        run_time.strftime("%Y-%m-%d %H"),
        model_cfg["steps"][:12],
    )
    try:
        service.execute(request, str(target_path))
    except Exception as exc:
        logger.warning(
            "MARS fetch failed for %s %s: %s",
            model_cfg["label"], run_time.strftime("%Y%m%dT%HZ"), exc,
        )
        return False
    return target_path.exists() and target_path.stat().st_size > 0


# ── Run processing ─────────────────────────────────────────────────────────────

def _fetch_series(nc: netCDF4.Dataset,
                  var_names: list[str],
                  j: int, i: int) -> np.ndarray | None:
    """Return all-time forecast series at grid point (j, i) for the first
    matching variable name found in the file."""
    for name in var_names:
        if name not in nc.variables:
            continue
        v = nc.variables[name]
        try:
            if v.ndim == 3:       # (time, lat, lon)
                arr = v[:, j, i]
            elif v.ndim == 4:     # (time, level, lat, lon)
                arr = v[:, 0, j, i]
            else:
                continue
        except Exception:
            continue
        return np.ma.filled(np.asarray(arr, dtype=float), np.nan)
    return None


def _process_run_nc(nc_path: Path,
                    run_time: datetime,
                    all_obs: dict[str, list[dict]],
                    model_cfg: dict) -> list[dict]:
    """Open one ECMWF NetCDF file, match obs and return paired list."""
    pairs: list[dict] = []
    max_lead_h = model_cfg["max_lead_h"]
    time_tol_s = model_cfg["time_tol_s"]
    run_end    = run_time + timedelta(hours=max_lead_h)

    try:
        nc = netCDF4.Dataset(nc_path)
    except OSError as exc:
        logger.warning("Cannot open %s: %s", nc_path.name, exc)
        return pairs

    try:
        lat2d, lon2d = _load_grid(nc)
        try:
            nc_time_list = _nc_times(nc)
        except KeyError as exc:
            logger.warning("Cannot decode times from %s: %s", nc_path.name, exc)
            return pairs

        # Cache: (var_name, j, i) → time-series array  (avoids re-reading)
        ts_cache:   dict[tuple, np.ndarray | None] = {}
        # Cache: rounded (lat, lon) → (j, i, dist)
        grid_cache: dict[tuple, tuple[int, int, float]] = {}

        for source, obs_list in all_obs.items():
            window = [o for o in obs_list if run_time <= o["time"] <= run_end]
            if not window:
                continue

            for obs in window:
                loc_key = (round(obs["lat"], 2), round(obs["lon"], 2))
                if loc_key not in grid_cache:
                    j, i, dist = _nearest_grid(lat2d, lon2d, obs["lat"], obs["lon"])
                    grid_cache[loc_key] = (j, i, dist)
                j, i, dist = grid_cache[loc_key]
                if dist > _MAX_DIST:
                    continue

                t_idx = _time_index(nc_time_list, obs["time"], time_tol_s)
                if t_idx is None:
                    continue

                lead_h = (obs["time"] - run_time).total_seconds() / 3600.0
                var = obs["variable"]
                if var not in _VAR_MAP:
                    continue
                var_spec, converter = _VAR_MAP[var]

                if var_spec == "wind":
                    def _ts(name: str) -> np.ndarray | None:
                        k = (name, j, i)
                        if k not in ts_cache:
                            ts_cache[k] = _fetch_series(nc, [name], j, i)
                        return ts_cache[k]

                    u_ser = _ts("u10")
                    v_ser = _ts("v10")
                    if u_ser is None or v_ser is None:
                        continue
                    uu, vv = float(u_ser[t_idx]), float(v_ser[t_idx])
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

    logger.info(
        "[%s] Run %s: %d pairs",
        model_cfg["label"], run_time.strftime("%Y%m%dT%HZ"), len(pairs),
    )
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


def _gross_error_filter(triplets: list[tuple]) -> tuple[list[tuple], int]:
    """Remove pairs where |error − mean| > _GROSS_ERROR_SIGMA * std(errors)."""
    if len(triplets) < 10:
        return triplets, 0
    errors = np.array([t[1] - t[0] for t in triplets])
    mu  = float(np.mean(errors))
    sig = float(np.std(errors))
    if sig == 0:
        return triplets, 0
    keep     = np.abs(errors - mu) <= _GROSS_ERROR_SIGMA * sig
    filtered = [t for t, k in zip(triplets, keep) if k]
    return filtered, len(triplets) - len(filtered)


def _compute_verification(all_pairs: list[dict], max_lead_h: int) -> dict:
    """Aggregate pairs into stats + scatter data per (source, variable)."""
    groupings: dict[str, list[tuple[int, int, str]]] = {
        "6h":  [(i, i + 6,  f"{i}\u2013{i+6}\u200ah")  for i in range(0, max_lead_h, 6)],
        "12h": [(i, i + 12, f"{i}\u2013{i+12}\u200ah") for i in range(0, max_lead_h, 12)],
        "24h": [
            (0,  24, "Day 1  (0\u201324\u200ah)"),
            (24, 48, "Day 2  (24\u201348\u200ah)"),
            (48, max_lead_h, f"Day 3  (48\u2013{max_lead_h}\u200ah)"),
        ],
    }

    pairs_by: dict[str, dict[str, list[tuple]]] = defaultdict(lambda: defaultdict(list))
    for p in all_pairs:
        pairs_by[p["source"]][p["variable"]].append(
            (p["obs"], p["model"], p["lead_h"], p.get("lat"), p.get("lon"))
        )

    stats_out:   dict[str, dict] = {}
    scatter_out: dict[str, dict] = {}

    for source, var_dict in pairs_by.items():
        stats_out[source]   = {}
        scatter_out[source] = {}
        for var, triplets in var_dict.items():
            triplets, n_rej = _gross_error_filter(triplets)
            if n_rej:
                logger.info(
                    "Gross error filter: %s/%s removed %d pairs (%.1f%%)",
                    source, var, n_rej,
                    100.0 * n_rej / (len(triplets) + n_rej),
                )
            obs_all   = np.array([t[0] for t in triplets])
            model_all = np.array([t[1] for t in triplets])
            leads_all = np.array([t[2] for t in triplets])

            grp_stats: dict[str, list[dict]] = {}
            for grp_key, buckets in groupings.items():
                grp_stats[grp_key] = []
                for lo, hi, label in buckets:
                    mask = (leads_all >= lo) & (leads_all < hi)
                    n = int(mask.sum())
                    if n < 2:
                        grp_stats[grp_key].append(
                            {"label": label, "n": n,
                             "rmse": None, "mae": None, "bias": None}
                        )
                    else:
                        s = _stats(obs_all[mask], model_all[mask])
                        grp_stats[grp_key].append({"label": label, **s})

            stats_out[source][var] = grp_stats
            scatter_out[source][var] = {
                "obs":   [round(t[0], 4) for t in triplets],
                "model": [round(t[1], 4) for t in triplets],
                "lead":  [round(t[2], 2) for t in triplets],
                "lat":   [t[3] for t in triplets],
                "lon":   [t[4] for t in triplets],
            }

    return {
        "stats":   stats_out,
        "scatter": scatter_out,
        "groupings": {
            k: [{"lo": lo, "hi": hi, "label": lbl} for lo, hi, lbl in v]
            for k, v in groupings.items()
        },
    }


# ── Model run loop ─────────────────────────────────────────────────────────────

def _run_model(
    model_name: str,
    model_cfg:  dict,
    all_obs:    dict[str, list[dict]],
    obs_max_time: datetime,
    start:      datetime,
    end:        datetime,
    out_dir:    Path,
    now:        datetime,
    force:      bool,
) -> None:
    """Process all runs for one model and write verification_{model_name}.json."""
    runs_dir   = out_dir / f"runs_{model_name}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    max_lead_h = model_cfg["max_lead_h"]
    all_pairs: list[dict] = []

    current = start.replace(hour=0)
    while current <= end:
        for hour in model_cfg["run_hours"]:
            run_time = current.replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            if run_time > end:
                continue

            cache_file = runs_dir / f"{run_time.strftime('%Y%m%d_%H')}.json"
            run_end_dt = run_time + timedelta(hours=max_lead_h)
            obs_covers_run = obs_max_time >= run_end_dt - timedelta(hours=12)

            if cache_file.exists() and not force:
                try:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    cache_max_lead = max((p["lead_h"] for p in data), default=0)
                    if cache_max_lead >= max_lead_h - 12 or not obs_covers_run:
                        all_pairs.extend(data)
                        logger.debug(
                            "Loaded %d cached pairs from %s",
                            len(data), cache_file.name,
                        )
                        continue
                    logger.info(
                        "Stale cache %s (max_lead=%dh, obs now to %s) – reprocessing",
                        cache_file.name, int(cache_max_lead),
                        obs_max_time.strftime("%Y-%m-%d %H:%M"),
                    )
                except Exception as exc:
                    logger.warning(
                        "Bad cache %s: %s – reprocessing", cache_file, exc
                    )

            # Download from MARS into a temp file, process, then delete
            with tempfile.NamedTemporaryFile(
                suffix=".nc",
                prefix=f"ecmwf_{model_name}_",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)

            try:
                ok = _mars_fetch(run_time, model_cfg, tmp_path)
                if not ok:
                    logger.warning(
                        "Skipping run %s – MARS fetch failed",
                        run_time.strftime("%Y%m%dT%HZ"),
                    )
                    continue

                pairs = _process_run_nc(tmp_path, run_time, all_obs, model_cfg)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
                    logger.debug("Deleted temp file %s", tmp_path.name)

            # Only cache when obs fully cover this run's forecast window
            if obs_covers_run or not pairs:
                try:
                    cache_file.write_text(
                        json.dumps(pairs, ensure_ascii=False), encoding="utf-8"
                    )
                except OSError as exc:
                    logger.warning("Cannot write cache %s: %s", cache_file, exc)
            else:
                logger.debug(
                    "Not caching %s: obs only to %s, run_end %s",
                    cache_file.name,
                    obs_max_time.strftime("%Y-%m-%d %H:%M"),
                    run_end_dt.strftime("%Y-%m-%d %H:%M"),
                )

            all_pairs.extend(pairs)
        current += timedelta(days=1)

    logger.info("[%s] Total pairs collected: %d", model_cfg["label"], len(all_pairs))

    if not all_pairs:
        logger.warning(
            "[%s] No pairs – verification JSON not written", model_cfg["label"]
        )
        return

    result = _compute_verification(all_pairs, max_lead_h)

    output = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model":     model_cfg["label"],
        "period":    {
            "start": start.date().isoformat(),
            "end":   end.date().isoformat(),
        },
        "groupings": result["groupings"],
        "variables": _VAR_META,
        # Regular lat/lon box — four corners of the MARS domain
        "domain": [
            [90.0, -180.0], [90.0, 180.0],
            [60.0,  180.0], [60.0, -180.0],
        ],
        "stats":   result["stats"],
        "scatter": result["scatter"],
    }

    out_file = out_dir / f"verification_{model_name}.json"
    out_file.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "Wrote %s (%.1f KB)", out_file, out_file.stat().st_size / 1024
    )


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    _SCRIPT_DIR = Path(__file__).resolve().parent
    _BASE_DIR   = _SCRIPT_DIR.parent

    p = argparse.ArgumentParser(
        description="Compute ECMWF IFS / AIFS Arctic verification statistics."
    )
    p.add_argument(
        "--model", default="both", choices=["ifs", "aifs", "both"],
        help="Which model(s) to process (default: both)",
    )
    p.add_argument(
        "--days", type=int, default=30,
        help="Number of days to look back (default: 30)",
    )
    p.add_argument(
        "--obs-dir", type=Path,
        default=_BASE_DIR / "data" / "processed" / "csv",
        help="Root directory for observation CSVs",
    )
    p.add_argument(
        "--out-dir", type=Path,
        default=_BASE_DIR / "data" / "processed" / "csv" / "ecmwf",
        help="Output directory for verification JSON files",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Reprocess all runs (ignore run cache)",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)

    now   = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    # Leave 6 h before now so the most recent run has time to arrive in MARS
    end   = now - timedelta(hours=6)
    start = (now - timedelta(days=args.days)).replace(hour=0, minute=0)

    logger.info("Period: %s → %s", start.date(), end.date())

    all_obs = _load_all_obs(args.obs_dir, start, end)
    total_obs = sum(len(v) for v in all_obs.values())
    logger.info("Total obs loaded: %d across %d sources", total_obs, len(all_obs))
    if not all_obs:
        logger.error("No observations found in %s", args.obs_dir)
        sys.exit(1)

    obs_max_time: datetime = max(
        (row["time"] for obs_list in all_obs.values() for row in obs_list),
        default=start,
    )
    logger.info("Obs max time: %s", obs_max_time)

    models_to_run = list(_MODELS.keys()) if args.model == "both" else [args.model]
    for model_name in models_to_run:
        logger.info("=== Processing model: %s ===", _MODELS[model_name]["label"])
        _run_model(
            model_name       = model_name,
            model_cfg        = _MODELS[model_name],
            all_obs          = all_obs,
            obs_max_time     = obs_max_time,
            start            = start,
            end              = end,
            out_dir          = args.out_dir,
            now              = now,
            force            = args.force,
        )


if __name__ == "__main__":
    main()
