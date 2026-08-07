#!/usr/bin/python3
"""Curation helper: promote a queued image into the live wallpaper pool.

Usage: promote.py <filename> [--title "Display title"] [--credit "Artist/photographer"]
The filename is a basename inside ~/.wallpaper-rotator/queue/. --title and
--credit set the authored caption in meta.json (the curator writes these
deliberately — evocative but factual; raw geodata and typos never ship).
Appends the promotion to curation_log.jsonl. Caption composition happens
separately (curate.sh runs compose.py after the review pass).
"""

import argparse
import json
import time
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
QUEUE = BASE / "queue"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
LOG = BASE / "curation_log.jsonl"

parser = argparse.ArgumentParser()
parser.add_argument("names", nargs="+")
parser.add_argument("--title")
parser.add_argument("--credit")
parser.add_argument("--treatment", choices=["mat", "fill"],
                    help="art only: mat = museum wall (bounded works), fill = crop full-bleed (unbounded imagery like space)")
parser.add_argument("--wildcard", action="store_true",
                    help="exploration pick outside the learned taste profile; outcome is tracked to widen or prune the profile")
args = parser.parse_args()

meta_file = BASE / "meta.json"
meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}

for name in args.names:
    src = QUEUE / Path(name).name
    if not src.is_file():
        print(f"skip (not in queue): {name}")
        continue
    src.rename(IMAGES / src.name)
    entry = meta.setdefault(src.name, {})
    if args.title:
        entry["title"] = args.title
    if args.credit:
        entry["credit"] = args.credit
    if args.treatment:
        entry["treatment"] = args.treatment
    if args.wildcard:
        entry["exploration"] = True
    with open(LOG, "a") as f:
        f.write(json.dumps({
            "ts": int(time.time()), "action": "promote", "image": src.name,
            "caption": entry.get("title", ""), "wildcard": bool(args.wildcard),
        }, ensure_ascii=False) + "\n")
    print(f"promoted {src.name}")

meta_file.write_text(json.dumps(meta, indent=1, ensure_ascii=False))
