#!/usr/bin/python3
"""Curation helper: reject an image with a stated reason.

Usage: reject.py <filename> "<one-line reason>"
Works on images in the queue or the live pool. Deletes the image and its
caption copy, drops its metadata, and appends the decision (with the image's
title, for future taste analysis) to curation_log.jsonl. seen.txt keeps its
source key, so a rejected photo can never be re-downloaded.
"""

import json
import sys
import time
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
QUEUE = BASE / "queue"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
LOG = BASE / "curation_log.jsonl"

name = Path(sys.argv[1]).name
reason = sys.argv[2] if len(sys.argv) > 2 else ""

found = False
for loc in (QUEUE / name, IMAGES / name):
    if loc.is_file():
        loc.unlink()
        found = True
(IMAGES / ".display" / name).unlink(missing_ok=True)
if not found:
    print(f"skip (not found): {name}", file=sys.stderr)
    sys.exit(1)

meta_file = BASE / "meta.json"
meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
entry = meta.pop(name, {})
meta_file.write_text(json.dumps(meta, indent=1, ensure_ascii=False))

with open(LOG, "a") as f:
    f.write(json.dumps({
        "ts": int(time.time()), "action": "reject", "image": name,
        "title": entry.get("title", ""), "reason": reason,
    }, ensure_ascii=False) + "\n")
print(f"rejected {name}: {reason}")
