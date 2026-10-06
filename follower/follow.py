#!/usr/bin/python3
"""Follower Mac: show the primary Mac's wallpaper program on this screen.

The primary Mac (fetch → curate → rotate) publishes a feed to iCloud Drive;
rotator/publish.py documents its layout. This Mac only reads it. The one
shared file it writes is its own event stream, which the primary merges, so
the curator learns from reactions on every screen and nothing ever repeats
across Macs.

Each tick (launchd: whenever the feed changes, and every five minutes):
  1. The primary put up a new wallpaper → show the same one here.
  2. The primary has been quiet for longer than one rotation interval
     (asleep, lid closed) → keep the show moving here with the next playlist
     image no Mac has shown yet.

  follow.py tick            the above
  follow.py advance         the next fresh image, now (wp skip / ban)
  follow.py react CMD       log a reaction: love, interesting, meh, skip, ban
  follow.py undo LABEL      relabel the last love / interesting / meh
  follow.py info [open]     caption and source of what this Mac shows
  follow.py status          what this Mac shows, and how fresh the feed is

Local state lives in ~/.wallpaper-follower/ (state.json, events.<host>.jsonl).
Images go on screen through apply.sh, the same stable-path mechanism as the
primary; seed it once with `wp seed`. Stdlib only, for the stock python3.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

F = Path.home() / ".wallpaper-follower"
IC = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/AweSomeWallpapers"
FEED = IC / "feed"
IMAGES = IC / "images"
HOST = os.uname().nodename.split(".")[0]
EVENTS = F / f"events.{HOST}.jsonl"
STATE = F / "state.json"
ROTATE_S = 3 * 3600   # the primary's rotation interval (install.sh)
GRACE_S = 20 * 60     # a primary waking from sleep gets the first move
LABELS = {"inter": "interesting", "next": "skip", "n": "skip"}


def log(msg: str) -> None:
    print(time.strftime("%F %T"), msg, flush=True)


def ago(ts: float) -> str:
    s = max(0, int(time.time() - ts))
    return f"{s // 60}m ago" if s < 3600 else f"{s // 3600}h ago" if s < 172800 else f"{s // 86400}d ago"


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def read_words(path: Path) -> list:
    return path.read_text().split() if path.exists() else []


# ------------------------------------------------------------ events ----

def own_events() -> list:
    if not EVENTS.exists():
        return []
    return [json.loads(line) for line in EVENTS.read_text().splitlines() if line.strip()]


def publish_events() -> None:
    """Copy this Mac's event stream into the feed whenever the feed copy lags."""
    if not EVENTS.exists() or not FEED.is_dir():
        return
    dst = FEED / EVENTS.name
    if dst.exists() and dst.stat().st_size == EVENTS.stat().st_size:
        return
    tmp = dst.with_name(f".{dst.name}.tmp")
    shutil.copyfile(EVENTS, tmp)
    os.replace(tmp, dst)


def append(type_: str, **data) -> None:
    event = {"ts": int(time.time()), "host": HOST, "type": type_, **data}
    with open(EVENTS, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    publish_events()


def shown_here() -> set:
    return {e.get("image") for e in own_events() if e.get("type") == "shown"}


# -------------------------------------------------------------- show ----

def image_path(name: str):
    for path in (IMAGES / ".display" / name, IMAGES / name):
        if path.exists():
            return path
    return None


def show(state: dict, name: str, captions: dict, mirrored: bool) -> bool:
    """Put name on screen and record it in state; False if it isn't readable yet."""
    src = image_path(name)
    if src is None:
        log(f"{name} has not synced yet; retrying next tick")
        return False
    try:
        with open(src, "rb") as fh:   # reading materializes an evicted iCloud file
            fh.read(1)
    except OSError as e:
        log(f"{name} is not readable yet ({e}); retrying next tick")
        return False
    if subprocess.run(["/bin/bash", str(F / "apply.sh"), str(src)]).returncode != 0:
        log(f"apply failed for {name}; retrying next tick")
        return False
    caption = captions.get(name, {})
    state.update(current=name, set_at=int(time.time()), **{k: caption.get(k, "") for k in ("title", "credit", "url", "source")})
    if not mirrored:   # a mirrored image was already logged as shown by the primary
        append("shown", image=name)
    log(f"{'mirrored' if mirrored else 'showing'}: {name} {caption.get('title', '')}")
    return True


def fresh(state: dict, current: dict) -> list:
    """Images no Mac has shown, in the curator's order, then the rest of the pool."""
    spent = set(read_words(FEED / "shown.txt")) | shown_here() | {state.get("current"), current.get("image")}
    pool = read_json(FEED / "pool.json", {})
    ordered = read_words(FEED / "playlist.txt") + sorted(pool, key=lambda _: random.random())
    seen, out = set(), []
    for name in ordered:
        if name not in spent and name not in seen and image_path(name):
            seen.add(name)
            out.append(name)
    return out


# ---------------------------------------------------------- commands ----

def tick() -> None:
    publish_events()
    current = read_json(FEED / "current.json", None)
    if not current:
        log(f"no feed at {FEED}; is the primary Mac publishing?")
        return
    captions = read_json(FEED / "pool.json", {})
    state = read_json(STATE, {})
    primary = current["image"]
    if primary != state.get("primary_seen"):
        # The primary moved on. Follow it, unless this screen already showed that image.
        if primary == state.get("current") or primary in shown_here() or show(state, primary, captions, mirrored=True):
            state["primary_seen"] = primary
            write_atomic(STATE, json.dumps(state, indent=1, ensure_ascii=False))
        return
    if time.time() - state.get("set_at", 0) >= ROTATE_S + GRACE_S:
        advance(state, current, captions)


def advance(state=None, current=None, captions=None) -> None:
    state = read_json(STATE, {}) if state is None else state
    current = read_json(FEED / "current.json", {}) if current is None else current
    captions = read_json(FEED / "pool.json", {}) if captions is None else captions
    for name in fresh(state, current or {}):
        if show(state, name, captions, mirrored=False):
            write_atomic(STATE, json.dumps(state, indent=1, ensure_ascii=False))
            return
    log("nothing fresh in the feed; holding the current wallpaper")


def react(cmd: str) -> None:
    state = read_json(STATE, {})
    if not state.get("current"):
        print("nothing shown on this Mac yet")
        return
    dwell = int(time.time() - state.get("set_at", time.time()))
    append("reaction", cmd=LABELS.get(cmd, cmd), image=state["current"], dwell_s=dwell)


def undo(label: str) -> None:
    last = [e for e in own_events() if e.get("type") == "reaction" and e.get("cmd") in ("love", "interesting", "meh")]
    if not last:
        print("no love, interesting or meh to correct on this Mac")
        return
    append("correction", ref_ts=last[-1]["ts"], field="cmd", value=label)
    print(f"corrected: {last[-1]['cmd']} -> {label} on {last[-1].get('image')}")


def info(open_page: bool) -> None:
    state = read_json(STATE, {})
    if not state.get("current"):
        print("nothing shown on this Mac yet")
        return
    print(f"{state.get('title') or state['current']}\n{state.get('credit', '')} — {state.get('source', '')}\n{state.get('url', '')}")
    if open_page and state.get("url"):
        subprocess.run(["/usr/bin/open", state["url"]])


def status() -> None:
    state = read_json(STATE, {})
    current = read_json(FEED / "current.json", None)
    if state.get("current"):
        same = current and current.get("image") == state["current"]
        print(f"showing: {state.get('title') or state['current']}, up {ago(state.get('set_at', 0))}"
              f" ({'same as the primary' if same else 'this Mac moved on'})")
    else:
        print("showing: nothing yet")
    if current:
        print(f"primary: {current['image']}, put up {ago(current.get('set_at', 0))}")
        print(f"fresh:   {len(fresh(state, current))} images no Mac has shown")
    else:
        print(f"primary: no feed at {FEED}")


def main() -> None:
    F.mkdir(parents=True, exist_ok=True)
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else "tick"), sys.argv[2:]
    if cmd == "tick":
        tick()
    elif cmd == "advance":
        advance()
    elif cmd == "react" and args:
        react(args[0])
    elif cmd == "undo":
        undo(args[0] if args else "interesting")
    elif cmd == "info":
        info(args[:1] == ["open"])
    elif cmd == "status":
        status()
    else:
        print(__doc__)
        sys.exit(64)


if __name__ == "__main__":
    main()
