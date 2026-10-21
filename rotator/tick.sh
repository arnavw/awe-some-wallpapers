#!/bin/bash
# tick.sh — launchd, every five minutes: credit the screen clock for what is on
# screen, and rotate once it has been seen for its full turn. Time counts only
# while this Mac is awake, unlocked and in use (screentime.py), so a wallpaper
# put up just before the lid closed is still there when it opens.
set -euo pipefail
BASE="$HOME/.wallpaper-rotator"

current=$(cat "$BASE/current.txt" 2>/dev/null || true)
if [[ -z "$current" ]]; then
  bash "$BASE/rotate.sh"   # nothing shown yet
  exit 0
fi
if [[ "$(/usr/bin/python3 -I "$BASE/screentime.py" tick "$BASE/clock.json" "$current")" == "due" ]]; then
  bash "$BASE/rotate.sh"
fi
