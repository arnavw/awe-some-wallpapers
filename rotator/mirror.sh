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
  # iCloud can hand us a dataless placeholder (evicted by Optimize Mac
  # Storage): -f passes but there are no bytes, and WallpaperAgent renders
  # nothing. Materialize first; if it won't download, bail and let the
  # 5-minute backstop retry.
  if [[ "$(stat -f %b "$cand")" -eq 0 ]]; then
    # A blocking read materializes the file synchronously — but ONLY if the
    # launchd job has MaterializeDatalessFiles=true; without it reads fail
    # with EDEADLK and brctl requests from this context can stall forever.
    cat "$cand" > /dev/null 2>&1 || brctl download "$cand" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
      [[ "$(stat -f %b "$cand")" -gt 0 ]] && break
      sleep 5
      cat "$cand" > /dev/null 2>&1 || true
    done
    if [[ "$(stat -f %b "$cand")" -eq 0 ]]; then
      echo "$(date '+%F %T') $name is still an undownloaded placeholder; will retry" >&2
      exit 0
    fi
  fi
  # The wallpaper extension is sandboxed out of ~/Library/Mobile Documents
  # AND TCC-protected dirs like ~/Pictures (reads surface as NSCocoaError
  # 4865 and the desktop silently falls back to the default), so stage the
  # image in /Users/Shared, which it can always read. Local staging also
  # survives iCloud re-evicting the synced copy later.
  CACHE="/Users/Shared/wallpaper-mirror"
  mkdir -p "$CACHE"
  cp -f "$cand" "$CACHE/$name"
  chmod 644 "$CACHE/$name"
  find "$CACHE" -type f ! -name "$name" -delete
  # macOS 26 "Tahoe": the sandboxed image extension only renders files it has
  # ingested itself (NSWorkspace/System Settings create its ChoiceRequest
  # record + scoped bookmark); acquires for store entries with no record fail
  # with NSCocoaError 4865 and the desktop silently falls back to the default.
  # Ingest via NSWorkspace first (registers the file, sets the active Space),
  # then apply.sh propagates the choice to every Space and display.
  if [[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ]]; then
    # Tahoe: the NSWorkspace ingest is the ONLY reliable setter. Direct store
    # editing + killall (apply.sh) makes the freshly respawned agent
    # fail every image acquire (NSCocoaError 4865) and revert to the default
    # aerial — it must never run here.
    /usr/bin/osascript -l JavaScript -e '
      ObjC.import("AppKit");
      const path = "'"$CACHE/$name"'";
      const url = $.NSURL.fileURLWithPath(path);
      const ws = $.NSWorkspace.sharedWorkspace;
      const screens = $.NSScreen.screens;
      for (let i = 0; i < screens.count; i++) {
        ws.setDesktopImageURLForScreenOptionsError(url, screens.objectAtIndex(i), $.NSDictionary.dictionary, null);
      }' || { echo "$(date '+%F %T') NSWorkspace ingest failed" >&2; exit 0; }
  else
    bash "$BASE/apply.sh" "$CACHE/$name"
  fi
  echo "$cand" > "$LAST"
  echo "$(date '+%F %T') mirrored: $name"
  exit 0
done
echo "$(date '+%F %T') $name not yet synced from iCloud; will retry" >&2
