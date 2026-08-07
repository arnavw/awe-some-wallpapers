#!/bin/bash
# awe-some-wallpapers installer. Idempotent — safe to re-run for updates.
# Copies the rotator into ~/.wallpaper-rotator, installs the `wp` command,
# and loads the two launchd agents (3-hourly rotation, daily 9am fetch+curate).
# Preserves an existing config.json and TASTE.md.

set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.wallpaper-rotator"
AGENTS="$HOME/Library/LaunchAgents"

mkdir -p "$BASE/logs" "$BASE/queue" "$HOME/Pictures/WorldWallpapers" "$HOME/.local/bin" "$AGENTS"

cp "$REPO"/rotator/*.py "$REPO"/rotator/*.sh "$REPO"/rotator/CURATOR.md "$BASE/"
chmod +x "$BASE"/*.py "$BASE"/*.sh
[[ -f "$BASE/config.json" ]] || cp "$REPO/config.example.json" "$BASE/config.json"
[[ -f "$BASE/TASTE.md" ]] || cp "$REPO/rotator/TASTE.seed.md" "$BASE/TASTE.md"
[[ -f "$BASE/explore_topics.txt" ]] || cp "$REPO/rotator/explore_topics.seed.txt" "$BASE/explore_topics.txt"
cp "$REPO/bin/wp" "$HOME/.local/bin/wp"
chmod +x "$HOME/.local/bin/wp"

uid=$(id -u)
cat > "$AGENTS/com.$USER.wallpaper-rotate.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.$USER.wallpaper-rotate</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$BASE/rotate.sh</string></array>
    <key>StartInterval</key><integer>10800</integer>
    <key>StandardOutPath</key><string>$BASE/logs/rotate.log</string>
    <key>StandardErrorPath</key><string>$BASE/logs/rotate.log</string>
</dict>
</plist>
EOF
cat > "$AGENTS/com.$USER.wallpaper-fetch.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.$USER.wallpaper-fetch</string>
    <key>ProgramArguments</key>
    <array><string>/usr/bin/python3</string><string>$BASE/fetch.py</string></array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StandardOutPath</key><string>$BASE/logs/fetch.log</string>
    <key>StandardErrorPath</key><string>$BASE/logs/fetch.log</string>
</dict>
</plist>
EOF

for name in rotate fetch; do
  launchctl bootout "gui/$uid/com.$USER.wallpaper-$name" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$AGENTS/com.$USER.wallpaper-$name.plist"
done

echo "Installed."
echo "1. Add your Unsplash access key to $BASE/config.json (optional but recommended)"
echo "2. Adjust the screen aspect in rotator/compose.py + refine.py if not a 16\" MBP (SCREEN_ASPECT)"
echo "3. Run: wp fetch   (downloads, then Claude curates the queue)"
