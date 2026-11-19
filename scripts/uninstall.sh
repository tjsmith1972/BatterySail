#!/bin/bash
# Remove BatterySail and restore stock charging (BCLM back to 100).
# Run with sudo:
#   sudo bash scripts/uninstall.sh
set -euo pipefail

LABEL="com.sunfishcode.batterysail"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"

# Restore the SMC ceiling FIRST, while the package is still installed.
if [ -d /usr/local/lib/batterysail ]; then
  PYTHONPATH=/usr/local/lib /usr/bin/python3 -m batterysail.cli restore || true
fi

launchctl unload "${PLIST}" 2>/dev/null || true
rm -f "${PLIST}"
rm -rf /usr/local/lib/batterysail
rm -f /etc/batterysail.json /etc/batterysail-state.json

echo "BatterySail removed; BCLM restored to 100%."
