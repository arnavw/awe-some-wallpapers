#!/bin/bash
# apply.sh — put an image on every screen, including the lock screen.
#
# macOS 26 (Tahoe) renders wallpaper through a sandboxed extension that can
# read only files it holds a grant for, and it cannot read TCC-protected
# folders (~/Pictures, ~/Library/Mobile Documents) at all. Every scriptable
# set path fails from launchd (System Events: -609/-1712; NSWorkspace grant
# requests go unconsumed; raw store writes render the default aerial).
#
# So the OS is pointed ONCE at a single stable file that lives outside every
# protected folder — /Users/Shared/awe-some-wallpapers/wallpaper.jpg — by a
# one-time interactive seed (`wp seed`, or picking that file in System
# Settings). That sanctioned selection carries the grant and the lock-screen
# linkage. From then on this script atomically swaps the file's contents and
# restarts WallpaperAgent, which re-reads the granted path. File ops and
# killall are fully launchd-safe; nothing here can be TCC-blocked.
#
# Pre-26 systems delegate to the legacy store-stamp path (set_wallpaper.py).
set -euo pipefail
SRC="$1"
STABLE_DIR="/Users/Shared/awe-some-wallpapers"
STABLE="$STABLE_DIR/wallpaper.jpg"
HERE="$(cd "$(dirname "$0")" && pwd)"

major=$(sw_vers -productVersion | cut -d. -f1)
if [[ "$major" -lt 26 ]]; then
  exec /usr/bin/python3 "$HERE/set_wallpaper.py" "$SRC"
fi

mkdir -p "$STABLE_DIR"
chmod 755 "$STABLE_DIR"
cp -f "$SRC" "$STABLE.tmp"
chmod 644 "$STABLE.tmp"
mv -f "$STABLE.tmp" "$STABLE"
/usr/bin/killall WallpaperAgent 2>/dev/null || true
echo "applied: $(basename "$SRC")"
