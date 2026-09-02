#!/bin/bash
# mirror.sh — replica mode: follow the primary Mac's current wallpaper.
# State and images arrive via iCloud Drive (AweSomeWallpapers/); the primary
# owns every write. This resolves the primary's current image, materializes
# it if iCloud evicted it, and applies it through the same stable-path
# mechanism as the primary (apply.sh; seed once with `wp seed`).
# launchd runs this when current.txt syncs, plus a 5-minute backstop, with
# MaterializeDatalessFiles=true so reads of evicted files download instead
# of failing with EDEADLK.
set -euo pipefail
BASE="$HOME/.wallpaper-rotator"
IMAGES="$HOME/Pictures/WorldWallpapers"
LAST="$HOME/.wallpaper-mirror-last"   # per-machine, outside the synced folder

name=$(basename "$(cat "$BASE/current.txt")")
for cand in "$IMAGES/.display/$name" "$IMAGES/$name" "$IMAGES/archive/$name"; do
  [[ -f "$cand" ]] || continue
  [[ -f "$LAST" && "$(cat "$LAST")" == "$cand" ]] && exit 0
  if [[ "$(stat -f %b "$cand")" -eq 0 ]]; then
    cat "$cand" > /dev/null 2>&1 || brctl download "$cand" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
      [[ "$(stat -f %b "$cand")" -gt 0 ]] && break
      sleep 5
      cat "$cand" > /dev/null 2>&1 || true
    done
    [[ "$(stat -f %b "$cand")" -eq 0 ]] && { echo "$(date '+%F %T') $name still evicted; will retry" >&2; exit 0; }
  fi
  bash "$BASE/apply.sh" "$cand"
  echo "$cand" > "$LAST"
  echo "$(date '+%F %T') mirrored: $name"
  exit 0
done
echo "$(date '+%F %T') $name not yet synced; will retry" >&2
