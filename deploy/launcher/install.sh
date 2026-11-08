#!/usr/bin/env bash
# Phase 7: put the Macro Tracker icon in the app menu (and dock, if pinned).
# .desktop files need absolute paths, so this writes one for this machine.
# Run from anywhere: bash deploy/launcher/install.sh
# @author Tony Shin <tonyshin4065@gmail.com>
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/calorie-tracker/Calorie-Macro-Tracker"
LAUNCHER="$APP_DIR/deploy/launcher/macro-tracker.sh"   # via the symlink: no spaces in Exec

mkdir -p "$HOME/.local/share/icons" "$HOME/.local/share/applications"
cp "$HERE/macro-tracker.svg" "$HOME/.local/share/icons/macro-tracker.svg"
chmod +x "$HERE/macro-tracker.sh"

cat > "$HOME/.local/share/applications/macro-tracker.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Macro Tracker
Comment=Track calories and macros
Exec=$LAUNCHER
Icon=$HOME/.local/share/icons/macro-tracker.svg
Terminal=false
Categories=Utility;
StartupNotify=false
Actions=stop;

[Desktop Action stop]
Name=Stop Macro Tracker
Exec=$LAUNCHER stop
DESKTOP

command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true
command -v desktop-file-validate >/dev/null && desktop-file-validate "$HOME/.local/share/applications/macro-tracker.desktop" || true
echo "Installed. Search 'Macro Tracker' in Activities, then right-click -> Pin to Dash."
