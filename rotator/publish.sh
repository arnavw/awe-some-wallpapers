#!/bin/bash
# publish.sh — sync with the iCloud share used by replica Macs and the iPad.
# Local disk is the source of truth; iCloud is only a transport.
#   out: state (no --delete: replicas keep their own wp_log.<host>.jsonl),
#        live pool + captions (mirrored exactly), archive (append-only).
#   in:  replicas' reaction logs, so the primary's learner sees every machine.
# Runs after every rotation and curation; safe when iCloud is absent.
IC="$HOME/Library/Mobile Documents/com~apple~CloudDocs/AweSomeWallpapers"
[[ -d "$IC" ]] || exit 0
BASE="$HOME/.wallpaper-rotator"
IMAGES="$HOME/Pictures/WorldWallpapers"
host=$(hostname -s)

rsync -a --exclude 'queue/' --exclude 'logs/' "$BASE/" "$IC/state/" 2>/dev/null
rsync -a --delete --exclude 'archive/' --exclude 'current/' "$IMAGES/" "$IC/images/" 2>/dev/null
rsync -a "$IMAGES/archive/" "$IC/images/archive/" 2>/dev/null
# pull replica event streams (never our own file)
for f in "$IC"/state/events.*.jsonl; do
  [[ -f "$f" && "$(basename "$f")" != "events.$host.jsonl" ]] && cp -f "$f" "$BASE/" 2>/dev/null
done
exit 0
