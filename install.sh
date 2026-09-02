#!/bin/bash
# awe-some-wallpapers installer. Idempotent — rerun to update.
#   ./install.sh            primary: intake + curation + rotation on this Mac
#   ./install.sh --replica  replica: mirror the primary via iCloud Drive
# Preserves config.json and taste.md. Agents run through a small exec helper
# (helper.c) that can be granted Full Disk Access if a Mac's TCC demands it,
# and write their logs to ~/Library/Logs.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.wallpaper-rotator"
AGENTS="$HOME/Library/LaunchAgents"
HELPER="$HOME/.local/bin/wallpaper-helper"
uid=$(id -u)

mkdir -p "$BASE" "$HOME/.local/bin" "$AGENTS" "$HOME/Library/Logs"
if command -v clang >/dev/null; then clang -O2 -o "$HELPER" "$REPO/helper.c"; else HELPER=""; fi
cp "$REPO/bin/wp" "$HOME/.local/bin/wp"; chmod +x "$HOME/.local/bin/wp"

plist() {  # label, program-args-xml, schedule-xml
  cat > "$AGENTS/$1.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array>${HELPER:+<string>$HELPER</string>}$2</array>
  $3
  <key>StandardOutPath</key><string>$HOME/Library/Logs/$1.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/$1.log</string>
</dict></plist>
EOF
  launchctl bootout "gui/$uid/$1" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$AGENTS/$1.plist"
}

if [[ "${1:-}" == "--replica" ]]; then
  IC="$HOME/Library/Mobile Documents/com~apple~CloudDocs/AweSomeWallpapers"
  [[ -d "$IC/state" && -d "$IC/images" ]] || { echo "iCloud folder not synced yet: $IC"; exit 1; }
  [[ -e "$BASE" ]] || ln -s "$IC/state" "$BASE"
  [[ -e "$HOME/Pictures/WorldWallpapers" ]] || ln -s "$IC/images" "$HOME/Pictures/WorldWallpapers"
  touch "$HOME/.wallpaper-replica"   # local marker: this machine appends to events.<host>.jsonl
  cp "$REPO/rotator/mirror.sh" "$REPO/rotator/apply.sh" "$REPO/rotator/seed.sh" "$REPO/rotator/set_wallpaper.py" "$REPO/rotator/info.sh" "$REPO/rotator/events.py" "$HOME/.local/bin/" 2>/dev/null || true
  plist "com.$USER.wallpaper-mirror" \
    "<string>/bin/bash</string><string>$HOME/.local/bin/mirror.sh</string>" \
    "<key>WatchPaths</key><array><string>$IC/state/current.txt</string></array><key>StartInterval</key><integer>300</integer><key>MaterializeDatalessFiles</key><true/>"
  echo "Replica installed. Turn OFF 'Optimize Mac Storage' for iCloud Drive, then run: wp seed"
  exit 0
fi

cp "$REPO"/rotator/*.py "$REPO"/rotator/*.sh "$REPO/rotator/CURATOR.md" "$BASE/"
chmod +x "$BASE"/*.py "$BASE"/*.sh
mkdir -p "$BASE/queue" "$HOME/Pictures/WorldWallpapers/archive"
[[ -f "$BASE/config.json" ]] || cp "$REPO/config.example.json" "$BASE/config.json"
[[ -f "$BASE/taste.md" ]]    || cp "$REPO/rotator/taste.seed.md" "$BASE/taste.md"

plist "com.$USER.wallpaper-rotate" \
  "<string>/bin/bash</string><string>$BASE/rotate.sh</string>" \
  "<key>StartInterval</key><integer>10800</integer>"
plist "com.$USER.wallpaper-fetch" \
  "<string>/usr/bin/python3</string><string>$BASE/fetch.py</string>" \
  "<key>StartCalendarInterval</key><array><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict><dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict></array>"

echo "Installed."
echo "1. Put your Unsplash key and contact email in $BASE/config.json"
echo "2. wp fetch          (first intake + curation)"
echo "3. wp seed           (one-time macOS grant; desktop + lock screen)"
