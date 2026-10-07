#!/bin/bash
# awe-some-wallpapers installer. Idempotent — rerun to update.
#   ./install.sh             primary: intake, curation and rotation run on this Mac
#   ./install.sh --follower  follower: show the primary's wallpapers through iCloud
#                            Drive (also migrates an old --replica install)
# Preserves config.json and taste.md. launchd agents run through a small exec
# helper (helper.c) that holds the Full Disk Access grant iCloud Drive needs.
# It is built once and kept: a rebuilt binary would no longer match that grant.
# Agents log to ~/Library/Logs.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
HELPER="$HOME/.local/bin/wallpaper-helper"
IC="$HOME/Library/Mobile Documents/com~apple~CloudDocs/AweSomeWallpapers"
uid=$(id -u)

mkdir -p "$HOME/.local/bin" "$AGENTS" "$HOME/Library/Logs"
if [[ ! -x "$HELPER" ]] && command -v clang >/dev/null; then
  clang -O2 -o "$HELPER" "$REPO/helper.c"
fi
[[ -x "$HELPER" ]] || HELPER=""

# plist LABEL PROGRAM-ARGS-XML SCHEDULE-XML — write and (re)load one agent.
# MaterializeDatalessFiles: reading an iCloud file the OS evicted downloads it
# instead of failing with EDEADLK.
plist() {
  cat > "$AGENTS/$1.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array>${HELPER:+<string>$HELPER</string>}$2</array>
  $3
  <key>MaterializeDatalessFiles</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/$1.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/$1.log</string>
</dict></plist>
EOF
  launchctl bootout "gui/$uid/$1" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$AGENTS/$1.plist"
}

if [[ "${1:-}" == "--follower" || "${1:-}" == "--replica" ]]; then
  if [[ ! -f "$IC/feed/current.json" ]]; then
    echo "No feed at $IC/feed yet. On the primary Mac run: git pull && ./install.sh — then rerun this."
    exit 1
  fi

  # Retire an old --replica install, which linked the primary's whole state
  # folder from iCloud. Only links and files that install created are removed.
  launchctl bootout "gui/$uid/com.$USER.wallpaper-mirror" 2>/dev/null || true
  rm -f "$AGENTS/com.$USER.wallpaper-mirror.plist" "$HOME/.wallpaper-replica"
  for link in "$HOME/.wallpaper-rotator" "$HOME/Pictures/WorldWallpapers"; do
    if [[ -L "$link" ]]; then rm "$link"; fi
  done
  for old in mirror.sh apply.sh seed.sh set_wallpaper.py info.sh events.py; do
    f="$HOME/.local/bin/$old"
    if [[ -f "$f" ]] && /usr/bin/grep -q -E 'wallpaper-rotator|awe-some-wallpapers|WallpaperAgent' "$f"; then
      rm -f "$f"
    fi
  done

  F="$HOME/.wallpaper-follower"
  mkdir -p "$F"
  cp "$REPO/follower/follow.py" "$REPO/rotator/apply.sh" "$REPO/rotator/seed.sh" "$REPO/rotator/set_wallpaper.py" "$F/"
  cp "$REPO/follower/wp" "$HOME/.local/bin/wp"
  chmod +x "$HOME/.local/bin/wp" "$F/follow.py" "$F/apply.sh" "$F/seed.sh" "$F/set_wallpaper.py"
  plist "com.$USER.wallpaper-follow" \
    "<string>/usr/bin/python3</string><string>-I</string><string>$F/follow.py</string><string>tick</string>" \
    "<key>WatchPaths</key><array><string>$IC/feed/current.json</string></array><key>StartInterval</key><integer>300</integer>"

  /usr/bin/python3 -I "$F/follow.py" tick
  echo "Follower installed: this Mac shows the primary's wallpapers, and keeps going while the primary sleeps."
  if [[ -f /Users/Shared/awe-some-wallpapers/wallpaper.jpg ]]; then
    echo "Pointing macOS at the wallpaper file (approve the System Events prompt if one appears):"
    bash "$F/seed.sh"
  else
    echo "Once the first wallpaper has synced, run: wp seed"
  fi
  exit 0
fi

BASE="$HOME/.wallpaper-rotator"
mkdir -p "$BASE/queue" "$HOME/Pictures/WorldWallpapers/archive"
cp "$REPO/bin/wp" "$HOME/.local/bin/wp"; chmod +x "$HOME/.local/bin/wp"
cp "$REPO"/rotator/*.py "$REPO"/rotator/*.sh "$REPO/rotator/CURATOR.md" "$BASE/"
chmod +x "$BASE"/*.py "$BASE"/*.sh
rm -f "$BASE/publish.sh" "$BASE/mirror.sh" "$BASE/migrate_v1.py" "$BASE/migrate_events.py"   # replaced or one-time
[[ -f "$BASE/config.json" ]] || cp "$REPO/config.example.json" "$BASE/config.json"
[[ -f "$BASE/taste.md" ]]    || cp "$REPO/rotator/taste.seed.md" "$BASE/taste.md"

# Rotation at fixed times, 00:30 and every three hours after: half an hour
# after each intake, so fresh promotions are ready, and predictable enough for
# the iPad's shortcut to run ten minutes later.
rotate_times=""
for h in 0 3 6 9 12 15 18 21; do
  rotate_times+="<dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>30</integer></dict>"
done
plist "com.$USER.wallpaper-rotate" \
  "<string>/bin/bash</string><string>$BASE/rotate.sh</string>" \
  "<key>StartCalendarInterval</key><array>$rotate_times</array>"
plist "com.$USER.wallpaper-fetch" \
  "<string>/usr/bin/python3</string><string>$BASE/fetch.py</string>" \
  "<key>StartCalendarInterval</key><array><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict><dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict></array>"
/usr/bin/python3 -I "$BASE/publish.py" || echo "feed publish failed; it retries after the next rotation"

echo "Installed."
echo "1. Put your Unsplash key and contact email in $BASE/config.json"
echo "2. wp auth           (year-long curator token; headless curation never needs a login)"
echo "3. wp fetch          (first intake + curation)"
echo "4. wp seed           (one-time macOS grant; desktop + lock screen)"
echo "Other Macs: ./install.sh --follower"
