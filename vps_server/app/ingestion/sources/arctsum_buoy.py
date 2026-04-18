"""ArctSum 2025 thermistor string buoy source.

Downloads the combined NetCDF from the MET Norway Thredds server,
extracts per-trajectory (buoy) data, and returns TS + TEMP records.

TS rows  (GPS cadence, ~hourly):
  time, latitude, longitude, air_temp_C, skin_temp_C, wave_height_m, wave_period_t02_s

TEMP rows  (thermistor cadence, ~hourly, resampled onto GPS time axis):
  time, D{depth}  ... one column per sensor, depth in metres relative to
  the first-in-ice sensor (negative = snow/air side, positive = below ice)
"""

import csv
import io
import logging
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timezone

import netCDF4 as nc
import numpy as np

logger = logging.getLogger(__name__)


def fetch_arctsum(nc_url: str, deployment_info: dict) -> dict[str, tuple[list[dict], list[dict]]]:
    """Download NetCDF and return per-buoy (ts_rows, temp_rows) dicts.

    Parameters
    ----------
    nc_url : str
        Full URL to the Thredds NetCDF file.
    deployment_info : dict
        Mapping buoy_id → sensor_ice2 (1-indexed int, first sensor in ice).

    Returns
    -------
    dict  buoy_id → (ts_rows, temp_rows)
    """
    logger.info("Downloading ArctSum NetCDF from %s", nc_url)
    try:
        with urllib.request.urlopen(nc_url, timeout=120) as resp:
            raw = resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download {nc_url}: {exc}") from exc

    logger.info("Downloaded %.1f MB", len(raw) / 1e6)

    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    results = {}
    ds = nc.Dataset(tmp_path)
    try:
        trajectories = list(ds.variables["trajectory"][:])
        string_positions = ds.variables["string_position"][:]  # 26 depths + 'air'
        air_idx = int(np.where(string_positions == "air")[0][0])
        depth_labels = string_positions[:air_idx]  # 26 numeric strings, e.g. '0.00' … '3.00'

        time_units_gps  = ds.variables["time"].units
        time_units_temp = ds.variables["time_temp"].units
        time_units_wave = ds.variables["time_waves_imu"].units

        for tr_idx, buoy_id in enumerate(trajectories):
            sensor_ice2 = deployment_info.get(buoy_id, 1)  # 1-indexed
            try:
                ts_rows, temp_rows = _extract_buoy(
                    ds, tr_idx, buoy_id, sensor_ice2,
                    air_idx, depth_labels,
                    time_units_gps, time_units_temp, time_units_wave,
                )
                results[buoy_id] = (ts_rows, temp_rows)
                logger.info("Buoy %s: %d TS rows, %d TEMP rows", buoy_id, len(ts_rows), len(temp_rows))
            except Exception as exc:
                logger.error("Failed to extract buoy %s: %s", buoy_id, exc)
    finally:
        ds.close()
        import os; os.unlink(tmp_path)

    return results


def _extract_buoy(ds, tr_idx, buoy_id, sensor_ice2,
                  air_idx, depth_labels,
                  time_units_gps, time_units_temp, time_units_wave):
    """Extract TS and TEMP rows for one trajectory."""

    # ── GPS / position time axis ──────────────────────────────────────────────
    t_gps_raw = ds.variables["time"][tr_idx, :]
    gps_mask  = _mask_of(t_gps_raw)
    t_gps_s   = np.asarray(t_gps_raw[~gps_mask], dtype=np.float64)  # seconds
    t_gps_iso = _to_iso(t_gps_s, time_units_gps)
    lat = np.asarray(ds.variables["lat"][tr_idx, :][~gps_mask], dtype=np.float64)
    lon = np.asarray(ds.variables["lon"][tr_idx, :][~gps_mask], dtype=np.float64)

    # ── Temperature time axis ─────────────────────────────────────────────────
    t_temp_raw = ds.variables["time_temp"][tr_idx, :]
    temp_mask  = _mask_of(t_temp_raw)
    t_temp_s   = np.asarray(t_temp_raw[~temp_mask], dtype=np.float64)
    t_temp_ns  = (t_temp_s * 1e9).astype(np.int64)
    t_gps_ns   = (t_gps_s  * 1e9).astype(np.int64)

    # ── String temperatures (26 sensors) ─────────────────────────────────────
    T_all = np.asarray(
        ds.variables["temperature_calibrated_at_positions"][tr_idx, :, :air_idx],
        dtype=np.float64,
    )
    T_valid = T_all[~temp_mask, :]  # (n_temp, 26)

    # Re-centre depth axis: sensor_ice2 is 1-indexed, its depth becomes 0.
    y0 = np.array([float(d) for d in depth_labels])  # e.g. [0.00, 0.12, … 3.00]
    y  = y0 - y0[sensor_ice2 - 1]                    # relative to ice surface

    # Column names: D-0.48, D0.00, D0.12 …
    depth_cols = [f"D{v:.2f}" for v in y]

    # Air temperature (last string position = 'air')
    Tair_all   = np.asarray(
        ds.variables["temperature_calibrated_at_positions"][tr_idx, :, air_idx],
        dtype=np.float64,
    )
    Tair_valid = Tair_all[~temp_mask]

    # Skin temperature (IR)
    Tskin_all   = np.asarray(ds.variables["temp_mlx_ir"][tr_idx, :], dtype=np.float64)
    Tskin_valid = Tskin_all[~temp_mask]

    # ── Wave time axis ────────────────────────────────────────────────────────
    t_wave_raw  = ds.variables["time_waves_imu"][tr_idx, :]
    wave_mask   = _mask_of(t_wave_raw)
    t_wave_s    = np.asarray(t_wave_raw[~wave_mask], dtype=np.float64)
    t_wave_ns   = (t_wave_s * 1e9).astype(np.int64)

    Hs0_all  = np.asarray(ds.variables["pHs0"][tr_idx, :],  dtype=np.float64)
    T02_all  = np.asarray(ds.variables["pT02"][tr_idx, :],  dtype=np.float64)
    Hs0_v    = Hs0_all[~wave_mask]
    T02_v    = T02_all[~wave_mask]

    # ── Resample all vars onto GPS time axis ──────────────────────────────────
    Tair_on_gps  = _nearest_1d(t_temp_ns, Tair_valid,  t_gps_ns, max_gap_s=3600)
    Tskin_on_gps = _nearest_1d(t_temp_ns, Tskin_valid, t_gps_ns, max_gap_s=3600)
    Hs0_on_gps   = _nearest_1d(t_wave_ns, Hs0_v,       t_gps_ns, max_gap_s=3600)
    T02_on_gps   = _nearest_1d(t_wave_ns, T02_v,       t_gps_ns, max_gap_s=3600)

    T_on_gps = np.full((len(t_gps_s), len(depth_cols)), np.nan)
    for j in range(len(depth_cols)):
        T_on_gps[:, j] = _nearest_1d(t_temp_ns, T_valid[:, j], t_gps_ns, max_gap_s=3600)

    # ── Build TS rows ─────────────────────────────────────────────────────────
    ts_rows = []
    for i, ts in enumerate(t_gps_iso):
        row = {
            "time":               ts,
            "latitude":           _fmt(lat[i]),
            "longitude":          _fmt(lon[i]),
            "air_temp_C":         _fmt(Tair_on_gps[i]),
            "skin_temp_C":        _fmt(Tskin_on_gps[i]),
            "wave_height_m":      _fmt(Hs0_on_gps[i]),
            "wave_period_t02_s":  _fmt(T02_on_gps[i]),
        }
        ts_rows.append(row)

    # ── Build TEMP rows (resample TEMP time onto GPS time too) ────────────────
    temp_rows = []
    for i, ts in enumerate(t_gps_iso):
        row = {"time": ts}
        for j, col in enumerate(depth_cols):
            row[col] = _fmt(T_on_gps[i, j])
        temp_rows.append(row)

    return ts_rows, temp_rows


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mask_of(arr):
    if hasattr(arr, "mask"):
        return np.asarray(arr.mask, dtype=bool)
    return np.zeros(len(arr), dtype=bool)


def _to_iso(seconds: np.ndarray, units: str) -> list[str]:
    """Convert seconds-since-epoch array to ISO-8601 UTC strings."""
    dates = nc.num2date(seconds, units, calendar="standard")
    result = []
    for d in dates:
        try:
            dt = datetime(d.year, d.month, d.day, d.hour, d.minute, d.second, tzinfo=timezone.utc)
            result.append(dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        except Exception:
            result.append("")
    return result


def _nearest_1d(t_src: np.ndarray, y_src: np.ndarray,
                t_tgt: np.ndarray, max_gap_s: float = 600) -> np.ndarray:
    """Vectorised nearest-neighbour resampling (int64 nanosecond timestamps)."""
    valid = np.isfinite(y_src)
    out = np.full(len(t_tgt), np.nan)
    if not valid.any():
        return out

    xs = t_src[valid]
    ys = y_src[valid].astype(np.float64)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]

    idx = np.searchsorted(xs, t_tgt)
    idx_r = np.clip(idx,     0, len(xs) - 1)
    idx_l = np.clip(idx - 1, 0, len(xs) - 1)

    dist_r = np.abs(t_tgt - xs[idx_r])
    dist_l = np.abs(t_tgt - xs[idx_l])

    use_left = dist_l <= dist_r
    nn       = np.where(use_left, idx_l, idx_r)
    dist_nn  = np.where(use_left, dist_l, dist_r)

    out = ys[nn].copy()
    out[dist_nn > int(max_gap_s * 1e9)] = np.nan
    return out


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    return f"{v:.6g}"
