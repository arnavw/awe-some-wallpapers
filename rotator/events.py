#!/usr/bin/python3
"""The event store: one append-only, typed record of everything that happens.

Every machine appends to its own file — events.jsonl on the primary,
events.<host>.jsonl on each follower Mac, pulled in by publish.py — and
readers merge all of them, so cross-machine sync is plain file copy. Nothing
is ever edited: a mistake is fixed by appending a `correction` event that
names the event it supersedes.
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


def append(type_: str, **data) -> dict:
    e = {"ts": int(time.time()), "host": HOST, "type": type_, **data}
    with open(BASE / "events.jsonl", "a") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


# Lines load() could not use on its last call, as "file: line"; wp status
# reports them. Every machine's stream is read, so one device's bad line must
# not stop the others' rotation, selection and learning.
malformed: list = []


def load() -> list:
    """All events from every machine, corrections applied, ordered by time.

    Lines that are not JSON objects with an integer ts are skipped and listed
    in `malformed`.
    """
    events = []
    malformed.clear()
    for path in glob.glob(str(BASE / "events*.jsonl")):
        with open(path, errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    e = None
                if isinstance(e, dict) and isinstance(e.get("ts"), int) and not isinstance(e["ts"], bool):
                    events.append(e)
                else:
                    malformed.append(f"{Path(path).name}: {line[:120]}")
    events.sort(key=lambda e: e["ts"])
    fixes = {}
    for c in (e for e in events if e.get("type") == "correction"):
        if isinstance(c.get("ref_ts"), int) and isinstance(c.get("field"), str) and "value" in c:
            fixes[c["ref_ts"]] = c
        else:
            malformed.append(f"correction: {json.dumps(c)[:120]}")
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
