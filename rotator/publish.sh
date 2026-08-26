#!/bin/bash
# Publish local state + images to the iCloud share for replica Macs/iPad.
# One-way, additive for others' files: no --delete on state (each machine
# writes its own wp_log.<host>.jsonl) and the keeper archive only grows.
# Local disk is the source of truth; iCloud eviction can never break the
# primary because nothing here depends on reading iCloud content.

IC="$HOME/Library/Mobile Documents/com~apple~CloudDocs/AweSomeWallpapers"
[[ -d "$IC" ]] || exit 0
rsync -a --exclude 'queue/' "$HOME/.wallpaper-rotator/" "$IC/state/" 2>/dev/null
rsync -a --delete --exclude 'archive/' "$HOME/Pictures/WorldWallpapers/" "$IC/images/" 2>/dev/null
rsync -a "$HOME/Pictures/WorldWallpapers/archive/" "$IC/images/archive/" 2>/dev/null
