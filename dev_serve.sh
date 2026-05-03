#!/usr/bin/env bash
# Run the website locally with live data from the VPS (or local fallback).
# Usage: bash dev_serve.sh [port]
#   Pulls latest CSVs from the VPS via rsync if SSH is reachable, then
#   copies them into website/data/ and serves the site locally.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEBSITE_DIR="${SCRIPT_DIR}/website"
VPS_HOST="root@148.230.70.161"
VPS_CSV_DIR="/opt/arct-collector/data/processed/csv/"
LOCAL_CSV_DIR="${SCRIPT_DIR}/vps_server/data/processed/csv"
PORT="${1:-8000}"

# --- Pull latest CSVs from VPS if reachable ---
if ssh -o BatchMode=yes -o ConnectTimeout=5 "${VPS_HOST}" true 2>/dev/null; then
  echo "Pulling latest CSVs from VPS ..."
  rsync -a --delete "${VPS_HOST}:${VPS_CSV_DIR}" "${LOCAL_CSV_DIR}/"
  echo "  Sync complete."
else
  echo "  VPS not reachable via SSH, using local cached CSVs."
fi

CSV_SRC="${LOCAL_CSV_DIR}/ships"
CSV_DST="${WEBSITE_DIR}/data/ships"

echo "Syncing ship CSVs into website/data/ships/ ..."
mkdir -p "${CSV_DST}"
cp "${CSV_SRC}"/*.csv "${CSV_DST}/"
echo "  $(ls "${CSV_DST}"/*.csv | wc -l) ship CSV files ready."

CSV_SIMBA_SRC="${LOCAL_CSV_DIR}/simba"
CSV_SIMBA_DST="${WEBSITE_DIR}/data/simba"
if ls "${CSV_SIMBA_SRC}"/*.csv 1>/dev/null 2>&1; then
  echo "Syncing SIMBA buoy CSVs into website/data/simba/ ..."
  mkdir -p "${CSV_SIMBA_DST}"
  cp "${CSV_SIMBA_SRC}"/*.csv "${CSV_SIMBA_DST}/"
  echo "  $(ls "${CSV_SIMBA_DST}"/*.csv | wc -l) SIMBA CSV files ready."
else
  echo "  No SIMBA CSVs found, skipping."
fi

CSV_THERM_SRC="${LOCAL_CSV_DIR}/thermistor"
CSV_THERM_DST="${WEBSITE_DIR}/data/thermistor"
if ls "${CSV_THERM_SRC}"/*.csv 1>/dev/null 2>&1; then
  echo "Syncing thermistor buoy CSVs into website/data/thermistor/ ..."
  mkdir -p "${CSV_THERM_DST}"
  cp "${CSV_THERM_SRC}"/*.csv "${CSV_THERM_DST}/"
  echo "  $(ls "${CSV_THERM_DST}"/*.csv | wc -l) thermistor CSV files ready."
else
  echo "  No thermistor CSVs found, skipping."
fi

CSV_ARCTSUM_SRC="${LOCAL_CSV_DIR}/arctsum"
CSV_ARCTSUM_DST="${WEBSITE_DIR}/data/arctsum"
if ls "${CSV_ARCTSUM_SRC}"/*.csv 1>/dev/null 2>&1; then
  echo "Syncing ArctSum buoy CSVs into website/data/arctsum/ ..."
  mkdir -p "${CSV_ARCTSUM_DST}"
  cp "${CSV_ARCTSUM_SRC}"/*.csv "${CSV_ARCTSUM_DST}/"
  echo "  $(ls "${CSV_ARCTSUM_DST}"/*.csv | wc -l) ArctSum CSV files ready."
else
  echo "  No ArctSum CSVs found, skipping."
fi

CSV_SVALMIZ_SRC="${LOCAL_CSV_DIR}/svalmiz"
CSV_SVALMIZ_DST="${WEBSITE_DIR}/data/svalmiz"
if ls "${CSV_SVALMIZ_SRC}"/*.csv 1>/dev/null 2>&1; then
  echo "Syncing SvalMIZ buoy CSVs into website/data/svalmiz/ ..."
  mkdir -p "${CSV_SVALMIZ_DST}"
  cp "${CSV_SVALMIZ_SRC}"/*.csv "${CSV_SVALMIZ_DST}/"
  echo "  $(ls "${CSV_SVALMIZ_DST}"/*.csv | wc -l) SvalMIZ CSV files ready."
else
  echo "  No SvalMIZ CSVs found, skipping."
fi

CSV_IABP_SRC="${LOCAL_CSV_DIR}/iabp"
CSV_IABP_DST="${WEBSITE_DIR}/data/iabp"
if ls "${CSV_IABP_SRC}"/*.csv 1>/dev/null 2>&1; then
  echo "Syncing IABP buoy CSVs into website/data/iabp/ ..."
  mkdir -p "${CSV_IABP_DST}"
  cp "${CSV_IABP_SRC}"/*.csv "${CSV_IABP_DST}/"
  # Copy the JSON index too
  [ -f "${CSV_IABP_SRC}/_index.json" ] && cp "${CSV_IABP_SRC}/_index.json" "${CSV_IABP_DST}/"
  echo "  $(ls "${CSV_IABP_DST}"/*.csv | wc -l) IABP CSV files ready."
else
  echo "  No IABP CSVs found, skipping."
fi

CSV_SVALBARD_SRC="${LOCAL_CSV_DIR}/svalbard"
CSV_SVALBARD_DST="${WEBSITE_DIR}/data/svalbard"
if ls "${CSV_SVALBARD_SRC}"/*.csv 1>/dev/null 2>&1; then
  echo "Syncing Svalbard station CSVs into website/data/svalbard/ ..."
  mkdir -p "${CSV_SVALBARD_DST}"
  cp "${CSV_SVALBARD_SRC}"/*.csv "${CSV_SVALBARD_DST}/"
  echo "  $(ls "${CSV_SVALBARD_DST}"/*.csv | wc -l) Svalbard CSV files ready."
else
  echo "  No Svalbard CSVs found, skipping."
fi

CSV_NORTHNO_SRC="${LOCAL_CSV_DIR}/north_norway"
CSV_NORTHNO_DST="${WEBSITE_DIR}/data/north_norway"
if ls "${CSV_NORTHNO_SRC}"/*.csv 1>/dev/null 2>&1; then
  echo "Syncing Northern Norway station CSVs into website/data/north_norway/ ..."
  mkdir -p "${CSV_NORTHNO_DST}"
  cp "${CSV_NORTHNO_SRC}"/*.csv "${CSV_NORTHNO_DST}/"
  echo "  $(ls "${CSV_NORTHNO_DST}"/*.csv | wc -l) Northern Norway CSV files ready."
else
  echo "  No Northern Norway CSVs found, skipping."
fi

CSV_OFFSHORE_SRC="${LOCAL_CSV_DIR}/offshore"
CSV_OFFSHORE_DST="${WEBSITE_DIR}/data/offshore"
if ls "${CSV_OFFSHORE_SRC}"/*.csv 1>/dev/null 2>&1; then
  echo "Syncing Offshore platform CSVs into website/data/offshore/ ..."
  mkdir -p "${CSV_OFFSHORE_DST}"
  cp "${CSV_OFFSHORE_SRC}"/*.csv "${CSV_OFFSHORE_DST}/"
  echo "  $(ls "${CSV_OFFSHORE_DST}"/*.csv | wc -l) Offshore CSV files ready."
else
  echo "  No Offshore CSVs found, skipping."
fi

echo "Starting local server on http://localhost:${PORT}"
echo "Press Ctrl-C to stop."
cd "${WEBSITE_DIR}"
python3 -m http.server "${PORT}"
