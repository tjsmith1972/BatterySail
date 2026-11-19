#!/bin/bash
# Build and install the BatterySail menu bar app. User-level, no sudo:
#   bash scripts/install_menubar.sh
# Compiles menubar/BatterySailMenu.swift with swiftc into
# ~/Applications/BatterySail Menu.app and registers a user LaunchAgent
# so it starts at login. Re-running rebuilds and restarts it.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/BatterySail Menu.app"
LABEL="com.sunfishcode.batterysail.menubar"
AGENT="$HOME/Library/LaunchAgents/${LABEL}.plist"

echo "Building BatterySail Menu from ${REPO_DIR}/menubar"
mkdir -p "${APP}/Contents/MacOS"
swiftc -O "${REPO_DIR}/menubar/BatterySailMenu.swift" -o "${APP}/Contents/MacOS/BatterySailMenu"
cp "${REPO_DIR}/menubar/Info.plist" "${APP}/Contents/Info.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "${AGENT}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${APP}/Contents/MacOS/BatterySailMenu</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

launchctl unload "${AGENT}" 2>/dev/null || true
launchctl load "${AGENT}"

echo "Installed and running — look for the charge and mode in your menu bar."
echo "It reads /etc/batterysail-state.json, published by the daemon;"
echo "if it says the daemon is not reporting, install the daemon first:"
echo "  sudo bash scripts/install.sh"
