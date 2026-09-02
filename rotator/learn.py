#!/usr/bin/python3
"""Deterministic learner: rebuild bandit.json from the event store.

Each register is a Beta-distributed arm. Evidence per shown image:
  love         +1.0 alpha
  interesting  +0.5 alpha (curiosity, not awe)
  long dwell   +0.25 alpha (skipped only after >= 2 hours on screen)
  meh / ban    +1.0 beta
  fast skip    +1.0 beta (skipped within 15 minutes of appearing)
Pulls = number of showings. Runs before every curation pass so the curator
plans from arithmetic, not from its own narrative.
"""

import json
import sys
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
sys.path.insert(0, str(BASE))
FAST_SKIP_S = 15 * 60
LONG_DWELL_S = 2 * 3600


def main() -> None:
    from events import load
    from fetch import REGISTERS
    meta = json.loads((BASE / "meta.json").read_text())
    arms = {r: {"alpha": 1.0, "beta": 1.0, "pulls": 0, "loves": 0, "negatives": 0} for r in REGISTERS}

    def arm(image):
        return arms.get(meta.get(image, {}).get("register"))

    for e in load():
        a = arm(e.get("image"))
        if a is None:
            continue
        t = e.get("type")
        if t == "shown":
            a["pulls"] += 1
        elif t == "reaction":
            cmd, dwell = e.get("cmd"), e.get("dwell_s") or 0
            if cmd == "love":
                a["alpha"] += 1.0; a["loves"] += 1
            elif cmd == "interesting":
                a["alpha"] += 0.5
            elif cmd in ("meh", "ban"):
                a["beta"] += 1.0; a["negatives"] += 1
            elif cmd in ("skip", "next", "n"):
                if dwell < FAST_SKIP_S:
                    a["beta"] += 1.0; a["negatives"] += 1
                elif dwell >= LONG_DWELL_S:
                    a["alpha"] += 0.25

    (BASE / "bandit.json").write_text(json.dumps(arms, indent=1))
    if "--quiet" not in sys.argv:
        print("register         pulls  loves  neg   mean")
        for r, a in sorted(arms.items(), key=lambda kv: -kv[1]["alpha"] / (kv[1]["alpha"] + kv[1]["beta"])):
            print(f"{r:16s} {a['pulls']:5d} {a['loves']:6d} {a['negatives']:4d}   {a['alpha']/(a['alpha']+a['beta']):.2f}")
        never = [r for r, a in arms.items() if a["pulls"] == 0]
        print("never shown:", ", ".join(never) if never else "none")


if __name__ == "__main__":
    main()
