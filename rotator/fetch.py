#!/usr/bin/python3
"""Intake engine: turn a query plan into a queue of wallpaper candidates.

Where queries come from, in priority order:
  1. plan.json — six queries the curator wrote at the end of its last run,
     each tagged with a register (bandit arm), a source, and a purpose
     (exploit / surprise / orthogonal). Consumed once, then deleted.
  2. Otherwise a bootstrap plan synthesized from bandit.json: Thompson
     samples pick exploit arms, the least-pulled arms fill surprise slots,
     and each arm's seed phrases (below) become queries.

Every executed query is appended to queries.jsonl and never executed again:
the ledger is the novelty guarantee at the query level.

Sources, chosen per register — all keyless except Unsplash:
  unsplash  photography, relevance-ranked, no like-floor (the curator's eyes
            are the quality gate; ranking by likes only ever found postcards)
  commons   Wikimedia Commons Featured Pictures (photo registers)
  met       The Met open access: public-domain highlights, direct hi-res
  aic       Art Institute of Chicago: public-domain works over IIIF
  nasa      NASA image library: space and science imagery

Stdlib only; runs on the stock macOS python3 from launchd.
"""

import hashlib
import json
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
QUEUE = BASE / "queue"
# No URL in the UA: the Art Institute's image server 403s agents that carry one.
UA = "awe-some-wallpapers/2.0 (personal wallpaper curator; github arnavw/awe-some-wallpapers)"

# Registers are the bandit's arms. Seed phrases are only used for bootstrap
# plans; the curator writes its own queries once it is running.
REGISTERS = {
    "night sky":      ["aurora over mountains", "milky way arch", "moonlit peak", "star trails desert"],
    "storm/weather":  ["supercell storm", "lightning storm plains", "lenticular cloud", "sunset thunderhead"],
    "volcanic":       ["lava lake night", "volcano eruption", "lava meets ocean", "geothermal field steam"],
    "ice/polar":      ["iceberg fog", "glacier crevasse", "antarctica ice shelf", "frozen lake bubbles"],
    "mountain":       ["alpenglow ridge", "himalaya face dawn", "dolomites storm light", "patagonia granite"],
    "desert/ground":  ["salt flat polygons", "sand dune abstract aerial", "slot canyon light", "badlands erosion"],
    "water/coast":    ["sea stacks fog", "bioluminescent tide", "cenote light shaft", "tidal flats aerial"],
    "architecture":   ["mosque dome interior", "gothic cathedral nave", "stepwell geometry", "brutalist concrete light"],
    "ruins/ancient":  ["angkor dawn mist", "petra siq light", "machu picchu clouds", "megalith moonlight"],
    "city":           ["city night rain neon", "skyscraper fog aerial", "old town rooftops dusk", "harbor lights night"],
    "fine art":       ["nocturne painting", "romantic landscape painting", "japanese woodblock print", "luminism painting"],
    "illustration":   ["botanical illustration plate", "celestial atlas plate", "vintage travel poster", "architectural drawing"],
    "science":        ["nebula", "electron microscope crystal", "satellite earth pattern", "solar flare"],
    "wildlife":       ["whale breach", "elephant dust sunset", "owl snow", "flamingo flock aerial"],
    "flora":          ["ancient forest fog", "cherry blossom night", "bristlecone pine", "lavender field storm"],
    "intimate":       ["frost macro", "ice crystal detail", "feather macro", "raindrop leaf"],
    "interior":       ["library hall", "opera house ceiling", "greenhouse light", "cathedral rose window interior"],
    "industrial":     ["steel mill pour", "radio telescope array", "dam spillway", "abandoned power plant"],
    "underwater":     ["kelp forest light", "coral reef wide", "freediver cave", "whale shark silhouette"],
    "human":          ["monk temple morning", "fisherman fog lake", "shepherd mountain storm", "market lantern night"],
}
ART_REGISTERS = {"fine art", "illustration"}

# Fetch-layer junk filter: archival document photography and event coverage
# that free-text search keeps returning.
DOC_WORDS = re.compile(
    r"scan|folio|codex|atlas page|gazetteer|newspaper|manuscript|sheet music|score"
    r"|title page|text page|diagram|annotated|halftone|microfilm|songbook|libretto"
    r"|endpaper|binding|gallica|btv1b|concert|festival|championship|tournament"
    r"|stadium|press conference|ceremony|banquet|specimen|watermark",
    re.I,
)


# ---------------------------------------------------------------- state ----

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))


def ledger_queries() -> set:
    out = set()
    try:
        for line in open(BASE / "queries.jsonl"):
            out.add(json.loads(line)["query"].lower())
    except OSError:
        pass
    return out


def ledger_add(query: str, register: str, source: str, purpose: str, yielded: int) -> None:
    with open(BASE / "queries.jsonl", "a") as f:
        f.write(json.dumps({
            "ts": int(time.time()), "query": query, "register": register,
            "source": source, "purpose": purpose, "yield": yielded,
        }) + "\n")


# ----------------------------------------------------------------- plan ----

def source_for(register: str) -> str:
    if register in ART_REGISTERS:
        return random.choice(["met", "aic"])
    if register == "science":
        return random.choice(["nasa", "commons"])
    return random.choice(["unsplash", "unsplash", "commons"])


def bootstrap_plan(cfg: dict) -> list:
    """Six queries from the bandit: four exploit arms by Thompson sampling,
    two surprise arms = least pulled. Seed phrases not yet in the ledger."""
    bandit = load_json(BASE / "bandit.json", {})
    used = ledger_queries()
    draws = {r: random.betavariate(bandit.get(r, {}).get("alpha", 1), bandit.get(r, {}).get("beta", 1))
             for r in REGISTERS}
    exploit = sorted(draws, key=draws.get, reverse=True)[:4]
    by_pulls = sorted(REGISTERS, key=lambda r: bandit.get(r, {}).get("pulls", 0))
    surprise = [r for r in by_pulls if r not in exploit][:2]
    plan = []
    for r, purpose in [(r, "exploit") for r in exploit] + [(r, "surprise") for r in surprise]:
        fresh = [q for q in REGISTERS[r] if q.lower() not in used]
        q = random.choice(fresh) if fresh else random.choice(REGISTERS[r]) + " " + random.choice(["dawn", "dusk", "winter", "aerial"])
        plan.append({"query": q, "register": r, "source": source_for(r), "purpose": purpose})
    return plan


def load_plan(cfg: dict) -> list:
    plan_file = BASE / "plan.json"
    plan = load_json(plan_file, None)
    if plan:
        plan_file.unlink(missing_ok=True)
        used = ledger_queries()
        plan = [p for p in plan if p.get("query", "").lower() not in used and p.get("register") in REGISTERS][:8]
        for p in plan:
            p.setdefault("source", source_for(p["register"]))
            p.setdefault("purpose", "exploit")
        if plan:
            return plan
    return bootstrap_plan(cfg)


# -------------------------------------------------------------- sources ----

def http_json(url: str, headers=None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def download(url: str, dest: Path, headers=None) -> None:
    delay = 5
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
            return
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503) or attempt == 3:
                raise
            time.sleep(delay)
            delay *= 3


def image_size(path: Path) -> tuple:
    out = subprocess.run(["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                         capture_output=True, text=True).stdout
    w = re.search(r"pixelWidth: (\d+)", out)
    h = re.search(r"pixelHeight: (\d+)", out)
    return (int(w.group(1)), int(h.group(1))) if w and h else (0, 0)


def cand(key, url, title, credit, source, page, kind="photo", headers=None) -> dict:
    return {"key": key, "url": url, "title": title or "", "credit": credit,
            "source": source, "page": page, "kind": kind, "headers": headers}


def src_unsplash(q: str, cfg: dict) -> list:
    key = cfg.get("unsplash_access_key")
    if not key:
        return []
    auth = {"Authorization": f"Client-ID {key}"}
    page = random.randint(1, 3)
    params = urllib.parse.urlencode({"query": q, "orientation": "landscape", "per_page": 30,
                                     "page": page, "content_filter": "high"})
    data = http_json(f"https://api.unsplash.com/search/photos?{params}", auth)
    out = []
    for p in data.get("results", []):
        if p.get("width", 0) < cfg.get("min_width", 3840):
            continue
        title = p.get("description") or p.get("alt_description") or q
        out.append(cand(f"unsplash:{p['id']}",
                        p["urls"]["raw"] + f"&w={cfg.get('download_width', 5120)}&q=90&fm=jpg",
                        title[:1].upper() + title[1:], p.get("user", {}).get("name", "Unknown"),
                        "Unsplash", p.get("links", {}).get("html", ""), "photo", auth))
    return out


def src_commons(q: str, cfg: dict) -> list:
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f'{q} incategory:"Featured pictures on Wikimedia Commons"',
        "gsrnamespace": 6, "gsrlimit": 30, "gsrsort": "random",
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": cfg.get("download_width", 5120),
    })
    data = http_json(f"https://commons.wikimedia.org/w/api.php?{params}")
    out = []
    for p in data.get("query", {}).get("pages", {}).values():
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < cfg.get("min_width", 3840):
            continue
        title = re.sub(r"^File:|\.[A-Za-z]+$", "", p.get("title", ""))
        artist = re.sub(r"<[^>]+>", "", info.get("extmetadata", {}).get("Artist", {}).get("value", "")).strip()
        out.append(cand(f"commons:{p['pageid']}", info.get("thumburl") or info.get("url"),
                        title, artist or "Unknown", "Wikimedia Commons",
                        info.get("descriptionshorturl", "")))
    return out


def src_met(q: str, cfg: dict) -> list:
    params = urllib.parse.urlencode({"q": q, "hasImages": "true", "isPublicDomain": "true", "isHighlight": "true"})
    ids = (http_json(f"https://collectionapi.metmuseum.org/public/collection/v1/search?{params}").get("objectIDs") or [])
    random.shuffle(ids)
    out = []
    for oid in ids[:12]:
        o = http_json(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}")
        if not o.get("primaryImage"):
            continue
        credit = ", ".join(x for x in (o.get("artistDisplayName"), o.get("objectDate")) if x) or "The Met"
        out.append(cand(f"met:{oid}", o["primaryImage"], o.get("title", q), credit,
                        "The Met", o.get("objectURL", ""), "art"))
        time.sleep(0.3)
    return out


def src_aic(q: str, cfg: dict) -> list:
    params = urllib.parse.urlencode({"q": q, "limit": 25,
                                     "fields": "id,title,artist_display,date_display,image_id,is_public_domain"})
    data = http_json(f"https://api.artic.edu/api/v1/artworks/search?{params}&query[term][is_public_domain]=true")
    out = []
    w = cfg.get("download_width", 5120)
    for a in data.get("data", []):
        if not a.get("image_id"):
            continue
        artist = (a.get("artist_display") or "").split("\n")[0]
        credit = ", ".join(x for x in (artist, a.get("date_display")) if x) or "Art Institute of Chicago"
        out.append(cand(f"aic:{a['id']}",
                        f"https://www.artic.edu/iiif/2/{a['image_id']}/full/!{w},{w}/0/default.jpg",
                        a.get("title", q), credit, "Art Institute of Chicago",
                        f"https://www.artic.edu/artworks/{a['id']}", "art"))
    return out


def src_nasa(q: str, cfg: dict) -> list:
    params = urllib.parse.urlencode({"q": q, "media_type": "image", "page_size": 30})
    data = http_json(f"https://images-api.nasa.gov/search?{params}")
    out = []
    items = data.get("collection", {}).get("items", [])
    random.shuffle(items)
    for it in items[:10]:
        d = it["data"][0]
        nasa_id = d["nasa_id"]
        assets = http_json(f"https://images-api.nasa.gov/asset/{nasa_id}").get("collection", {}).get("items", [])
        urls = [a["href"] for a in assets if a["href"].lower().endswith((".jpg", ".png"))]
        big = next((u for u in urls if "~orig" in u), None) or next((u for u in urls if "~large" in u), None)
        if not big:
            continue
        out.append(cand(f"nasa:{nasa_id}", big, d.get("title", q),
                        d.get("secondary_creator") or d.get("center") or "NASA", "NASA",
                        f"https://images.nasa.gov/details/{nasa_id}", "science"))
        time.sleep(0.3)
    return out


SOURCES = {"unsplash": src_unsplash, "commons": src_commons, "met": src_met, "aic": src_aic, "nasa": src_nasa}


# ------------------------------------------------------------------ run ----

def acceptable_file(path: Path, kind: str, cfg: dict) -> bool:
    w, h = image_size(path)
    if w == 0 or h == 0:
        return False
    if kind == "photo":
        return w >= cfg.get("min_width", 3840) and cfg.get("min_aspect", 1.2) <= w / h <= cfg.get("max_aspect", 2.5)
    return max(w, h) >= cfg.get("art_min_dimension", 2400)


def run_query(item: dict, cfg: dict, seen: set, meta: dict, run_subjects: set) -> int:
    q, register, source, purpose = item["query"], item["register"], item["source"], item.get("purpose", "exploit")
    fn = SOURCES.get(source, src_unsplash)
    try:
        cands = fn(q, cfg)
    except Exception as e:
        print(f"  {source} search failed for {q!r}: {e}", file=sys.stderr)
        cands = []
    random.shuffle(cands)
    got = 0
    for c in cands:
        if got >= cfg.get("images_per_query", 3):
            break
        if c["key"] in seen or DOC_WORDS.search(c["title"]):
            continue
        subject = re.sub(r"\W+", "", c["title"].lower())[:16]
        if subject in run_subjects:
            continue
        name = hashlib.sha1(c["key"].encode()).hexdigest()[:16] + ".jpg"
        dest = QUEUE / name
        time.sleep(1.5)
        try:
            download(c["url"], dest, c.get("headers"))
        except Exception as e:
            print(f"  download failed {c['url'][:80]}: {e}", file=sys.stderr)
            continue
        if not acceptable_file(dest, c["kind"], cfg):
            dest.unlink(missing_ok=True)
            continue
        seen.add(c["key"])
        run_subjects.add(subject)
        meta[name] = {"title": c["title"], "credit": c["credit"], "url": c["page"],
                      "source": c["source"], "kind": c["kind"], "register": register,
                      "purpose": purpose, "query": q}
        got += 1
        print(f"  + [{source}/{register}/{purpose}] {c['title'][:70]} -> {name}")
    return got


def main() -> None:
    cfg = load_json(BASE / "config.json", {})
    seen = set((BASE / "seen.txt").read_text().split()) if (BASE / "seen.txt").exists() else set()
    meta = load_json(BASE / "meta.json", {})
    QUEUE.mkdir(parents=True, exist_ok=True)
    plan = load_plan(cfg)
    total = 0
    run_subjects = set()
    for item in plan:
        print(f"query: {item['query']!r} [{item['source']}/{item['register']}/{item.get('purpose')}]")
        n = run_query(item, cfg, seen, meta, run_subjects)
        ledger_add(item["query"], item["register"], item["source"], item.get("purpose", "exploit"), n)
        total += n
    (BASE / "seen.txt").write_text("\n".join(list(seen)[-8000:]))
    save_json(BASE / "meta.json", meta)
    print(f"done: {total} candidates queued")
    sys.stdout.flush()
    if "--no-curate" not in sys.argv:
        subprocess.run(["/bin/bash", str(BASE / "curate.sh")], check=False)


if __name__ == "__main__":
    main()
