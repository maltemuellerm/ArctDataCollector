#!/usr/bin/env bash# Deploy the ArctDataCollector ship-fetch code to /opt/arct-collector.
# Safe to run alongside the existing /opt/decoder service.set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="${BASE_DIR}/.venv"

python3 -m venv "${VENV_PATH}"
source "${VENV_PATH}/bin/activate"
pip install --upgrade pip
pip install -r "${BASE_DIR}/requirements.txt"

echo "Bootstrap complete. Activate with: source ${VENV_PATH}/bin/activate"
