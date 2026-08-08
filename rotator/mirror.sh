#!/bin/bash
# Replica mode: mirror the primary Mac's current wallpaper.
#
# State and images are shared via iCloud Drive (AweSomeWallpapers/); the
# primary runs fetch/curation/rotation and owns all writes. This script just
# reads current.txt and sets the same image locally. Installed by
# `install.sh --replica`; launchd triggers it when current.txt syncs, with a
# 5-minute backstop interval.

set -euo pipefail
BASE="$HOME/.wallpaper-rotator"
IMAGES="$HOME/Pictures/WorldWallpapers"
LAST="$HOME/.wallpaper-mirror-last"   # per-machine, deliberately outside the synced folder

name=$(basename "$(cat "$BASE/current.txt")")
for cand in "$IMAGES/.display/$name" "$IMAGES/$name" "$IMAGES/archive/$name"; do
  [[ -f "$cand" ]] || continue
  [[ -f "$LAST" && "$(cat "$LAST")" == "$cand" ]] && exit 0
  /usr/bin/python3 "$BASE/set_wallpaper.py" "$cand"
  echo "$cand" > "$LAST"
  echo "$(date '+%F %T') mirrored: $name"
  exit 0
done
echo "$(date '+%F %T') $name not yet synced from iCloud; will retry" >&2
