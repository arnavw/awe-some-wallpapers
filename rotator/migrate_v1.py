#!/usr/bin/python3
"""One-time migration from the v1 layout (topic list, explore garden,
appended TASTE.md) to v2 (bandit, query ledger, capped taste.md).

Keeps everything that is evidence: meta, seen, shown, reaction logs, the
curation log, the archive. Infers a register for every known image so the
bandit starts from real history, seeds the query ledger from v1's fetch log,
and turns the long TASTE.md into taste_history.md plus a fresh taste.md the
curator will rewrite on its first run.
"""

import json
import re
import shutil
import sys
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
sys.path.insert(0, str(BASE))

RULES = [
    ("night sky", r"aurora|milky way|stars|starry|night sky|moon|nocturne"),
    ("science", r"nebula|galaxy|orion|hubble|webb|nasa|infrared"),
    ("storm/weather", r"storm|thunder|lightning|lenticular|cloud"),
    ("volcanic", r"volcan|lava|crater|erupt"),
    ("ice/polar", r"iceberg|glacier|ice |antarctica|greenland|frost|snow|fog"),
    ("mountain", r"peak|massif|matterhorn|annapurna|lobuche|fitz roy|paine|dolomit|himalaya|alps|half dome|mountain|yosemite"),
    ("desert/ground", r"canyon|dune|desert|salt|uyuni|polygon|terrace|braided|badland"),
    ("water/coast", r"lake|river|coast|sea|island|bay|falls|waterfall|tide|harbor"),
    ("fine art", r"hiroshige|van gogh|monet|hokusai|painting|print|adam|venus|whistler|cabanel"),
    ("ruins/ancient", r"machu|angkor|petra|ruin|pyramid|giza|persepolis|borobudur"),
    ("architecture", r"temple|castle|bridge|mosque|dome|cathedral|pagoda|torii|hall|tower|palace"),
    ("city", r"skyline|hong kong|city|seoul|singapore|tokyo|new york|dubai"),
    ("wildlife", r"lion|bear|bird|elephant|whale|gull"),
    ("flora", r"blossom|cypress|forest|tree|orchard|garden"),
]


def infer(title: str) -> str:
    t = (title or "").lower()
    for reg, pat in RULES:
        if re.search(pat, t):
            return reg
    return "desert/ground" if "aerial" in t else "mountain"


def main() -> None:
    meta_path = BASE / "meta.json"
    meta = json.loads(meta_path.read_text())
    n = 0
    for name, e in meta.items():
        if not e.get("register"):
            e["register"] = "science" if (e.get("kind") == "art" and re.search(r"nebula|nasa|hubble", (e.get("title") or ""), re.I)) \
                else ("fine art" if e.get("kind") == "art" else infer(e.get("title", "")))
            n += 1
        if e.pop("exploration", None):
            e["purpose"] = "surprise"
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print(f"registers inferred for {n} images")

    # query ledger from the v1 fetch log
    ledger = BASE / "queries.jsonl"
    if not ledger.exists():
        log = Path.home() / "Library/Logs/wallpaper-fetch.log"
        seen_q = set()
        with open(ledger, "w") as f:
            if log.exists():
                for q in re.findall(r"fetching: (.+?) \(", log.read_text(errors="ignore")):
                    q = q.replace("art:", "").strip()
                    if q.lower() not in seen_q:
                        seen_q.add(q.lower())
                        f.write(json.dumps({"ts": 0, "query": q, "register": "legacy", "source": "legacy", "purpose": "exploit", "yield": 0}) + "\n")
        print(f"query ledger seeded with {len(seen_q)} legacy queries")

    # taste: long diary -> history + fresh summary. APFS is case-insensitive, so
    # TASTE.md and taste.md are the same file: detect the v1 diary by content.
    old = BASE / "TASTE.md"
    is_v1 = old.exists() and "Seed hypothesis" in old.read_text()
    if is_v1:
        shutil.copy(old, BASE / "taste_history.md")
        old.unlink()
        (BASE / "taste.md").write_text(
            "# Taste — summary\n\n"
            "Rewrite me: the curator keeps this under twelve bullets, citing log timestamps.\n"
            "The full v1 diary is in taste_history.md; bandit.json holds the arithmetic.\n\n"
            "- Moved most reliably by sculpted form meeting rare light: night skies over "
            "monumental rock, alpenglow, storm cells, eruptions (16+ loves).\n"
            "- Also moved by austerity and accommodation without drama: Elephant Island under a "
            "white sky, Uyuni polygons, Greenland icebergs in fog.\n"
            "- Loves art with strong design (Hiroshige, the Creation of Adam detail); the Great "
            "Wave and other over-reproduced icons feel stale on first showing.\n"
            "- Rejects postcard competence: serene lakes, pastel blossoms, flat-daylight monuments, "
            "city panoramas (0 positives), and any subject already seen.\n"
            "- Untested territory as of the v2 rebuild: city, intimate/macro, interiors, people, "
            "illustration, industrial, underwater, wildlife.\n"
        )
        print("taste.md created; v1 diary preserved as taste_history.md")

    for stale in ("explore_topics.txt", "topic_cycle.json", "explore_topics.seed.txt"):
        p = BASE / stale
        if p.exists():
            p.rename(BASE / f"{stale}.v1")
    cfg_path = BASE / "config.json"
    cfg = json.loads(cfg_path.read_text())
    for k in ("topics", "topics_per_fetch", "images_per_topic", "quality_pool", "unsplash_min_likes",
              "explore_min_likes", "fetch_pages", "display_aspects"):
        cfg.pop(k, None)
    cfg.setdefault("images_per_query", 3)
    cfg.setdefault("curator_model", "claude-fable-5")
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    print("config slimmed; v1 topic files renamed *.v1")


if __name__ == "__main__":
    main()
