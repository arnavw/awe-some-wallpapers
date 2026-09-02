#!/bin/bash
# rotate.sh — advance the wallpaper program by one image.
# Selection: next_image.py (curator playlist order, absolute never-reshow).
# Apply:     apply.sh (stable-path swap; Tahoe rationale documented there).
# State:     current.txt, shown.jsonl exposure log, retirement of the
#            outgoing image to archive/, publish to the iCloud share.
set -euo pipefail
BASE="$HOME/.wallpaper-rotator"
IMAGES="$HOME/Pictures/WorldWallpapers"
STATE="$BASE/current.txt"

current=""
[[ -f "$STATE" ]] && current=$(cat "$STATE")

next=$(/usr/bin/python3 "$BASE/next_image.py" "$current" || true)
if [[ -z "$next" ]]; then
  echo "$(date '+%F %T') nothing fresh; holding current wallpaper"
  exit 0
fi

target="$next"
display="$IMAGES/.display/$(basename "$next")"
[[ -f "$display" ]] && target="$display"

if ! bash "$BASE/apply.sh" "$target"; then
  echo "$(date '+%F %T') apply failed; will retry next interval"
  exit 0
fi

echo "$next" > "$STATE"
/usr/bin/python3 "$BASE/events.py" append shown "image=$(basename "$next")" >/dev/null

# Never-repeat: the outgoing wallpaper retires to the keeper archive.
if [[ -n "$current" && "$current" != "$next" && -f "$current" && "$current" != *"/archive/"* ]]; then
  mkdir -p "$IMAGES/archive"
  mv "$current" "$IMAGES/archive/"
  rm -f "$IMAGES/.display/$(basename "$current")"
fi
echo "$(date '+%F %T') set wallpaper: $(basename "$next")"
bash "$BASE/publish.sh" || true
