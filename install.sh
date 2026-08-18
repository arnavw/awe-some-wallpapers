#!/bin/bash
# awe-some-wallpapers installer. Idempotent — safe to re-run for updates.
# Copies the rotator into ~/.wallpaper-rotator, installs the `wp` command,
# and loads the two launchd agents (3-hourly rotation, daily 9am fetch+curate).
# Preserves an existing config.json and TASTE.md.

set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/.wallpaper-rotator"
AGENTS="$HOME/Library/LaunchAgents"
HELPER="$HOME/.local/bin/wallpaper-helper"

# When state lives in iCloud Drive (~/Library/Mobile Documents), launchd jobs
# can be TCC-blocked from reading it. All agents therefore run through a tiny
# exec wrapper that can be granted Full Disk Access once if needed.
build_helper() {
  mkdir -p "$HOME/.local/bin"
  if command -v clang >/dev/null; then
    clang -O2 -o "$HELPER" "$REPO/helper.c"
  else
    echo "warning: clang not found (install Xcode Command Line Tools); agents run without the helper" >&2
    HELPER=""
  fi
}

# --replica: this Mac mirrors a primary whose state/images are shared via
# iCloud Drive (AweSomeWallpapers/). No fetching, curation, or rotation here —
# just symlinks into the synced folders and a mirror agent that follows
# current.txt. Run the default install on exactly one machine (the primary).
if [[ "${1:-}" == "--replica" ]]; then
  ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs/AweSomeWallpapers"
  if [[ ! -d "$ICLOUD/state" || ! -d "$ICLOUD/images" ]]; then
    echo "iCloud folder not synced yet: $ICLOUD" >&2
    echo "Enable iCloud Drive with the same Apple ID and wait for AweSomeWallpapers to appear." >&2
    exit 1
  fi
  mkdir -p "$HOME/.local/bin" "$AGENTS"
  build_helper
  [[ -e "$BASE" ]] || ln -s "$ICLOUD/state" "$BASE"
  [[ -e "$HOME/Pictures/WorldWallpapers" ]] || ln -s "$ICLOUD/images" "$HOME/Pictures/WorldWallpapers"
  cp "$REPO/bin/wp" "$HOME/.local/bin/wp" && chmod +x "$HOME/.local/bin/wp"
  cat > "$AGENTS/com.$USER.wallpaper-mirror.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.$USER.wallpaper-mirror</string>
    <key>ProgramArguments</key>
    <array>${HELPER:+<string>$HELPER</string>}<string>/bin/bash</string><string>$BASE/mirror.sh</string></array>
    <key>WatchPaths</key>
    <array><string>$ICLOUD/state/current.txt</string></array>
    <key>StartInterval</key><integer>300</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>$HOME/.wallpaper-mirror.log</string>
    <key>StandardErrorPath</key><string>$HOME/.wallpaper-mirror.log</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/com.$USER.wallpaper-mirror" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/com.$USER.wallpaper-mirror.plist"
  echo "Replica installed — this Mac now mirrors the primary's wallpaper."
  echo "Tip: turn OFF 'Optimize Mac Storage' for iCloud Drive so images stay downloaded."
  echo "If ~/.wallpaper-mirror.log shows 'Operation not permitted': grant Full Disk"
  echo "Access to $HOME/.local/bin/wallpaper-helper (System Settings -> Privacy & Security)."
  exit 0
fi

mkdir -p "$BASE/logs" "$BASE/queue" "$HOME/Pictures/WorldWallpapers" "$HOME/.local/bin" "$AGENTS"

cp "$REPO"/rotator/*.py "$REPO"/rotator/*.sh "$REPO"/rotator/CURATOR.md "$BASE/"
chmod +x "$BASE"/*.py "$BASE"/*.sh
[[ -f "$BASE/config.json" ]] || cp "$REPO/config.example.json" "$BASE/config.json"
[[ -f "$BASE/TASTE.md" ]] || cp "$REPO/rotator/TASTE.seed.md" "$BASE/TASTE.md"
[[ -f "$BASE/explore_topics.txt" ]] || cp "$REPO/rotator/explore_topics.seed.txt" "$BASE/explore_topics.txt"
cp "$REPO/bin/wp" "$HOME/.local/bin/wp"
chmod +x "$HOME/.local/bin/wp"

uid=$(id -u)
build_helper
mkdir -p "$HOME/Library/Logs"
cat > "$AGENTS/com.$USER.wallpaper-rotate.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.$USER.wallpaper-rotate</string>
    <key>ProgramArguments</key>
    <array>${HELPER:+<string>$HELPER</string>}<string>/bin/bash</string><string>$BASE/rotate.sh</string></array>
    <key>StartInterval</key><integer>10800</integer>
    <key>StandardOutPath</key><string>$HOME/Library/Logs/wallpaper-rotate.log</string>
    <key>StandardErrorPath</key><string>$HOME/Library/Logs/wallpaper-rotate.log</string>
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
    <array>${HELPER:+<string>$HELPER</string>}<string>/usr/bin/python3</string><string>$BASE/fetch.py</string></array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StandardOutPath</key><string>$HOME/Library/Logs/wallpaper-fetch.log</string>
    <key>StandardErrorPath</key><string>$HOME/Library/Logs/wallpaper-fetch.log</string>
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
