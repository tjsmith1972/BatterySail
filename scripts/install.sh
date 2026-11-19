#!/bin/bash
# Install BatterySail as a root LaunchDaemon. Run with sudo:
#   sudo bash scripts/install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.sunfishcode.batterysail"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"

echo "Installing BatterySail from ${REPO_DIR}"

# Package -> /usr/local/lib/batterysail (plist puts /usr/local/lib on PYTHONPATH)
mkdir -p /usr/local/lib
rm -rf /usr/local/lib/batterysail
cp -R "${REPO_DIR}/src/batterysail" /usr/local/lib/batterysail

# Config: keep an existing one, otherwise seed from the example
if [ ! -f /etc/batterysail.json ]; then
  cp "${REPO_DIR}/config.example.json" /etc/batterysail.json
  echo "Seeded /etc/batterysail.json from config.example.json"
fi

# LaunchDaemon
cp "${REPO_DIR}/launchd/${LABEL}.plist" "${PLIST}"
chown root:wheel "${PLIST}"
chmod 644 "${PLIST}"

launchctl unload "${PLIST}" 2>/dev/null || true
launchctl load "${PLIST}"

echo "Installed and loaded. Check with:"
echo "  tail -f /var/log/batterysail.log"
echo "  PYTHONPATH=${REPO_DIR}/src python3 -m batterysail.cli status"
