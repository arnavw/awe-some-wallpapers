#!/usr/bin/python3
"""The iCloud Drive feed that follower Macs and the iPad read.

Local disk is the source of truth and iCloud is only transport. This Mac is
the only writer, except that each follower Mac writes its own event stream:

  AweSomeWallpapers/images/          the live pool and its captioned copies
                                     (.display/), mirrored exactly; archive/
                                     only grows (the keeper collection)
  AweSomeWallpapers/feed/
    current.json                     {"image", "set_at"}: what this Mac shows
    playlist.txt                     the curator's order
    pool.json                        captions per pool image: title, credit, url, source
    shown.txt                        every image any Mac has shown
    events.<host>.jsonl              a follower's shown + reaction events (its own)

  publish.py pull   copy followers' event streams into ~/.wallpaper-rotator/,
                    where events.load() merges them
  publish.py push   images/, then the feed files (current.json last, so a
                    follower never sees a wallpaper before its image)
  publish.py        both, pull first

Stdlib only; a no-op when iCloud Drive is absent. Failures print and exit
non-zero; callers keep going, since a stale feed only delays followers.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
IC = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/AweSomeWallpapers"
FEED = IC / "feed"
sys.path.insert(0, str(BASE))


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def rsync(*args: str) -> None:
    subprocess.run(["/usr/bin/rsync", "-a", *args], check=True)


def pull() -> None:
    """Followers' event streams into BASE (this Mac writes events.jsonl, never these)."""
    for src in FEED.glob("events.*.jsonl"):
        shutil.copyfile(src, BASE / src.name)


def push() -> None:
    from events import load
    FEED.mkdir(parents=True, exist_ok=True)
    rsync("--delete", "--exclude", "archive/", "--exclude", "current/", f"{IMAGES}/", f"{IC}/images/")
    rsync(f"{IMAGES}/archive/", f"{IC}/images/archive/")

    meta = json.loads((BASE / "meta.json").read_text())
    pool = sorted(p.name for p in IMAGES.iterdir() if p.suffix.lower() in (".jpg", ".png"))
    captions = {n: {k: meta.get(n, {}).get(k, "") for k in ("title", "credit", "url", "source")} for n in pool}
    shown = sorted({e["image"] for e in load() if e.get("type") == "shown" and e.get("image")})
    playlist = BASE / "playlist.txt"
    write_atomic(FEED / "pool.json", json.dumps(captions, indent=1, ensure_ascii=False))
    write_atomic(FEED / "shown.txt", "\n".join(shown) + "\n")
    write_atomic(FEED / "playlist.txt", playlist.read_text() if playlist.exists() else "")

    state = BASE / "current.txt"
    if state.exists():
        current = {"image": Path(state.read_text().strip()).name, "set_at": int(state.stat().st_mtime)}
        write_atomic(FEED / "current.json", json.dumps(current))


def main() -> None:
    if not IC.parent.is_dir():
        return
    IC.mkdir(exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if mode in ("pull", "both"):
        pull()
    if mode in ("push", "both"):
        push()


if __name__ == "__main__":
    main()
