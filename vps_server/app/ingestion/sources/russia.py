"""OGIMET SYNOP (FM-12) source for Russian Arctic / Franz Josef Land / Novaya Zemlya.

Fetches near-real-time surface observations (~1-6 h lag) from OGIMET, which
aggregates WMO Global Telecommunication System (GTS) SYNOP messages.

API:    https://www.ogimet.com/cgi-bin/getsynop
Auth:   None (public, no key required).
Format: CSV lines -- ``station,YYYY,MM,DD,HH,mm,<FM-12 SYNOP message>==``
Lag:    ~1-6 hours.
History: OGIMET retains ~60 days; older data held from prior NCEI ISD runs.

The 5-digit WMO block number used by OGIMET equals the first 5 characters of
the 11-char NCEI station IDs (USAF code).

HTTP note: OGIMET serves data ~100x faster via HTTP/2 (curl) than via Python
urllib/requests on some server IPs.  This module therefore uses ``curl`` as a
subprocess if it is available, falling back to urllib otherwise.

Output CSV columns (shared land-station layout):
    time, station_id, latitude, longitude,
    air_temp, dew_point_temp, humidity,
    wind_direction, wind_speed, air_pressure
"""

import logging
import math
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.ogimet.com/cgi-bin/getsynop"
# OGIMET retains roughly 60 days; cap lookback to avoid empty responses.
_MAX_LOOKBACK_DAYS = 58
# Timeout for each HTTP request (seconds).
_TIMEOUT = 30

# Detect curl once at module load time.
_CURL = shutil.which("curl")


# --------------------------------------------------------------------------
# FM-12 SYNOP decoder helpers
# --------------------------------------------------------------------------

def _sign_temp(s: str, ttt: str) -> str:
    """Decode a SYNOP signed temperature group (sTTT, 1/10 deg C)."""
    if s == "/" or "/" in ttt or ttt in ("999",):
        return ""
    try:
        val = int(ttt) / 10.0
        if s == "1":
            val = -val
        return str(round(val, 1))
    except ValueError:
        return ""


def _decode_pressure(pppp: str) -> str:
    """Decode a 4-digit SYNOP pressure group (tenths of hPa, leading digit dropped).

    Values 0000-4999 -> (10000 + PPPP) / 10  -> 1000.0-1499.9 hPa.
    Values 5000-9999 -> PPPP / 10             ->  500.0- 999.9 hPa.
    """
    if not pppp or "/" in pppp:
        return ""
    try:
        v = int(pppp)
        hpa = (10000 + v) / 10.0 if v < 5000 else v / 10.0
        return str(round(hpa, 1))
    except ValueError:
        return ""


def _rh_from_t_td(t_str: str, td_str: str) -> str:
    """Estimate relative humidity from temperature and dewpoint (Magnus formula)."""
    if not t_str or not td_str:
        return ""
    try:
        t  = float(t_str)
        td = float(td_str)
        gamma_t  = 17.625 * t  / (243.04 + t)
        gamma_td = 17.625 * td / (243.04 + td)
        rh = 100.0 * math.exp(gamma_td - gamma_t)
        return str(round(min(max(rh, 0.0), 100.0), 1))
    except (ValueError, ZeroDivisionError):
        return ""


def _decode_synop_line(
    line: str, station_id: str, fixed_lat: float, fixed_lon: float
) -> "dict | None":
    """Parse one OGIMET CSV line into an observation dict.

    Line format::
        23078,2026,04,30,00,00,AAXX 30001 23078 12570 61306 11059 21080 30106 40189==
    """
    line = line.strip().rstrip("=").strip()
    if not line:
        return None

    parts = line.split(",", 6)
    if len(parts) < 7:
        return None
    try:
        year, month, day, hour, minute = (int(parts[i]) for i in range(1, 6))
    except ValueError:
        return None

    ts = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:00"
    tokens = parts[6].strip().split()
    if not tokens:
        return None
    if tokens[0] == "AAXX":
        tokens = tokens[1:]
    if len(tokens) < 3:
        return None

    # YYGGiw: last char = wind indicator (1=m/s, 3/4=knots)
    try:
        in_knots = tokens[0][-1] in ("3", "4")
    except IndexError:
        in_knots = False

    groups = tokens[2:]   # skip YYGGiw and IIiii

    # groups[0] = iRiXhVV (skip)
    # groups[1] = Nddff   (cloud/wind)
    wind_dir = ""
    wind_spd = ""
    if len(groups) > 1:
        g = groups[1]
        m = re.fullmatch(r"([0-9/])([0-9/]{2})([0-9/]{2})", g)
        if m:
            dd_str, ff_str = m.group(2), m.group(3)
            if dd_str.isdigit():
                dd = int(dd_str)
                wind_dir = "" if dd in (0, 99) else str(dd * 10)
            if ff_str.isdigit():
                ff = int(ff_str)
                if in_knots:
                    ff = round(ff * 0.514444, 1)
                wind_spd = str(ff)

    air_temp = ""
    dew_temp = ""
    pressure = ""

    for g in groups[2:]:
        if g == "333":
            break
        if len(g) != 5 or g[0] == "/":
            continue
        gid = g[0]
        if gid == "1":
            air_temp = _sign_temp(g[1], g[2:])
        elif gid == "2":
            dew_temp = _sign_temp(g[1], g[2:])
        elif gid == "4":
            pressure = _decode_pressure(g[1:])
        elif gid == "3" and not pressure:
            pressure = _decode_pressure(g[1:])

    return {
        "time":           ts,
        "station_id":     station_id,
        "latitude":       str(fixed_lat),
        "longitude":      str(fixed_lon),
        "air_temp":       air_temp,
        "dew_point_temp": dew_temp,
        "humidity":       _rh_from_t_td(air_temp, dew_temp),
        "wind_direction": wind_dir,
        "wind_speed":     wind_spd,
        "air_pressure":   pressure,
    }


# --------------------------------------------------------------------------
# HTTP fetch (curl preferred for HTTP/2 speed, urllib as fallback)
# --------------------------------------------------------------------------

def _http_get(url: str) -> str:
    """Fetch URL, using curl if available (much faster on some hosts)."""
    if _CURL:
        try:
            result = subprocess.run(
                [_CURL, "-s", "--max-time", str(_TIMEOUT),
                 "-A", "ArctDataCollector/1.0", url],
                capture_output=True, text=True, timeout=_TIMEOUT + 5,
            )
            if result.returncode == 0:
                return result.stdout
            logger.warning("curl exited %d: %s", result.returncode, result.stderr[:200])
        except subprocess.TimeoutExpired:
            logger.warning("curl timed out for %s", url)
        return ""

    # Fall back to urllib
    req = urllib.request.Request(url, headers={"User-Agent": "ArctDataCollector/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        logger.warning("urllib request failed: %s", exc)
        return ""


# --------------------------------------------------------------------------
# Public fetch function
# --------------------------------------------------------------------------

def fetch_russia(
    station_id: str,
    fixed_lat: float,
    fixed_lon: float,
    since: datetime,
) -> "list[dict]":
    """Download and parse SYNOP observations from OGIMET.

    Parameters
    ----------
    station_id:
        11-char NCEI USAF+WBAN code; first 5 chars = WMO block for OGIMET.
    fixed_lat / fixed_lon:
        Station coordinates (OGIMET does not return position data).
    since:
        Fetch observations at or after this UTC datetime.  Capped at
        ``now - _MAX_LOOKBACK_DAYS`` because OGIMET only keeps ~60 days.
    """
    now = datetime.now(tz=timezone.utc)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    effective_since = max(since, now - timedelta(days=_MAX_LOOKBACK_DAYS))

    wmo_block = station_id[:5]
    begin_str = effective_since.strftime("%Y%m%d%H%M")
    end_str   = now.strftime("%Y%m%d%H%M")

    url = f"{_BASE_URL}?block={wmo_block}&begin={begin_str}&end={end_str}"
    logger.info(
        "Fetching OGIMET SYNOP for %s (block %s, %s -> now)",
        station_id, wmo_block, effective_since.date(),
    )
    logger.debug("  URL: %s", url)

    raw = _http_get(url)

    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = _decode_synop_line(line, station_id, fixed_lat, fixed_lon)
        if row:
            rows.append(row)

    # Deduplicate by exact timestamp
    by_ts: "dict[str, dict]" = {}
    for row in rows:
        by_ts[row["time"]] = row
    rows = sorted(by_ts.values(), key=lambda r: r["time"])

    logger.info("  %d observations decoded for %s", len(rows), station_id)
    return rows
