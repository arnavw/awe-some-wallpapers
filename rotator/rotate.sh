#!/bin/bash
# rotate.sh — advance the wallpaper show by one image.
# Selection: next_image.py — the curator's playlist order, never anything any
#            Mac has shown. Follower Macs' events are pulled in first, so an
#            image a follower already showed is skipped here too.
# Apply:     apply.sh (stable-path swap; Tahoe rationale documented there).
# State:     current.txt, a `shown` event, retirement of every spent image
#            (keeper archive, or deletion when banned), then the iCloud feed.
set -euo pipefail
BASE="$HOME/.wallpaper-rotator"
IMAGES="$HOME/Pictures/WorldWallpapers"
STATE="$BASE/current.txt"

/usr/bin/python3 -I "$BASE/publish.py" pull ||
  echo "$(date '+%F %T') could not pull follower events; choosing from this Mac's history"

current=""
[[ -f "$STATE" ]] && current=$(cat "$STATE")

on_screen="$current"
next=$(/usr/bin/python3 -I "$BASE/next_image.py" "$current" || true)
if [[ -z "$next" ]]; then
  echo "$(date '+%F %T') nothing fresh; holding current wallpaper"
else
  target="$next"
  display="$IMAGES/.display/$(basename "$next")"
  [[ -f "$display" ]] && target="$display"
  if ! bash "$BASE/apply.sh" "$target"; then
    echo "$(date '+%F %T') apply failed; will retry next interval"
    exit 0
  fi
  echo "$next" > "$STATE"
  /usr/bin/python3 -I "$BASE/events.py" append shown "image=$(basename "$next")" >/dev/null
  on_screen="$next"
  echo "$(date '+%F %T') set wallpaper: $(basename "$next")"
fi

# Never-repeat: everything any Mac has shown leaves the pool, except what is on
# screen here. Shown images go to the keeper archive; banned ones are deleted.
# Runs even when holding, since follower Macs keep showing and banning.
mkdir -p "$IMAGES/archive"
/usr/bin/python3 -I "$BASE/next_image.py" --retire "$on_screen" | while read -r action name; do
  case "$action" in
    archive) mv -f "$IMAGES/$name" "$IMAGES/archive/" ;;
    delete)  rm -f "$IMAGES/$name" ;;
  esac
  rm -f "$IMAGES/.display/$name" "$IMAGES/.ipad/$name"
done || echo "$(date '+%F %T') retiring spent images failed; next_image.py still refuses them"
/usr/bin/python3 -I "$BASE/publish.py" push || echo "$(date '+%F %T') feed publish failed; followers catch up on the next one"
