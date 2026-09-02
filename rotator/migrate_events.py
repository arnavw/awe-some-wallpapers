#!/usr/bin/python3
"""One-time: fold the v1/v2 separate logs into the unified event store.

shown.jsonl → shown · wp_log*.jsonl → reaction · curation_log.jsonl →
promote/reject · queries.jsonl → query. Source files are renamed *.v1 (never
deleted). Idempotent: skips if events.jsonl already exists.
"""

import glob
import json
import os
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
HOST = os.uname().nodename.split(".")[0]


def rows(path):
    try:
        return [json.loads(l) for l in open(path) if l.strip()]
    except OSError:
        return []


def main() -> None:
    out = BASE / "events.jsonl"
    if out.exists():
        print("events.jsonl exists; nothing to do")
        return
    events = []
    for r in rows(BASE / "shown.jsonl"):
        events.append({"ts": r["ts"], "host": HOST, "type": "shown", "image": r["image"]})
    for f in glob.glob(str(BASE / "wp_log*.jsonl")):
        host = Path(f).name.replace("wp_log.", "").replace(".jsonl", "") or HOST
        for r in rows(f):
            e = {"ts": r["ts"], "host": host, "type": "reaction", "cmd": r["cmd"],
                 "image": r.get("image"), "dwell_s": r.get("dwell_s")}
            if r.get("corrected"):
                e["note"] = r["corrected"]
            events.append(e)
    for r in rows(BASE / "curation_log.jsonl"):
        e = {"ts": r["ts"], "host": HOST, "type": r["action"], "image": r["image"]}
        for k in ("caption", "register", "purpose", "reason", "title", "wildcard"):
            if k in r:
                e[k] = r[k]
        events.append(e)
    for r in rows(BASE / "queries.jsonl"):
        events.append({"ts": r["ts"], "host": HOST, "type": "query", **{k: r[k] for k in ("query", "register", "source", "purpose", "yield") if k in r}})
    events.sort(key=lambda e: e.get("ts", 0))
    with open(out, "w") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    for name in ["shown.jsonl", "curation_log.jsonl", "queries.jsonl"] + [Path(p).name for p in glob.glob(str(BASE / "wp_log*.jsonl"))]:
        p = BASE / name
        if p.exists():
            p.rename(BASE / f"{name}.v1")
    print(f"events.jsonl written with {len(events)} events; old logs renamed *.v1")


if __name__ == "__main__":
    main()
