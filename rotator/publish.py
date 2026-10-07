#!/usr/bin/python3
"""The iCloud Drive feed that follower Macs and the iPad read.

Local disk is the source of truth and iCloud is only transport. This Mac is
the only writer, except that each follower Mac writes its own event stream
and the iPad appends to its two text files:

  AweSomeWallpapers/images/          the live pool and its captioned copies
                                     (.display/), mirrored exactly; archive/
                                     only grows (the keeper collection)
  AweSomeWallpapers/feed/
    current.json                     {"image", "set_at"}: what this Mac shows
    playlist.txt                     the curator's order
    pool.json                        captions per pool image: title, credit, url, source
    shown.txt                        every image any Mac has shown
    events.<host>.jsonl              a follower Mac's shown + reaction events
    ipad/<name>.jpg                  the next square image for the iPad; at most one.
                                     Its shortcut sets it, logs it, moves it to ipad-done/
    ipad-log.txt                     iPad, appended: "<date> applied <name>"
    reactions.ipad.txt               iPad, appended: "<date> love" (or interesting, meh, ban)

  publish.py pull   followers' event streams into ~/.wallpaper-rotator/, and
                    the iPad's text files into events.ipad.jsonl plus ipad.json
                    (its health), attributing each reaction to the image the iPad
                    had most recently applied
  publish.py push   images/, then the feed files (current.json last, so a
                    follower never sees a wallpaper before its image), then the
                    iPad's image when this Mac's wallpaper changed
  publish.py        both, pull first

Stdlib only; a no-op when iCloud Drive is absent. Failures print and exit
non-zero; callers keep going, since a stale feed only delays the others.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
IC = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/AweSomeWallpapers"
FEED = IC / "feed"
IPAD_INBOX = FEED / "ipad"           # one image waiting for the iPad
IPAD_DONE = FEED / "ipad-done"       # where the iPad's shortcut moves it after applying
IPAD_PUBLISHED = BASE / ".ipad-published"
IPAD_REACTIONS = ("love", "interesting", "meh", "ban")
sys.path.insert(0, str(BASE))


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def rsync(*args: str) -> None:
    subprocess.run(["/usr/bin/rsync", "-a", *args], check=True)


# ------------------------------------------------------------------ iPad ----

def parse_date(text: str):
    """Epoch seconds for a date Shortcuts wrote; None if unreadable.

    ISO 8601 is what the setup asks for; Shortcuts' default medium style
    ("Oct 7, 2026 at 9:41 PM", read in this Mac's time zone) is accepted too.
    """
    text = re.sub(r"[  ]", " ", text.strip())
    iso = re.sub(r"Z$", "+00:00", text)
    iso = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", iso)
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        pass
    for fmt in ("%b %d, %Y at %I:%M %p", "%b %d, %Y at %I:%M:%S %p", "%d %b %Y at %H:%M", "%d %b %Y at %H:%M:%S"):
        try:
            return int(datetime.strptime(text, fmt).timestamp())
        except ValueError:
            continue
    return None


def split_line(line: str, words: tuple):
    """(epoch, word, rest) for "<date> <word> [rest]", where word is one of words."""
    for word in words:
        m = re.match(rf"^(.*?)\s+{word}\b\s*(.*)$", line.strip())
        if m:
            ts = parse_date(m.group(1))
            return (ts, word, m.group(2).strip()) if ts is not None else None
    return None


def read_lines(path: Path) -> list:
    return [l for l in path.read_text(errors="replace").splitlines() if l.strip()] if path.exists() else []


def pull_ipad() -> None:
    """The iPad's log and reactions into events.ipad.jsonl, and its health into ipad.json."""
    applied, rejected = [], []
    for line in read_lines(FEED / "ipad-log.txt"):
        got = split_line(line, ("applied",))
        if got and got[2]:
            applied.append((got[0], Path(got[2]).stem + ".jpg"))
        else:
            rejected.append(f"ipad-log.txt: {line}")
    applied.sort()

    events_path = BASE / "events.ipad.jsonl"
    events = [json.loads(l) for l in read_lines(events_path)]
    known = {(e["ts"], e["cmd"], e["image"]) for e in events}
    for line in read_lines(FEED / "reactions.ipad.txt"):
        got = split_line(line, IPAD_REACTIONS)
        before = [a for a in applied if got and a[0] <= got[0]]
        if not got or not before:
            rejected.append(f"reactions.ipad.txt: {line}")
            continue
        ts, cmd, _ = got
        applied_at, image = before[-1]
        if (ts, cmd, image) not in known:
            known.add((ts, cmd, image))
            events.append({"ts": ts, "host": "ipad", "type": "reaction", "cmd": cmd,
                           "image": image, "dwell_s": ts - applied_at})
    events.sort(key=lambda e: e["ts"])
    write_atomic(events_path, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
    health = {"last_applied": {"ts": applied[-1][0], "image": applied[-1][1]} if applied else None,
              "reactions": len(events), "rejected": rejected[-20:], "checked": int(time.time())}
    write_atomic(BASE / "ipad.json", json.dumps(health, indent=1, ensure_ascii=False))
    for done in IPAD_DONE.glob("*"):
        done.unlink()


def push_ipad(current: str) -> None:
    """Leave current's square copy as the iPad's only waiting image, once per change."""
    if IPAD_PUBLISHED.exists() and IPAD_PUBLISHED.read_text().strip() == current:
        return
    src = IMAGES / ".ipad" / current
    if not src.exists():
        print(f"no iPad copy of {current} yet (compose.py makes them); the iPad keeps its image", file=sys.stderr)
        return
    for d in (IPAD_INBOX, IPAD_DONE):
        d.mkdir(parents=True, exist_ok=True)
    for old in IPAD_INBOX.glob("*"):
        old.unlink()
    tmp = IPAD_INBOX / f".{current}.tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, IPAD_INBOX / current)
    IPAD_PUBLISHED.write_text(current)


# ------------------------------------------------------------------ feed ----

def pull() -> None:
    """Followers' event streams into BASE (this Mac writes events.jsonl, never these)."""
    for src in FEED.glob("events.*.jsonl"):
        shutil.copyfile(src, BASE / src.name)
    if FEED.is_dir():
        pull_ipad()


def push() -> None:
    from events import load
    FEED.mkdir(parents=True, exist_ok=True)
    rsync("--delete", "--exclude", "archive/", "--exclude", "current/", "--exclude", ".ipad/",
          f"{IMAGES}/", f"{IC}/images/")
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
        name = Path(state.read_text().strip()).name
        current = {"image": name, "set_at": int(state.stat().st_mtime)}
        write_atomic(FEED / "current.json", json.dumps(current))
        push_ipad(name)


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
