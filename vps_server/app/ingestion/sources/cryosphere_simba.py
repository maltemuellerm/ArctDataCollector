"""CryosphereInnovation API source for SIMBA ice buoys.

Fetches JSON data for a single deployment and returns:
  - raw_json : the full parsed response (saved as-is for inspection)
  - rows     : list of flat dicts ready for CSV writing

Because the exact response schema is confirmed on first live run, the
flattening logic handles both a bare list and a dict with a "data" key,
and writes every scalar field it finds.  Once the real schema is known
this can be tightened.
"""

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def fetch_simba_deployment(deployment_id: str, base_url: str, api_key: str) -> tuple[dict | list, list[dict]]:
    """Fetch data for *deployment_id* from the CryosphereInnovation API.

    Returns
    -------
    (raw_json, rows)
        raw_json  – the full parsed JSON response
        rows      – list of flat dicts suitable for CSV output
    """
    url = f"{base_url.rstrip('/')}/{deployment_id}"
    logger.info("Fetching SIMBA deployment %s from %s", deployment_id, url)

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "ArctDataCollector/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Connection error fetching {url}: {exc}") from exc

    raw_json = json.loads(raw_bytes.decode("utf-8", errors="replace"))
    rows = _flatten_response(raw_json, deployment_id)
    logger.info("Fetched %d rows for deployment %s", len(rows), deployment_id)
    return raw_json, rows


def _flatten_response(raw_json, deployment_id: str) -> list[dict]:
    """Flatten JSON response to a list of flat dicts for CSV output.

    The CryosphereInnovation API returns a bare list of observation dicts.
    Each record has a Unix epoch ``time_stamp`` which is converted to ISO-8601.
    The 160 ``dtc_values_*`` columns (snow/ice temperature profile) are kept
    as individual columns so the CSV is fully self-contained.
    """
    from datetime import datetime, timezone

    if isinstance(raw_json, list):
        records = raw_json
    elif isinstance(raw_json, dict):
        for key in ("data", "measurements", "observations", "records"):
            if isinstance(raw_json.get(key), list):
                records = raw_json[key]
                break
        else:
            records = [raw_json]
    else:
        logger.warning("Unexpected JSON type %s for %s", type(raw_json), deployment_id)
        return []

    rows = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        flat = {"deployment_id": deployment_id}
        for k, v in rec.items():
            if k == "time_stamp" and isinstance(v, (int, float)):
                # Convert Unix epoch to ISO-8601 UTC string
                flat["time_stamp"] = datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
            elif isinstance(v, (dict, list)):
                import json as _json
                flat[k] = _json.dumps(v)
            else:
                flat[k] = v if v is not None else ""
        rows.append(flat)

    return rows
