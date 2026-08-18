#!/usr/bin/python3
"""Pick the next wallpaper. Prints an absolute path (empty if nothing fresh).

HARD RULE (owner's instruction, 2026-08-18): a shown image is never shown
again. rotate.sh retires each outgoing wallpaper to archive/, and this
selector additionally refuses anything in the shown.jsonl history — no
grandfathered pool entries, no archive replay. If nothing fresh exists, it
prints nothing and the current wallpaper simply stays up until intake
delivers.

Selection:
  1. First playlist entry that exists in the pool, isn't current, and has
     never been shown.
  2. Random never-shown pool image that isn't current.

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

shown_ever = set()
try:
    with open(os.path.join(BASE, "shown.jsonl")) as f:
        for line in f:
            shown_ever.add(json.loads(line).get("image"))
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
    if (
        cand != current
        and cand not in shown_ever
        and os.path.isfile(os.path.join(IMAGES, cand))
    ):
        pick, consumed = cand, i + 1
        break

if pick and not dry:
    with open(pl_path, "w") as f:
        rest = lines[consumed:]
        f.write("\n".join(rest) + ("\n" if rest else ""))

if not pick:
    fresh = [f for f in pool if f != current and f not in shown_ever]
    if fresh:
        pick = random.choice(fresh)

# Nothing fresh: print nothing; the current wallpaper stays up.
if pick:
    print(os.path.join(IMAGES, pick))
