#!/usr/bin/python3
"""Curation helper: promote a queued image into the live wallpaper pool.

Usage:
  promote.py <filename> --title "…" --credit "…" [--register R] [--treatment mat|fill] [--purpose exploit|surprise|orthogonal]

The filename is a basename inside ~/.wallpaper-rotator/queue/. --title and
--credit set the caption shown on screen (author it like a gallery label).
--register overrides the arm the fetcher tagged; --purpose marks a promotion
as exploration so its outcome is tracked. Appends to curation_log.jsonl.
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
QUEUE = BASE / "queue"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"

parser = argparse.ArgumentParser()
parser.add_argument("name")
parser.add_argument("--title")
parser.add_argument("--credit")
parser.add_argument("--register")
parser.add_argument("--treatment", choices=["mat", "fill"])
parser.add_argument("--purpose", choices=["exploit", "surprise", "orthogonal"])
args = parser.parse_args()

src = QUEUE / Path(args.name).name
if not src.is_file():
    raise SystemExit(f"not in queue: {args.name}")

meta_file = BASE / "meta.json"
meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
entry = meta.setdefault(src.name, {})
for k in ("title", "credit", "register", "treatment", "purpose"):
    v = getattr(args, k)
    if v:
        entry[k] = v
meta_file.write_text(json.dumps(meta, indent=1, ensure_ascii=False))

IMAGES.mkdir(parents=True, exist_ok=True)
src.rename(IMAGES / src.name)
sys.path.insert(0, str(BASE))
from events import append  # noqa: E402
append("promote", image=src.name, caption=entry.get("title", ""),
       register=entry.get("register"), purpose=entry.get("purpose", "exploit"))
print(f"promoted {src.name} [{entry.get('register')}/{entry.get('purpose', 'exploit')}]")
