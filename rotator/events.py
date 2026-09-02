#!/usr/bin/python3
"""The event store: one append-only, typed record of everything that happens.

Every machine appends to its own file — events.jsonl on the primary,
events.<host>.jsonl on replicas — and readers merge all of them, so
cross-machine sync is plain file copy. Nothing is ever edited: a mistake is
fixed by appending a `correction` event that names the event it supersedes.
Everything else (bandit.json, captions in meta.json) is a projection.

Event shape: {"ts": epoch, "host": short hostname, "type": …, "image": …, …}
Types: shown · reaction (cmd, dwell_s) · promote (caption, register, purpose)
       · reject (reason) · query (query, register, source, purpose, yield)
       · caption (title, credit) · correction (ref_ts, field, value)

CLI: events.py append <type> key=value …   |   events.py tail [n]
"""

import glob
import json
import os
import sys
import time
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
HOST = os.uname().nodename.split(".")[0]


def own_file() -> Path:
    # Replicas are marked by a file OUTSIDE the synced state dir (install.sh
    # --replica creates it), so the marker never travels to other machines.
    replica = (Path.home() / ".wallpaper-replica").exists()
    return BASE / (f"events.{HOST}.jsonl" if replica else "events.jsonl")


def append(type_: str, **data) -> dict:
    e = {"ts": int(time.time()), "host": HOST, "type": type_, **data}
    with open(own_file(), "a") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def load() -> list:
    """All events from every machine, corrections applied, ordered by time."""
    events = []
    for path in glob.glob(str(BASE / "events*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        pass
    events.sort(key=lambda e: e.get("ts", 0))
    fixes = {c["ref_ts"]: c for c in events if c.get("type") == "correction"}
    out = []
    for e in events:
        if e.get("type") == "correction":
            continue
        c = fixes.get(e.get("ts"))
        if c:
            e = {**e, c["field"]: c["value"]}
        out.append(e)
    return out


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "append":
        data = {}
        for kv in sys.argv[3:]:
            k, _, v = kv.partition("=")
            data[k] = int(v) if v.lstrip("-").isdigit() else v
        print(json.dumps(append(sys.argv[2], **data)))
    elif len(sys.argv) >= 2 and sys.argv[1] == "tail":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        for e in load()[-n:]:
            print(json.dumps(e, ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
