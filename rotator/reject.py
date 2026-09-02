#!/usr/bin/python3
"""Curation helper: reject an image with a stated reason.

Usage: reject.py <filename> "<one-line, taste-specific reason>"
Works on images in the queue or the live pool. Deletes the image and its
caption copy, drops its metadata, and records a `reject` event (with the
image's title, for later taste analysis). seen.txt keeps its source key, so a
rejected photo can never be re-downloaded.
"""

import json
import sys
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
QUEUE = BASE / "queue"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
sys.path.insert(0, str(BASE))
from events import append  # noqa: E402

name = Path(sys.argv[1]).name
reason = sys.argv[2] if len(sys.argv) > 2 else ""

found = False
for loc in (QUEUE / name, IMAGES / name):
    if loc.is_file():
        loc.unlink()
        found = True
(IMAGES / ".display" / name).unlink(missing_ok=True)
if not found:
    raise SystemExit(f"not found: {name}")

meta_file = BASE / "meta.json"
meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
entry = meta.pop(name, {})
meta_file.write_text(json.dumps(meta, indent=1, ensure_ascii=False))

append("reject", image=name, title=entry.get("title", ""), register=entry.get("register"),
       purpose=entry.get("purpose"), reason=reason)
print(f"rejected {name}: {reason}")
