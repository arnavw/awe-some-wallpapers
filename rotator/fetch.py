#!/usr/bin/python3
"""Wallpaper fetcher for the WorldWallpapers rotation.

Downloads high-resolution, landscape-oriented photos of architecture,
buildings, and landscapes into ~/Pictures/WorldWallpapers.

Sources, in order of preference:
  1. Unsplash official API (only if `unsplash_access_key` is set in config.json)
  2. Wikimedia Commons "Featured pictures" (award-tier, human-curated)
  3. Wikimedia Commons "Quality images" (larger pool, still human-reviewed)

Topics come from ~/.wallpaper-rotator/config.json — edit that file to change
what you see. Stdlib only, so it runs on the stock macOS python3 from launchd.
"""

import hashlib
import json
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
SEEN_FILE = BASE / "seen.txt"
META_FILE = BASE / "meta.json"
# Downloads land in the queue; a Claude curation pass (curate.sh) decides
# what gets promoted into the live pool at IMAGES.
QUEUE = BASE / "queue"
# Wikimedia robot policy (https://w.wiki/4wJS) requires a descriptive UA with contact info.
USER_AGENT = "WorldWallpapers/1.0 (personal wallpaper rotator; contact: dolphin.arnav@gmail.com)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def load_config() -> dict:
    with open(BASE / "config.json") as f:
        return json.load(f)


def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(SEEN_FILE.read_text().split())
    return set()


def save_seen(seen: set) -> None:
    # Cap the ledger so it never grows unbounded across years of daily runs.
    SEEN_FILE.write_text("\n".join(list(seen)[-5000:]))


def load_meta() -> dict:
    if META_FILE.exists():
        with open(META_FILE) as f:
            return json.load(f)
    return {}


def save_meta(meta: dict) -> None:
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def pick_topics(cfg: dict) -> list:
    """Cycle through the full topic list across fetches instead of sampling:
    a persisted shuffled order advances by topics_per_fetch each run, and
    reshuffles once exhausted, so every topic gets covered before any repeats."""
    state_file = BASE / "topic_cycle.json"
    # The curator gardens explore_topics.txt: experimental searches probing
    # outside the learned taste profile. They join the cycle like any topic.
    explore_file = BASE / "explore_topics.txt"
    extra = []
    if explore_file.exists():
        extra = [l.strip() for l in explore_file.read_text().splitlines()
                 if l.strip() and not l.startswith("#")]
    topics = list(dict.fromkeys(cfg["topics"] + extra))
    n = min(cfg["topics_per_fetch"], len(topics))
    state = {}
    if state_file.exists():
        state = json.loads(state_file.read_text())
    if sorted(state.get("order", [])) != sorted(topics):
        state = {"order": random.sample(topics, len(topics)), "pos": 0}
    picked = []
    while len(picked) < n:
        if state["pos"] >= len(state["order"]):
            state = {"order": random.sample(topics, len(topics)), "pos": 0}
        picked.append(state["order"][state["pos"]])
        state["pos"] += 1
    state_file.write_text(json.dumps(state))
    return picked


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def download(url: str, dest: Path) -> None:
    """Download with backoff — the Commons thumbnail scaler 429s aggressively."""
    delay = 5
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
                while chunk := resp.read(1 << 16):
                    f.write(chunk)
            return
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503) or attempt == 3:
                raise
            time.sleep(delay)
            delay *= 3


def commons_search(topic: str, pool, width: int = 5120, limit: int = 30, sort: str = "random") -> list:
    """Search Commons for images matching `topic`, optionally inside a curated
    pool category. sort='relevance' suits named artworks; 'random' suits broad
    photo topics."""
    search = f'{topic} incategory:"{pool}"' if pool else topic
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": search,
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "gsrsort": "random",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": width,
        }
    )
    data = http_json(f"{COMMONS_API}?{params}")
    return list(data.get("query", {}).get("pages", {}).values())


def topical(title: str, topic: str) -> bool:
    """Require a topic word in the file title — full-text search also matches
    descriptions, which is how a politician's portrait once matched 'opera house'."""
    words = [w for w in re.split(r"\W+", topic.lower()) if len(w) >= 4]
    words = words or topic.lower().split()
    return any(w in title.lower() for w in words)


def acceptable(info: dict, cfg: dict) -> bool:
    w, h = info.get("width", 0), info.get("height", 1)
    if info.get("mime") not in ("image/jpeg", "image/png"):
        return False
    if w < cfg["min_width"]:
        return False
    aspect = w / h
    return cfg["min_aspect"] <= aspect <= cfg["max_aspect"]


def commons_meta(page: dict, info: dict) -> dict:
    """Caption metadata for a Commons page: place-ish title, artist, short link."""
    title = re.sub(r"^File:", "", page.get("title", ""))
    title = re.sub(r"\.[A-Za-z]+$", "", title)
    ext = info.get("extmetadata", {})
    artist = strip_html(ext.get("Artist", {}).get("value", "")) or "Unknown"
    url = info.get("descriptionshorturl") or info.get("descriptionurl", "")
    return {"title": title, "credit": artist, "url": url, "source": "Wikimedia Commons"}


def fetch_topic_commons(topic: str, cfg: dict, seen: set, meta: dict) -> int:
    """Download up to images_per_topic new images for one topic. Returns count."""
    # "featured_only" keeps the pool to award-tier Featured Pictures (community-
    # voted, ~0.1% of Commons). "featured_then_quality" adds the larger but more
    # ordinary Quality-images pool as a fallback when a topic runs dry.
    pools = ["Featured pictures on Wikimedia Commons"]
    if cfg.get("quality_pool") == "featured_then_quality":
        pools.append("Quality images")
    got = 0
    for pool in pools:
        if got >= cfg["images_per_topic"]:
            break
        try:
            pages = commons_search(topic, pool, width=cfg.get("download_width", 5120))
        except Exception as e:  # network hiccup on one pool shouldn't kill the run
            print(f"  search failed for {topic!r} in {pool!r}: {e}", file=sys.stderr)
            continue
        random.shuffle(pages)
        for page in pages:
            if got >= cfg["images_per_topic"]:
                break
            key = f"commons:{page['pageid']}"
            info = (page.get("imageinfo") or [{}])[0]
            if key in seen or not acceptable(info, cfg):
                continue
            if not topical(page.get("title", ""), topic):
                continue
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            ext = ".png" if info.get("mime") == "image/png" else ".jpg"
            name = hashlib.sha1(key.encode()).hexdigest()[:16] + ext
            time.sleep(3)  # pace every attempt — the scaler rate-limits by IP
            try:
                download(url, QUEUE / name)
            except Exception as e:
                print(f"  download failed {url}: {e}", file=sys.stderr)
                continue
            seen.add(key)
            meta[name] = commons_meta(page, info)
            got += 1
            print(f"  + {page['title']} -> {name}")
    return got


def unsplash_meta(photo: dict, detail: dict, topic: str) -> dict:
    """Caption metadata for an Unsplash photo; the per-photo endpoint carries
    location info that search results lack."""
    loc = (detail or {}).get("location") or {}
    place = loc.get("name") or ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)
    desc = (detail or photo).get("description") or photo.get("alt_description") or ""
    title = place or (desc[:1].upper() + desc[1:] if desc else topic.title())
    return {
        "title": title,
        "credit": photo.get("user", {}).get("name", "Unknown"),
        "url": photo.get("links", {}).get("html", ""),
        "source": "Unsplash",
        "likes": photo.get("likes", 0),
    }


def acceptable_art(info: dict, cfg: dict) -> bool:
    """Art scans skip the aspect gate (portrait works get gallery-matted) but
    must be big enough to survive display scaling."""
    if info.get("mime") not in ("image/jpeg", "image/png"):
        return False
    return max(info.get("width", 0), info.get("height", 0)) >= cfg.get("art_min_dimension", 2400)


def fetch_topic_art(topic: str, cfg: dict, seen: set, meta: dict) -> int:
    """Fine-art path: relevance-ranked Commons search across the whole corpus
    (museum scans usually aren't Featured Pictures). The curation pass judges
    reproduction quality by eye."""
    try:
        pages = commons_search(topic, None, width=cfg.get("download_width", 5120), sort="relevance")
    except Exception as e:
        print(f"  art search failed for {topic!r}: {e}", file=sys.stderr)
        return 0
    got = 0
    for page in pages:
        if got >= 2:
            break
        key = f"commons:{page['pageid']}"
        info = (page.get("imageinfo") or [{}])[0]
        if key in seen or not acceptable_art(info, cfg):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        ext = ".png" if info.get("mime") == "image/png" else ".jpg"
        name = hashlib.sha1(key.encode()).hexdigest()[:16] + ext
        time.sleep(3)
        try:
            download(url, QUEUE / name)
        except Exception as e:
            print(f"  download failed {url}: {e}", file=sys.stderr)
            continue
        seen.add(key)
        meta[name] = {**commons_meta(page, info), "kind": "art"}
        got += 1
        print(f"  + {page['title']} -> {name}")
    return got


def fetch_topic_unsplash(topic: str, cfg: dict, seen: set, meta: dict) -> int:
    """Unsplash official API path, used only when an access key is configured.

    Awe filter: results are taken in descending like-count order, and anything
    under `unsplash_min_likes` is skipped — crowd validation is the best proxy
    the API offers for "stunning" vs "someone's decent photo".
    """
    auth = {"User-Agent": USER_AGENT, "Authorization": f"Client-ID {cfg['unsplash_access_key']}"}
    params = urllib.parse.urlencode(
        {"query": topic, "orientation": "landscape", "per_page": 30, "content_filter": "high"}
    )
    req = urllib.request.Request(f"https://api.unsplash.com/search/photos?{params}", headers=auth)
    with urllib.request.urlopen(req, timeout=30) as resp:
        results = json.load(resp).get("results", [])
    results.sort(key=lambda p: p.get("likes", 0), reverse=True)
    got = 0
    for photo in results:
        if got >= cfg["images_per_topic"]:
            break
        key = f"unsplash:{photo['id']}"
        if (
            key in seen
            or photo.get("width", 0) < cfg["min_width"]
            or photo.get("likes", 0) < cfg.get("unsplash_min_likes", 0)
        ):
            continue
        raw = photo["urls"]["raw"] + f"&w={cfg.get('download_width', 5120)}&q=90&fm=jpg"
        name = hashlib.sha1(key.encode()).hexdigest()[:16] + ".jpg"
        try:
            download(raw, QUEUE / name)
        except Exception as e:
            print(f"  download failed {raw}: {e}", file=sys.stderr)
            continue
        # Unsplash API guidelines ask apps to ping download_location per download.
        try:
            loc = photo.get("links", {}).get("download_location")
            if loc:
                urllib.request.urlopen(urllib.request.Request(loc, headers=auth), timeout=15).read()
        except Exception:
            pass
        detail = None
        try:
            req = urllib.request.Request(
                f"https://api.unsplash.com/photos/{photo['id']}", headers=auth
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                detail = json.load(resp)
        except Exception:
            pass  # caption falls back to search-result fields
        seen.add(key)
        meta[name] = unsplash_meta(photo, detail, topic)
        got += 1
        print(f"  + unsplash {photo['id']} ({photo.get('likes', 0)} likes) -> {name}")
    return got


def prune(cfg: dict, meta: dict) -> None:
    """Keep the collection bounded; drop the oldest files (and their caption
    copies and metadata) first."""
    files = sorted(IMAGES.glob("*.[jp]*g"), key=lambda p: p.stat().st_mtime)
    excess = len(files) - cfg["max_images_kept"]
    for p in files[:max(0, excess)]:
        p.unlink()
        (IMAGES / ".display" / p.name).unlink(missing_ok=True)
        meta.pop(p.name, None)
        print(f"  - pruned {p.name}")


def run_curation() -> None:
    """Hand the queue to the Claude curation pass (which also composes
    captions for whatever it promotes)."""
    subprocess.run(["/bin/bash", str(BASE / "curate.sh")], check=False)


def main() -> None:
    cfg = load_config()
    seen = load_seen()
    meta = load_meta()
    IMAGES.mkdir(parents=True, exist_ok=True)
    QUEUE.mkdir(parents=True, exist_ok=True)
    topics = pick_topics(cfg)
    total = 0
    use_unsplash = bool(cfg.get("unsplash_access_key"))
    for topic in topics:
        if topic.startswith("art:"):
            print(f"fetching: {topic} (commons art)")
            total += fetch_topic_art(topic[4:].strip(), cfg, seen, meta)
            continue
        print(f"fetching: {topic} ({'unsplash' if use_unsplash else 'wikimedia commons'})")
        if use_unsplash:
            try:
                total += fetch_topic_unsplash(topic, cfg, seen, meta)
                continue
            except Exception as e:
                print(f"  unsplash failed ({e}); falling back to commons", file=sys.stderr)
        total += fetch_topic_commons(topic, cfg, seen, meta)
    save_seen(seen)
    prune(cfg, meta)
    save_meta(meta)
    print(f"done: {total} new images queued for curation")
    sys.stdout.flush()
    run_curation()


if __name__ == "__main__":
    main()
