#!/bin/bash
# seed.sh — one-time, interactive: establish the OS-level grant for the
# stable wallpaper file (macOS 26+). Must run from a user terminal, not
# launchd: it uses System Events, which launchd contexts cannot reach.
# Idempotent; rerun any time macOS forgets (after an upgrade, for example).
set -euo pipefail
STABLE_DIR="/Users/Shared/awe-some-wallpapers"
STABLE="$STABLE_DIR/wallpaper.jpg"
BASE="$HOME/.wallpaper-rotator"
IMAGES="$HOME/Pictures/WorldWallpapers"

mkdir -p "$STABLE_DIR"; chmod 755 "$STABLE_DIR"
if [[ ! -f "$STABLE" ]]; then
  cur=$(cat "$BASE/current.txt" 2>/dev/null || true)
  src=""
  [[ -n "$cur" && -f "$IMAGES/.display/$(basename "$cur")" ]] && src="$IMAGES/.display/$(basename "$cur")"
  [[ -z "$src" && -n "$cur" && -f "$cur" ]] && src="$cur"
  [[ -z "$src" ]] && src=$(ls "$IMAGES"/*.jpg 2>/dev/null | head -1 || true)
  [[ -z "$src" ]] && { echo "no image to seed with — run: wp fetch"; exit 1; }
  cp -f "$src" "$STABLE"; chmod 644 "$STABLE"
fi

/usr/bin/osascript -e "tell application \"System Events\" to set picture of every desktop to POSIX file \"$STABLE\""
echo "seeded: macOS now follows $STABLE (desktop + lock screen)."
echo "If the lock screen does not follow, pick this exact file once in System Settings → Wallpaper."
