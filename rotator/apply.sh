#!/bin/bash
# apply.sh — put an image on every screen, including the lock screen.
#
# macOS 26 (Tahoe): wallpaper is rendered by a sandboxed extension that only
# reads files it holds a grant for, and every scriptable set path fails from
# launchd (System Events: -609/-1712; NSWorkspace: the grant request is never
# consumed; raw store writes: ungranted path -> default aerial). So the OS is
# pointed ONCE — by hand, in System Settings — at a single stable file:
#   ~/Pictures/WorldWallpapers/current/wallpaper.jpg
# That sanctioned selection carries the grant and the lock-screen linkage.
# From then on this script atomically swaps the file's CONTENTS and restarts
# WallpaperAgent, which re-reads the granted path and refreshes its cache.
# File ops + killall are fully launchd-safe; nothing here can be TCC-blocked.
# Pre-26 systems delegate to the legacy store-stamp path (set_wallpaper.py).
set -euo pipefail
SRC="$1"
CUR_DIR="$HOME/Pictures/WorldWallpapers/current"
CUR="$CUR_DIR/wallpaper.jpg"

major=$(sw_vers -productVersion | cut -d. -f1)
if [[ "$major" -lt 26 ]]; then
  exec /usr/bin/python3 "$HOME/.wallpaper-rotator/set_wallpaper.py" "$SRC"
fi

mkdir -p "$CUR_DIR"
cp -f "$SRC" "$CUR.tmp"
mv -f "$CUR.tmp" "$CUR"
/usr/bin/killall WallpaperAgent 2>/dev/null || true

# Return immediately after the swap: the caller's state bookkeeping must not
# sit behind a wait (an interrupted caller once left the screen and the state
# disagreeing about which image was up). The cache-refresh check runs
# detached, purely as a log signal.
(
  CACHE="$HOME/Library/Containers/com.apple.wallpaper.extension.image/Data/Library/Caches"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if [[ -n "$(find "$CACHE" -name '*.jpg' -newer "$CUR" 2>/dev/null | head -1)" ]]; then
      echo "$(date '+%F %T') cache refreshed for $(basename "$SRC")" >> "$HOME/Library/Logs/wallpaper-rotate.log"
      exit 0
    fi
  done
  echo "$(date '+%F %T') cache refresh unconfirmed for $(basename "$SRC")" >> "$HOME/Library/Logs/wallpaper-rotate.log"
) >/dev/null 2>&1 &
disown || true
echo "applied: $(basename "$SRC")"
