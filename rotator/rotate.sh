#!/bin/bash
# Rotate the desktop wallpaper to a random image from ~/Pictures/WorldWallpapers.
# On macOS Sequoia the lock screen mirrors the desktop wallpaper, so this
# covers both. Run by launchd on the configured interval (com.$USER.wallpaper-rotate).

set -euo pipefail

IMAGES="$HOME/Pictures/WorldWallpapers"
STATE="$HOME/.wallpaper-rotator/current.txt"

current=""
[[ -f "$STATE" ]] && current=$(cat "$STATE")

# Selection (playlist order, 36h no-repeat window, tiered fallbacks) lives in
# next_image.py.
next=$(/usr/bin/python3 "$HOME/.wallpaper-rotator/next_image.py" "$current" || true)

if [[ -z "$next" ]]; then
  echo "no images in $IMAGES — run ~/.wallpaper-rotator/fetch.py" >&2
  exit 1
fi

# Prefer the caption copy (frosted-glass credit panel) when one exists.
target="$next"
display="$IMAGES/.display/$(basename "$next")"
[[ -f "$display" ]] && target="$display"

# Write the image into every Space/display entry of the wallpaper store and
# restart WallpaperAgent. NSWorkspace and System Events only change the active
# Space, so on multi-Space setups the change appeared to "not take".
if ! /usr/bin/python3 "$HOME/.wallpaper-rotator/set_wallpaper.py" "$target"; then
  echo "$(date '+%F %T') store update failed; will retry next interval"
  exit 0
fi

echo "$next" > "$STATE"
# Exposure history — the curator reads this to sequence future playlists.
printf '{"ts": %s, "image": "%s"}\n' "$(date +%s)" "$(basename "$next")" \
  >> "$HOME/.wallpaper-rotator/shown.jsonl"

# Never-repeat: the outgoing wallpaper retires to the keeper archive. The
# original is preserved; only its caption copy is dropped.
if [[ -n "$current" && "$current" != "$next" && -f "$current" && "$current" != *"/archive/"* ]]; then
  mkdir -p "$IMAGES/archive"
  mv "$current" "$IMAGES/archive/"
  rm -f "$IMAGES/.display/$(basename "$current")"
fi
echo "$(date '+%F %T') set wallpaper: $(basename "$next")"
