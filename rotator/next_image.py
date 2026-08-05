#!/usr/bin/python3
"""Pick the next wallpaper. Prints an absolute path (empty if nothing exists).

The pool holds only never-shown images (rotate.sh retires each outgoing
wallpaper to archive/), so any pool pick is fresh by construction.

Selection tiers:
  1. First playlist entry that exists in the pool and isn't current.
  2. Random pool image that isn't current.
  3. Pool empty: replay a random archived image not shown in the last
     NO_REPEAT_H hours (stopgap until fresh intake catches up).

Consumes the playlist prefix up to the chosen entry. --dry skips the
playlist write (for testing).

Usage: next_image.py [current-path] [--dry]
"""

import json
import os
import random
import sys
import time

BASE = os.path.expanduser("~/.wallpaper-rotator")
IMAGES = os.path.expanduser("~/Pictures/WorldWallpapers")
NO_REPEAT_H = 36

args = [a for a in sys.argv[1:] if a != "--dry"]
dry = "--dry" in sys.argv
current = os.path.basename(args[0]) if args else ""

cutoff = time.time() - NO_REPEAT_H * 3600
recent = set()
try:
    with open(os.path.join(BASE, "shown.jsonl")) as f:
        for line in f:
            e = json.loads(line)
            if e.get("ts", 0) >= cutoff:
                recent.add(e.get("image"))
except OSError:
    pass

ARCHIVE = os.path.join(IMAGES, "archive")
pool = [f for f in os.listdir(IMAGES) if f.lower().endswith((".jpg", ".png"))]
pl_path = os.path.join(BASE, "playlist.txt")
try:
    lines = [l.strip() for l in open(pl_path) if l.strip()]
except OSError:
    lines = []

pick, consumed = "", 0
for i, cand in enumerate(lines):
    if cand != current and os.path.isfile(os.path.join(IMAGES, cand)):
        pick, consumed = cand, i + 1
        break

if pick and not dry:
    with open(pl_path, "w") as f:
        rest = lines[consumed:]
        f.write("\n".join(rest) + ("\n" if rest else ""))

if not pick:
    fresh = [f for f in pool if f != current]
    if fresh:
        pick = random.choice(fresh)

if pick:
    print(os.path.join(IMAGES, pick))
else:
    # Pool is dry: replay from the keeper archive until new intake arrives.
    try:
        archived = [f for f in os.listdir(ARCHIVE) if f.lower().endswith((".jpg", ".png"))]
    except OSError:
        archived = []
    for tier in (
        [f for f in archived if f != current and f not in recent],
        [f for f in archived if f != current],
        archived,
    ):
        if tier:
            print(os.path.join(ARCHIVE, random.choice(tier)))
            break
