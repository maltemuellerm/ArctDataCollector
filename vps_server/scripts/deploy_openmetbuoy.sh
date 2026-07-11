#!/usr/bin/env bash
# Deploy the OpenMetBuoy-Arctic static website to the VPS.
#
# What this script does:
#   1. Rsyncs the OpenMetBuoy-Arctic site to /var/www/openmetbuoy-arctic.com/
#   2. Installs the arct-proxy.conf nginx snippet
#   3. Installs and enables the openmetbuoy-arctic.com nginx server block
#   4. Tests and reloads nginx
#   5. Optionally obtains a Let's Encrypt certificate via Certbot
#
# Usage:
#   bash vps_server/scripts/deploy_openmetbuoy.sh [--skip-certbot]
#
# Set OMB_SRC to override the default OpenMetBuoy-Arctic source path:
#   OMB_SRC=/path/to/OpenMetBuoy-Arctic bash deploy_openmetbuoy.sh

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
VPS_HOST="root@148.230.70.161"
VPS_WEBROOT="/var/www/openmetbuoy-arctic.com"
DOMAIN="openmetbuoy-arctic.com"

# Default source: sibling folder of the ArctDataCollector workspace
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGINX_DIR="${SCRIPT_DIR}/../nginx"
OMB_SRC="${OMB_SRC:-/home/maltem/work/websites/OpenMetBuoy-Arctic}"

SKIP_CERTBOT=0
[[ "${1:-}" == "--skip-certbot" ]] && SKIP_CERTBOT=1

# ── Preflight ────────────────────────────────────────────────────────────────
if [[ ! -d "${OMB_SRC}" ]]; then
  echo "ERROR: OpenMetBuoy-Arctic source not found at: ${OMB_SRC}"
  echo "       Set OMB_SRC=/path/to/OpenMetBuoy-Arctic and retry."
  exit 1
fi

echo "==> Source : ${OMB_SRC}"
echo "==> Target : ${VPS_HOST}:${VPS_WEBROOT}"
echo ""

# ── 1. Sync website files ────────────────────────────────────────────────────
echo "--- [1/5] Syncing OpenMetBuoy-Arctic site to VPS ..."
ssh "${VPS_HOST}" "mkdir -p ${VPS_WEBROOT}"

rsync -az --delete \
  --exclude=".git/" \
  --exclude="nginx/" \
  --exclude="*.md" \
  --exclude="src/" \
  --exclude="server/" \
  --exclude="*.php" \
  --exclude="decoded_fixes.geojson" \
  --exclude="master-decoded.json" \
  --exclude="rockblock-decoded.log" \
  "${OMB_SRC}/" \
  "${VPS_HOST}:${VPS_WEBROOT}/"

echo "    Done."

# ── 2. Install nginx snippets ────────────────────────────────────────────────
echo "--- [2/5] Installing nginx snippets ..."
ssh "${VPS_HOST}" "mkdir -p /etc/nginx/snippets"
scp "${NGINX_DIR}/arct-proxy.conf"      "${VPS_HOST}:/etc/nginx/snippets/arct-proxy.conf"
scp "${NGINX_DIR}/rockblock-proxy.conf" "${VPS_HOST}:/etc/nginx/snippets/rockblock-proxy.conf"
echo "    Installed: arct-proxy.conf and rockblock-proxy.conf"

# ── 3. Install openmetbuoy server block ─────────────────────────────────────
echo "--- [3/5] Installing openmetbuoy-arctic.com nginx server block ..."
scp "${NGINX_DIR}/openmetbuoy.conf" \
  "${VPS_HOST}:/etc/nginx/sites-available/openmetbuoy-arctic.com"

ssh "${VPS_HOST}" "
  ln -sf /etc/nginx/sites-available/openmetbuoy-arctic.com \
         /etc/nginx/sites-enabled/openmetbuoy-arctic.com
  # Disable the default site if it is still enabled
  rm -f /etc/nginx/sites-enabled/default
"
echo "    Enabled: openmetbuoy-arctic.com"

# ── 4. Ensure web root data files exist ─────────────────────────────────────
# The Flask decoder (running as root) writes decoded_fixes.geojson and
# master-decoded.json directly to the web root via atomic rename.
# Seed them with valid empty structures so nginx never serves a missing file.
echo "--- [4/5] Seeding web root data files ..."
ssh "${VPS_HOST}" "
  [ -s ${VPS_WEBROOT}/decoded_fixes.geojson ] || \
    echo '{\"type\":\"FeatureCollection\",\"features\":[]}' \
      > ${VPS_WEBROOT}/decoded_fixes.geojson
  [ -s ${VPS_WEBROOT}/master-decoded.json ] || \
    echo '[]' > ${VPS_WEBROOT}/master-decoded.json
"
echo "    Done."

# ── 5. Test and reload nginx ─────────────────────────────────────────────────
echo "--- [5/5] Testing and reloading nginx ..."
ssh "${VPS_HOST}" "nginx -t && systemctl reload nginx"
echo "    Nginx reloaded."
echo ""
echo "HTTP site is live at: http://${DOMAIN}/"
echo ""

# ── 6. Optional: Certbot HTTPS ───────────────────────────────────────────────
if [[ "${SKIP_CERTBOT}" -eq 1 ]]; then
  echo "--- Skipping Certbot (--skip-certbot flag set)."
  echo "    Run manually on the VPS when DNS has propagated:"
  echo "    certbot --nginx -d ${DOMAIN} -d www.${DOMAIN}"
else
  echo "--- [6/6] Obtaining Let's Encrypt certificate via Certbot ..."
  echo "    (This will fail if DNS has not propagated yet.)"
  echo "    To skip this step, run with --skip-certbot"
  echo ""
  ssh "${VPS_HOST}" "
    # Install certbot if missing
    if ! command -v certbot &>/dev/null; then
      apt-get install -y certbot python3-certbot-nginx
    fi
    certbot --nginx \
      --non-interactive \
      --agree-tos \
      --redirect \
      -d ${DOMAIN} \
      -d www.${DOMAIN}
  "
  echo ""
  echo "HTTPS site is live at: https://${DOMAIN}/"
fi
