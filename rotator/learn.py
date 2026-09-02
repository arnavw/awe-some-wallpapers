#!/usr/bin/python3
"""Deterministic learner: rebuild bandit.json from the reaction record.

Each register is a Beta-distributed arm. Evidence per shown image:
  love         +1.0 alpha
  interesting  +0.5 alpha (curiosity, not awe)
  long dwell   +0.25 alpha (>= 2 visible hours without a negative)
  meh / ban    +1.0 beta
  fast skip    +1.0 beta (skipped within 15 minutes of appearing)
Pulls = number of showings. Runs before every curation pass so the curator
plans from arithmetic, not from its own narrative. Also prints a coverage
summary the curator uses to pick surprise cells.
"""

import glob
import json
import sys
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
FAST_SKIP_S = 15 * 60
LONG_DWELL_S = 2 * 3600


def load_jsonl(path):
    try:
        return [json.loads(l) for l in open(path) if l.strip()]
    except OSError:
        return []


def main() -> None:
    meta = json.loads((BASE / "meta.json").read_text())
    shown = load_jsonl(BASE / "shown.jsonl")
    reactions = []
    for f in glob.glob(str(BASE / "wp_log*.jsonl")):
        reactions += load_jsonl(f)

    from fetch import REGISTERS  # arms live with their seed phrases
    arms = {r: {"alpha": 1.0, "beta": 1.0, "pulls": 0, "loves": 0, "negatives": 0} for r in REGISTERS}

    def register_of(image):
        return meta.get(image, {}).get("register")

    for s in shown:
        r = register_of(s.get("image"))
        if r in arms:
            arms[r]["pulls"] += 1

    reacted = set()
    for e in reactions:
        img, cmd = e.get("image"), e.get("cmd")
        r = register_of(img)
        if r not in arms:
            continue
        dwell = e.get("dwell_s") or 0
        if cmd == "love":
            arms[r]["alpha"] += 1.0; arms[r]["loves"] += 1; reacted.add(img)
        elif cmd == "interesting":
            arms[r]["alpha"] += 0.5; reacted.add(img)
        elif cmd in ("meh", "ban"):
            arms[r]["beta"] += 1.0; arms[r]["negatives"] += 1; reacted.add(img)
        elif cmd in ("skip", "next", "n") and dwell < FAST_SKIP_S:
            arms[r]["beta"] += 1.0; arms[r]["negatives"] += 1; reacted.add(img)
        elif cmd in ("skip", "next", "n") and dwell >= LONG_DWELL_S:
            arms[r]["alpha"] += 0.25

    (BASE / "bandit.json").write_text(json.dumps(arms, indent=1))

    if "--quiet" not in sys.argv:
        print("register         pulls  loves  neg   mean")
        for r, a in sorted(arms.items(), key=lambda kv: -kv[1]["alpha"] / (kv[1]["alpha"] + kv[1]["beta"])):
            print(f"{r:16s} {a['pulls']:5d} {a['loves']:6d} {a['negatives']:4d}   {a['alpha']/(a['alpha']+a['beta']):.2f}")
        never = [r for r, a in arms.items() if a["pulls"] == 0]
        print("never shown:", ", ".join(never) if never else "none")


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    main()
