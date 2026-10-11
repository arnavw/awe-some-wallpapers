#!/usr/bin/python3
"""Intake engine: turn a query plan into a queue of wallpaper candidates.

Where queries come from, in priority order:
  1. plan.json — six queries the curator wrote at the end of its last run,
     each tagged with a register (bandit arm), a source, and a purpose
     (exploit / surprise / orthogonal). Consumed once, then deleted.
  2. Otherwise a bootstrap plan synthesized from bandit.json: Thompson
     samples pick exploit arms, the least-pulled arms fill surprise slots,
     and each arm's seed phrases (below) become queries.

Every executed query is ledgered as a `query` event and never executed again:
the ledger is the novelty guarantee at the query level. A query an outage cut
short (the search raised, or every download did) is logged as `query_error`
instead, left out of the ledger, and saved to plan.retry.json for the next
run, so network trouble neither burns queries nor discards the curator's plan.

Demand: launchd runs this hourly, and it works only while the reserve (approved,
captioned wallpapers no Mac has shown) is below pool_target. Each intake is sized
to the shortfall at about ten candidates per keep, the curator's usual rate, and
at most max_curations_per_day passes run in any 24 hours, so a picky stretch
cannot spend the Claude plan without bound. `--force` (wp fetch) ignores both.

Backpressure: while the queue holds max_queue or more unjudged candidates
(the curator is behind or failing), intake pauses and only the chained
curation pass runs, so a stalled curator cannot bury itself in downloads.
The default of 30 is about two intakes: a queue much larger than that no
longer fits the curator's view at once, and a recovery run slows several-fold.

Sources, chosen per register (SOURCE_MIX, or the curator's plan) — all keyless
except Unsplash, ISS and Flickr, which sit out until their key is in config:
  unsplash      photography, relevance-ranked, no like-floor (the curator's eyes
                are the quality gate; ranking by likes only ever found postcards)
  commons       Wikimedia Commons: Featured and Quality images first, then the rest
  esawebb, esahubble, eso, noirlab
                agency astronomy archives (CC BY 4.0), sized before download
  photojournal  NASA/JPL planetary images, via science.nasa.gov search
  earthobs      NASA Earth Observatory satellite and ISS views, same route
  nasa          NASA image library: a mixed science archive
  cleveland     Cleveland Museum of Art open access (CC0)
  smk           SMK, National Gallery of Denmark (public domain)
  commons_art   prints, plates and paintings across all of Commons
  met, aic      The Met and the Art Institute of Chicago, public domain
  nga           National Gallery of Art open access, searched by what each
                picture shows (its published alt text), from a monthly local index
  iss           ISS astronaut photography of Earth (needs eol_api_key)
  flickr        Flickr, openly licensed, by interestingness (needs flickr_api_key)

Stdlib only; runs on the stock macOS python3 from launchd.
"""

import csv
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
RETRY_PLAN = BASE / "plan.retry.json"   # queries an outage cut short, run again first
MAX_ATTEMPTS = 3                         # failures after which a query is spent rather than retried
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
    """Every query ever executed, from the event store (never repeat one)."""
    sys.path.insert(0, str(BASE))
    from events import load
    return {e["query"].lower() for e in load() if e.get("type") == "query" and e.get("query")}


def ledger_add(query: str, register: str, source: str, purpose: str, yielded: int) -> None:
    events_append("query", query=query, register=register, source=source, purpose=purpose, **{"yield": yielded})


def events_append(type_: str, **data) -> None:
    sys.path.insert(0, str(BASE))
    from events import append
    append(type_, **data)


# ----------------------------------------------------------------- plan ----

SOURCE_MIX = {
    "fine art": ["nga", "cleveland", "smk", "commons_art", "met"],
    "illustration": ["commons_art", "nga", "cleveland", "smk", "aic"],
    "science": ["esawebb", "esahubble", "eso", "noirlab", "photojournal", "nasa"],
    "night sky": ["eso", "commons", "unsplash", "flickr"],
    "storm/weather": ["unsplash", "flickr", "commons"],
    **{r: ["unsplash", "commons", "earthobs", "iss", "flickr"]
       for r in ("ice/polar", "desert/ground", "water/coast", "volcanic")},
}
DEFAULT_MIX = ["unsplash", "unsplash", "commons", "flickr"]
KEYED = {"unsplash": "unsplash_access_key", "iss": "eol_api_key", "flickr": "flickr_api_key"}


def available(source: str, cfg: dict) -> bool:
    """A known source whose key, if it needs one, is configured."""
    return source in SOURCES and bool(cfg.get(KEYED[source], "") if source in KEYED else True)


def source_for(register: str, cfg: dict) -> str:
    """The source for a plan entry that names none, or names one that cannot run."""
    return random.choice([s for s in SOURCE_MIX.get(register, DEFAULT_MIX) if available(s, cfg)] or ["commons"])


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
        plan.append({"query": q, "register": r, "source": source_for(r, cfg), "purpose": purpose})
    return plan


def load_plan(cfg: dict) -> list:
    """Queries that failed on the network last time, then the curator's plan;
    a bootstrap plan only when both are empty. Both files are consumed."""
    plan = []
    for plan_file in (RETRY_PLAN, BASE / "plan.json"):
        plan += load_json(plan_file, None) or []
        plan_file.unlink(missing_ok=True)
    if plan:
        used, picked = ledger_queries(), set()
        plan = [p for p in plan if p.get("query", "").lower() not in used and p.get("register") in REGISTERS
                and not (p["query"].lower() in picked or picked.add(p["query"].lower()))][:8]
        for p in plan:
            if not available(p.get("source", ""), cfg):
                p["source"] = source_for(p["register"], cfg)
            p.setdefault("purpose", "exploit")
        if plan:
            return plan
    return bootstrap_plan(cfg)


# -------------------------------------------------------------- sources ----

def http_json(url: str, headers=None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def http_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def ascii_url(url: str) -> str:
    """Percent-encode any non-ASCII character (NASA slugs carry curly quotes)."""
    return re.sub(r"[^\x21-\x7e]", lambda m: urllib.parse.quote(m.group()), url)


def download(url: str, dest: Path, headers=None) -> None:
    url = ascii_url(url)
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
    # Page 1 only: queries never repeat, and a random later page lands past
    # the end of a niche query's results.
    params = urllib.parse.urlencode({"query": q, "orientation": "landscape", "per_page": 30,
                                     "page": 1, "content_filter": "high"})
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


COMMONS_TIERS = {"featured": 0, "potd": 0, "poty": 0, "valued": 1, "quality": 2}


COMMONS_ASSESSED = "incategory:Featured_pictures_on_Wikimedia_Commons|Quality_images"


def commons_search(gsrsearch: str, sort: str) -> list:
    """Commons file pages matching a CirrusSearch string, with their imageinfo."""
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": gsrsearch, "gsrnamespace": 6, "gsrlimit": 30, "gsrsort": sort,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiextmetadatafilter": "Artist|Assessments", "iiurlwidth": 3840,
    })
    return list(http_json(f"https://commons.wikimedia.org/w/api.php?{params}").get("query", {}).get("pages", {}).values())


def src_commons(q: str, cfg: dict) -> list:
    """Screen-shaped files at least min_width wide, assessed ones first.

    Featured and Quality images come first (in random order), but alone they
    leave most specific queries empty: "hair ice" has none at 4K, all of
    Commons has 37. So when the assessed set is short, the whole archive is
    searched too, most relevant first, and ranks behind it. Multi-word queries
    are quoted: unquoted, "sun pillar" matches nebulae and temple pillars.
    Shape is checked from imageinfo before download. Thumbnails stop at 3840 px.
    """
    phrase = f'"{q}"' if " " in q.strip() else q
    width = cfg.get("min_width", 3840)
    lo, hi = cfg.get("min_aspect", 1.2), cfg.get("max_aspect", 2.5)
    pages = commons_search(f"{phrase} filew:>{width - 1} {COMMONS_ASSESSED}", "random")
    if len(pages) < 8:
        time.sleep(1)
        pages += commons_search(f"{phrase} filew:>{width - 1}", "relevance")
    out, ids = [], set()
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        w, h = info.get("width", 0), info.get("height", 0)
        if p["pageid"] in ids or info.get("mime") not in ("image/jpeg", "image/png") or w < width or not h or not lo <= w / h <= hi:
            continue
        ids.add(p["pageid"])
        ext = info.get("extmetadata", {})
        tiers = ext.get("Assessments", {}).get("value", "").split("|")
        title = re.sub(r"^File:|\.[A-Za-z]+$", "", p.get("title", ""))
        artist = re.sub(r"<[^>]+>", "", ext.get("Artist", {}).get("value", "")).strip()
        c = cand(f"commons:{p['pageid']}", info.get("thumburl") or info.get("url"),
                 title, artist or "Unknown", "Wikimedia Commons", info.get("descriptionshorturl", ""))
        c["rank"] = min((COMMONS_TIERS[t] for t in tiers if t in COMMONS_TIERS), default=3)
        out.append(c)
    return out


MET_API = "https://collectionapi.metmuseum.org/public/collection"
MET_CANDIDATES = 12   # public-domain candidates handed to run_query per query
MET_LOOKUPS = 36      # object lookups spent finding them


MET_MEDIA = ("Paintings", "Prints", "Photographs")


def src_met(q: str, cfg: dict) -> list:
    """Public-domain paintings, prints and photographs from The Met matching q,
    in random order.

    Search is v1.1 (v1 was retired 2026-10-01), up to 500 IDs per page. It
    takes one medium per request, so each of MET_MEDIA is searched. It ignores
    isPublicDomain, and copyrighted objects carry no primaryImage, so rights
    are checked on each object. No isHighlight: the Met defines a highlight as
    a popular and important work, which is the canon the curator turns away.
    """
    ids = []
    for medium in MET_MEDIA:
        params = urllib.parse.urlencode({"q": q, "hasImages": "true", "medium": medium, "limit": 500})
        ids += http_json(f"{MET_API}/v1.1/search?{params}").get("objectIDs") or []
    ids = list(dict.fromkeys(ids))
    random.shuffle(ids)
    out = []
    for oid in ids[:MET_LOOKUPS]:
        if len(out) >= MET_CANDIDATES:
            break
        o = http_json(f"{MET_API}/v1/objects/{oid}")
        time.sleep(0.3)
        if not (o.get("isPublicDomain") and o.get("primaryImage")):
            continue
        credit = ", ".join(x for x in (o.get("artistDisplayName"), o.get("objectDate")) if x) or "The Met"
        out.append(cand(f"met:{oid}", o["primaryImage"], o.get("title", q), credit,
                        "The Met", o.get("objectURL", ""), "art"))
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


# ---------------------------------------------------- agency archives ----
# ESA/Webb, ESA/Hubble, ESO and NOIRLab run the same platform (djangoplicity):
# a search page embeds its results as `id: '...'`, and every image has a JSON
# record (/images/<id>/api/json/) with title, credit, rights (CC BY 4.0), type
# and each rendition's pixel size, so size and shape are checked before any
# download. "Large" runs to 15,000+ px and hundreds of megabytes; the
# "publicationjpg" rendition (4000 px on the long side) stands in whenever
# Large is over 6000 px wide or 60 MB (ESO has none, so huge ESO files skip).
DJANGOPLICITY = {
    "esawebb": ("https://esawebb.org", "ESA/Webb", True),
    "esahubble": ("https://esahubble.org", "ESA/Hubble", True),
    "eso": ("https://www.eso.org/public", "ESO", False),
    "noirlab": ("https://noirlab.edu/public", "NOIRLab", True),
}
LARGE_MAX_BYTES = 60_000_000
NOT_A_PICTURE = re.compile(r"artist|illustration|impression|concept|annotated|labell?ed|chart|spectrum|diagram|"
                           r"comparison|infographic|\bgraphs?\b|\bmap\b|logo|poster|timeline|(?<!-)\bscale\b|compass", re.I)


def dp_text(value) -> str:
    """Three of the sites send strings as Python bytes reprs ("b'...'")."""
    s = str(value or "")
    if re.match(r"^b(['\"]).*\1$", s, re.S):
        import ast
        try:
            return ast.literal_eval(s).decode("utf-8", "replace")
        except (ValueError, SyntaxError):
            return s[2:-1]
    return s


def src_djangoplicity(site: str, q: str, cfg: dict) -> list:
    base, label, has_publication = DJANGOPLICITY[site]
    html = http_text(f"{base}/images/?{urllib.parse.urlencode({'search': q})}")
    ids = list(dict.fromkeys(re.findall(r"id: '([a-z0-9-]+)'", html)))[:12]
    lo, hi, min_w = cfg.get("min_aspect", 1.2), cfg.get("max_aspect", 2.5), cfg.get("min_width", 3840)
    out = []
    for image_id in ids:
        d = http_json(f"{base}/images/{image_id}/api/json/")
        time.sleep(0.3)
        title = dp_text(d.get("Title"))
        if d.get("Type") not in (None, "Observation", "Photographic") or NOT_A_PICTURE.search(title):
            continue
        large = next((r for r in d.get("Resources", []) if r.get("ResourceType") == "Large"), None)
        if not large or not large.get("Dimensions"):
            continue
        w, h = (int(v) for v in large["Dimensions"][:2])
        if not h or not lo <= w / h <= hi:
            continue
        url = large["URL"]
        if has_publication and (w > 6000 or large.get("FileSize", 0) > LARGE_MAX_BYTES):
            url, w = url.replace("/large/", "/publicationjpg/"), 4000   # plenty for a screen
        elif large.get("FileSize", 0) > LARGE_MAX_BYTES:
            continue
        if w < min_w:
            continue
        out.append(cand(f"{site}:{image_id}", url, title, dp_text(d.get("Credit")) or label, label,
                        f"{base}/images/{image_id}/", "science"))
    return out


# --------------------------------------------- NASA science (WordPress) ----
# Earth Observatory and Photojournal moved to science.nasa.gov, whose
# WordPress API searches posts by keyword. Each post page's srcset names the
# original's width and height, and NASA's image resizer serves any width of it.
NASA_SCIENCE = "https://science.nasa.gov/wp-json/wp/v2"
PHOTOJOURNAL_CATEGORY = 19797
EO_SKIP = re.compile(r"map|chart|graph|anomal|trend|plot|legend|_tmo_|_amo_", re.I)
# Photojournal also files lab and engineering shots and explainer graphics.
PJ_SKIP = re.compile(r"prototype|testing|\btests?\b|robot|engineers?|clean ?room|assembl|mock-?up|\bteam\b|"
                     r"may have|\bcould\b|\bhow\b|\bwhat\b|\bwhy\b|infographic|poster", re.I)


def nasa_science_image(page: str, kind: str):
    """(url at <= 5120 px wide, width, height) of a post's own image, or None.

    The post's og:image names its picture (site templates carry other large
    images); Earth Observatory's og:image is the _th thumbnail of the _lrg
    file. The original's size is the largest entry in that file's srcset.
    """
    html = curl_text(page)
    og = re.search(r'<meta property="og:image" content="https://assets\.science\.nasa\.gov/content/dam/([^"]+?)/jcr:content', html)
    if not og:
        return None
    path = og.group(1)
    if kind == "earthobs":
        path = re.sub(r"_th\.(jpe?g)$", r"_lrg.\1", path)
    base = f"https://assets.science.nasa.gov/dynamicimage/assets/{path}"
    dims = [(int(w), int(h)) for w, h in re.findall(re.escape(base) + r"\?w=(\d+)&amp;h=(\d+)", html)]
    if not dims:
        return None
    w, h = max(dims)
    tw = min(w, 5120)
    return f"{base}?w={tw}&h={round(h * tw / w)}&fit=crop", tw, h * tw / w


def curl_text(url: str) -> str:
    """GET through /usr/bin/curl. science.nasa.gov answers Python's TLS client
    with 403 whatever the headers (always on /wp-json/, on pages once it has
    seen a few), while curl's handshake passes; outside our control, so curl it
    is. Its images live on assets.science.nasa.gov, which serves Python fine.
    Raises on any HTTP or network failure, like http_text."""
    out = subprocess.run(["/usr/bin/curl", "-sSfL", "--max-time", "30", "-A", UA, ascii_url(url)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise OSError(f"curl exit {out.returncode}: {out.stderr.strip()[:120]}")
    return out.stdout


def curl_json(url: str):
    return json.loads(curl_text(url))


def src_nasa_science(kind: str, q: str, cfg: dict) -> list:
    if kind == "photojournal":
        params = {"search": q, "categories": PHOTOJOURNAL_CATEGORY, "per_page": 12, "_fields": "link,title"}
        posts = [(p["link"], p["title"]["rendered"]) for p in curl_json(f"{NASA_SCIENCE}/posts?{urllib.parse.urlencode(params)}")]
        label = "NASA/JPL Photojournal"
    else:
        params = {"search": q, "per_page": 20, "_fields": "url,title"}
        posts = [(p["url"], p["title"]) for p in curl_json(f"{NASA_SCIENCE}/search?{urllib.parse.urlencode(params)}")
                 if "/earth/earth-observatory/" in p.get("url", "")]
        label = "NASA Earth Observatory"
    lo, hi, min_w = cfg.get("min_aspect", 1.2), cfg.get("max_aspect", 2.5), cfg.get("min_width", 3840)
    out = []
    for link, title in posts[:12]:
        found = nasa_science_image(link, kind)
        time.sleep(0.3)
        if not found:
            continue
        url, w, h = found
        if w < min_w or not lo <= w / h <= hi or (kind == "earthobs" and EO_SKIP.search(url)):
            continue
        title = re.sub(r"&#8217;", "’", re.sub(r"&#821[12];", "–", title))
        if NOT_A_PICTURE.search(title) or (kind == "photojournal" and PJ_SKIP.search(title)):
            continue
        out.append(cand(f"{kind}:{url.split('?')[0]}", url, title, label, label, link, "science"))
    return out


# ------------------------------------------------------------- museums ----

def src_cleveland(q: str, cfg: dict) -> list:
    """Cleveland Museum of Art open access (CC0). The print JPEG reaches ~3400 px."""
    params = urllib.parse.urlencode({"q": q, "has_image": 1, "cc0": 1, "limit": 30})
    out = []
    for a in http_json(f"https://openaccess-api.clevelandart.org/api/artworks/?{params}").get("data", []):
        if a.get("type") not in ("Painting", "Print", "Drawing", "Photograph"):   # no bowls or lacquer boxes
            continue
        img = (a.get("images") or {}).get("print") or {}
        if not img.get("url") or max(int(img.get("width") or 0), int(img.get("height") or 0)) < cfg.get("art_min_dimension", 2400):
            continue
        who = ((a.get("creators") or [{}])[0].get("description") or "").split(" (")[0]
        credit = ", ".join(x for x in (who, a.get("creation_date")) if x) or "Cleveland Museum of Art"
        out.append(cand(f"cleveland:{a['id']}", img["url"], a.get("title", q), credit,
                        "Cleveland Museum of Art", a.get("url", ""), "art"))
    return out


def src_smk(q: str, cfg: dict) -> list:
    """SMK, the National Gallery of Denmark (public domain)."""
    params = urllib.parse.urlencode({"keys": q, "filters": "[has_image:true],[public_domain:true]", "offset": 0, "rows": 30})
    out = []
    for a in http_json(f"https://api.smk.dk/api/v1/art/search/?{params}").get("items", []):
        if not a.get("image_native") or max(a.get("image_width") or 0, a.get("image_height") or 0) < cfg.get("art_min_dimension", 2400):
            continue
        title = ((a.get("titles") or [{}])[0]).get("title") or q
        who = ((a.get("production") or [{}])[0]).get("creator") or ""
        if "," in who:   # "Neer, Aert van der" -> "Aert van der Neer"
            who = " ".join(reversed([p.strip() for p in who.split(",", 1)]))
        period = ((a.get("production_date") or [{}])[0]).get("period") or ""
        out.append(cand(f"smk:{a['object_number']}", a["image_native"], title,
                        ", ".join(x for x in (who, period) if x) or "SMK", "SMK", a.get("frontend_url", ""), "art"))
    return out


def src_commons_art(q: str, cfg: dict) -> list:
    """All of Commons at artwork size: prints, plates and paintings are rarely
    Featured or Quality images, so this search drops that restriction."""
    width = cfg.get("art_min_dimension", 2400)
    phrase = f'"{q}"' if " " in q.strip() else q
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{phrase} fileres:>{width - 1}", "gsrnamespace": 6, "gsrlimit": 30,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiextmetadatafilter": "Artist|Assessments", "iiurlwidth": 3840,
    })
    out = []
    for p in http_json(f"https://commons.wikimedia.org/w/api.php?{params}").get("query", {}).get("pages", {}).values():
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png") or max(info.get("width", 0), info.get("height", 0)) < width:
            continue
        ext = info.get("extmetadata", {})
        artist = re.sub(r"<[^>]+>", "", ext.get("Artist", {}).get("value", "")).strip()
        c = cand(f"commons:{p['pageid']}", info.get("thumburl") or info.get("url"),
                 re.sub(r"^File:|\.[A-Za-z]+$", "", p.get("title", "")), artist or "Unknown",
                 "Wikimedia Commons", info.get("descriptionshorturl", ""), "art")
        tiers = ext.get("Assessments", {}).get("value", "").split("|")
        c["rank"] = min((COMMONS_TIERS[t] for t in tiers if t in COMMONS_TIERS), default=3)
        out.append(c)
    return out


# ---------------------------------------------- National Gallery of Art ----
# NGA publishes its open-access collection as CSVs on GitHub, each image with
# AI-written alt text describing what it shows. Searching that text finds
# pictures by content ("moonlit harbor", "fog over a river") where titles
# rarely say it. The CSVs (~170 MB) are fetched once a month and reduced to a
# local JSON-lines index of open-access paintings, prints, drawings and
# photographs; searches run against the index.
NGA_DATA = "https://raw.githubusercontent.com/NationalGalleryOfArt/opendata/main/data"
NGA_INDEX = BASE / "cache" / "nga.jsonl"
NGA_MAX_AGE = 30 * 86400
NGA_CLASSES = ("Painting", "Print", "Drawing", "Photograph")


def build_nga_index(dest: Path) -> None:
    """Download the NGA CSVs and write the index to dest, replacing it whole."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    csv.field_size_limit(1 << 24)   # provenance and alt-text fields run long
    objects_csv, images_csv = dest.parent / "nga-objects.csv", dest.parent / "nga-images.csv"
    try:
        download(f"{NGA_DATA}/objects.csv", objects_csv)
        download(f"{NGA_DATA}/published_images.csv", images_csv)
        objects = {}
        with open(objects_csv, newline="", encoding="utf-8") as f:
            for o in csv.DictReader(f):
                if o["classification"] in NGA_CLASSES:
                    objects[o["objectid"]] = (o["title"], o["displaydate"], o["attribution"], o["classification"])
        tmp = dest.with_suffix(".new")
        with open(images_csv, newline="", encoding="utf-8") as f, open(tmp, "w") as out:
            for r in csv.DictReader(f):
                o = objects.get(r["depictstmsobjectid"])
                if not o or r["openaccess"] != "1" or r["viewtype"] != "primary":
                    continue
                out.write(json.dumps({"id": r["depictstmsobjectid"], "uuid": r["uuid"],
                                      "w": int(r["width"] or 0), "h": int(r["height"] or 0),
                                      "title": o[0], "date": o[1], "artist": o[2], "class": o[3],
                                      "alt": r["assistivetext"]}, ensure_ascii=False) + "\n")
        tmp.replace(dest)
    finally:
        objects_csv.unlink(missing_ok=True)
        images_csv.unlink(missing_ok=True)


def src_nga(q: str, cfg: dict) -> list:
    """Works whose title or alt text holds every word of q; title matches first."""
    if not NGA_INDEX.exists() or time.time() - NGA_INDEX.stat().st_mtime > NGA_MAX_AGE:
        build_nga_index(NGA_INDEX)
    words = [re.compile(rf"\b{re.escape(w)}", re.I) for w in q.split()]
    if not words:
        return []
    min_dim = cfg.get("art_min_dimension", 2400)
    out = []
    with open(NGA_INDEX) as f:
        for line in f:
            a = json.loads(line)
            if max(a["w"], a["h"]) < min_dim:
                continue
            in_title = all(w.search(a["title"]) for w in words)
            if not in_title and not all(w.search(a["title"]) or w.search(a["alt"]) for w in words):
                continue
            side = min(5120, max(a["w"], a["h"]))
            c = cand(f"nga:{a['id']}", f"https://api.nga.gov/iiif/{a['uuid']}/full/!{side},{side}/0/default.jpg",
                     a["title"] or q, ", ".join(x for x in (a["artist"], a["date"]) if x) or "National Gallery of Art",
                     "National Gallery of Art", f"https://www.nga.gov/collection/art-object-page.{a['id']}.html", "art")
            c["rank"] = 0 if in_title else 1
            out.append(c)
    out.sort(key=lambda c: (c["rank"], random.random()))
    return out[:60]


# --------------------------------------------- ISS astronaut photography ----
# NASA JSC's Gateway to Astronaut Photography of Earth. The API filters the
# human-catalogued `frames` table (features, place names, cloud, tilt) and
# joins `images`, which names each file's size, so only full-size, unannotated
# frames that fit the screen are fetched. Queries are feature or place names
# ("delta", "Lena", "sea ice"); the catalogue stores them in capitals.
EOL = "https://eol.jsc.nasa.gov"
ISS_RETURN = ("frames|mission|frames|roll|frames|frame|frames|feat|frames|geon|frames|cldp|frames|tilt|"
              "images|directory|images|filename|images|width|images|height|images|annotated|images|filesize")
CLOUD_SUBJECTS = re.compile(r"cloud|storm|cyclone|hurricane|typhoon|vortex|vortices|aurora|lightning|night", re.I)


def iss_name(s: str) -> str:
    """The catalogue's capitals in title case, keeping country acronyms."""
    return re.sub(r"[A-Za-z]+", lambda m: m.group() if m.group() in ("USA", "UK", "UAE", "DRC") else m.group().capitalize(), s)


def src_iss(q: str, cfg: dict) -> list:
    """Full-size ISS frames whose catalogued features, then place names, match q.
    Clear frames rank first unless q asks for weather."""
    key = cfg.get("eol_api_key")
    if not key:
        return []
    term = re.sub(r"[^A-Za-z0-9 .,-]", "", q).strip().upper()   # the only characters the API accepts
    if not term:
        return []
    lo, hi, min_w = cfg.get("min_aspect", 1.2), cfg.get("max_aspect", 2.5), cfg.get("min_width", 3840)
    rows = []
    for field in ("feat", "geon"):
        query = (f"frames|{field}|like|*{term}*|images|directory|like|*large*|"
                 f"images|width|ge|{min_w}|images|annotated|eq|N")
        params = urllib.parse.urlencode({"query": query, "return": ISS_RETURN, "key": key})
        found = http_json(f"{EOL}/SearchPhotos/PhotosDatabaseAPI/PhotosDatabaseAPI.pl?{params}")
        if not isinstance(found, list):   # errors (a bad key, a bad field) come back as an object
            raise OSError(f"EOL API: {str(found)[:160]}")
        rows += found
        if len(rows) >= 30:
            break
    weather = bool(CLOUD_SUBJECTS.search(q))
    out, ids = [], set()
    for r in rows:
        mission, roll, frame = r.get("frames.mission"), r.get("frames.roll"), r.get("frames.frame")
        w, h = int(r.get("images.width") or 0), int(r.get("images.height") or 0)
        if (mission, frame) in ids or not h or not lo <= w / h <= hi or int(r.get("images.filesize") or 0) > LARGE_MAX_BYTES:
            continue
        ids.add((mission, frame))
        feature = (r.get("frames.feat") or "").split(",")[0].strip()
        geon = (r.get("frames.geon") or "").replace("-", ", ")
        title = ", ".join(iss_name(x) for x in (feature, geon) if x) or f"{mission}-{roll}-{frame}"
        c = cand(f"iss:{mission}-{roll}-{frame}", f"{EOL}/DatabaseImages/{r['images.directory']}/{r['images.filename']}",
                 title, f"{mission} crew, NASA JSC", "ISS astronaut photography",
                 f"{EOL}/SearchPhotos/photo.pl?mission={mission}&roll={roll}&frame={frame}", "science")
        cloud = int(float(r.get("frames.cldp") or 100))
        c["rank"] = 0 if weather else (0 if cloud <= 10 else 1 if cloud <= 25 else 2)
        out.append(c)
    return out


# --------------------------------------------------------------- Flickr ----
# Openly licensed photos (the Creative Commons family, no known copyright, US
# government, CC0, public domain), ordered by Flickr's interestingness within
# the query. Interestingness only orders a query's results; favourite counts
# would find postcards, as likes did on Unsplash.
FLICKR_LICENSES = "1,2,3,4,5,6,7,8,9,10"
FLICKR_SIZES = ("5k", "6k", "o", "4k")   # first one at least min_width wide is fetched


def src_flickr(q: str, cfg: dict) -> list:
    key = cfg.get("flickr_api_key")
    if not key:
        return []
    params = urllib.parse.urlencode({
        "method": "flickr.photos.search", "api_key": key, "text": q, "license": FLICKR_LICENSES,
        "sort": "interestingness-desc", "content_types": 0, "media": "photos", "safe_search": 1,
        "per_page": 60, "extras": "owner_name,url_o,url_6k,url_5k,url_4k",
        "format": "json", "nojsoncallback": 1,
    })
    data = http_json(f"https://api.flickr.com/services/rest/?{params}")
    if data.get("stat") != "ok":
        raise OSError(f"flickr: {data.get('message', data)}")
    lo, hi, min_w = cfg.get("min_aspect", 1.2), cfg.get("max_aspect", 2.5), cfg.get("min_width", 3840)
    out = []
    for i, p in enumerate(data.get("photos", {}).get("photo", [])):
        size = next((s for s in FLICKR_SIZES if p.get(f"url_{s}") and int(p.get(f"width_{s}") or 0) >= min_w), None)
        if not size:
            continue
        w, h = int(p[f"width_{size}"]), int(p[f"height_{size}"] or 0)
        if not h or not lo <= w / h <= hi:
            continue
        c = cand(f"flickr:{p['id']}", p[f"url_{size}"], p.get("title") or q, p.get("ownername") or "Flickr",
                 "Flickr", f"https://www.flickr.com/photos/{p['owner']}/{p['id']}")
        c["rank"] = i // 10   # interestingness in bands of ten, shuffled within a band
        out.append(c)
    return out


SOURCES = {
    "unsplash": src_unsplash, "commons": src_commons, "nasa": src_nasa,
    "met": src_met, "aic": src_aic, "cleveland": src_cleveland, "smk": src_smk, "commons_art": src_commons_art,
    **{site: (lambda s: lambda q, cfg: src_djangoplicity(s, q, cfg))(site) for site in DJANGOPLICITY},
    "photojournal": lambda q, cfg: src_nasa_science("photojournal", q, cfg),
    "earthobs": lambda q, cfg: src_nasa_science("earthobs", q, cfg),
    "iss": src_iss, "flickr": src_flickr, "nga": src_nga,
}


# ------------------------------------------------------------------ run ----

def acceptable_file(path: Path, kind: str, cfg: dict) -> bool:
    w, h = image_size(path)
    if w == 0 or h == 0:
        return False
    if kind in ("photo", "science"):   # science fills the screen too, so it meets the photo gate
        return w >= cfg.get("min_width", 3840) and cfg.get("min_aspect", 1.2) <= w / h <= cfg.get("max_aspect", 2.5)
    return max(w, h) >= cfg.get("art_min_dimension", 2400)


def run_query(item: dict, cfg: dict, seen: set, meta: dict, run_subjects: set) -> tuple:
    """Queue up to images_per_query candidates for one query.

    Returns (queued, error). error names an outage — the search raised, or every
    download did — so the caller can retry the query instead of ledgering a
    zero that says nothing about taste. Candidates go in rank order (a
    source's quality tier; 0 when it has none), shuffled within a rank.
    """
    q, register, source, purpose = item["query"], item["register"], item["source"], item.get("purpose", "exploit")
    try:
        cands = SOURCES[source](q, cfg)
    except Exception as e:
        print(f"  {source} search failed for {q!r}: {e}", file=sys.stderr)
        return 0, f"search failed: {e}"
    cands.sort(key=lambda c: (c.get("rank", 0), random.random()))
    got = tried = failed = 0
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
        tried += 1
        try:
            download(c["url"], dest, c.get("headers"))
        except Exception as e:
            failed += 1
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
    if got == 0 and tried and failed == tried:
        return 0, f"all {tried} downloads failed"
    return got, None


def queued_count() -> int:
    return sum(1 for p in QUEUE.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def reserve() -> int:
    """Approved wallpapers waiting their turn: in the pool, captioned, never
    shown on any Mac, and not on screen now."""
    sys.path.insert(0, str(BASE))
    from events import load
    shown = {e.get("image") for e in load() if e.get("type") == "shown"}
    state = BASE / "current.txt"
    current = Path(state.read_text().strip()).name if state.exists() else ""
    images = Path.home() / "Pictures" / "WorldWallpapers"
    return sum(1 for p in images.iterdir()
               if p.suffix.lower() in (".jpg", ".jpeg", ".png") and p.name not in shown
               and p.name != current and (images / ".display" / p.name).exists())


def curations_today() -> int:
    sys.path.insert(0, str(BASE))
    from events import load
    since = time.time() - 86400
    return sum(1 for e in load() if e.get("type") == "curation" and e["ts"] >= since)


def intake(cfg: dict, want: int) -> None:
    """Run one query plan, queueing about `want` candidates across its queries."""
    seen = set((BASE / "seen.txt").read_text().split()) if (BASE / "seen.txt").exists() else set()
    meta = load_json(BASE / "meta.json", {})
    plan = load_plan(cfg)
    floor = int(cfg.get("images_per_query", 3))
    per_query = max(floor, min(8, -(-want // max(1, len(plan)))))
    cfg = {**cfg, "images_per_query": per_query}
    print(f"{time.strftime('%F %T')} intake: {len(plan)} queries, up to {per_query} images each")
    total = 0
    run_subjects = set()
    retry = []
    sys.path.insert(0, str(BASE))
    from events import load
    failures = {}
    for e in load():
        if e.get("type") == "query_error" and e.get("query"):
            failures[e["query"].lower()] = failures.get(e["query"].lower(), 0) + 1
    for item in plan:
        print(f"query: {item['query']!r} [{item['source']}/{item['register']}/{item.get('purpose')}]")
        n, error = run_query(item, cfg, seen, meta, run_subjects)
        if error:   # an outage, not a verdict: keep the query for the next run
            events_append("query_error", query=item["query"], register=item["register"],
                          source=item["source"], purpose=item.get("purpose", "exploit"), error=error[:200])
            if failures.get(item["query"].lower(), 0) + 1 < MAX_ATTEMPTS:
                retry.append(item)
                continue
            print(f"  {item['query']!r} failed {MAX_ATTEMPTS} times; ledgered as spent", file=sys.stderr)
        ledger_add(item["query"], item["register"], item["source"], item.get("purpose", "exploit"), n)
        total += n
    if retry:
        save_json(RETRY_PLAN, retry)
        print(f"{len(retry)} queries failed on the network; kept for the next run")
    (BASE / "seen.txt").write_text("\n".join(list(seen)[-8000:]))
    save_json(BASE / "meta.json", meta)
    print(f"done: {total} candidates queued")


FILL_ROUNDS = 4   # an emptied pool refills in back-to-back rounds, not hour by hour


def one_round(cfg: dict, force: bool) -> bool:
    """Intake and curation if the pool needs them; True when a curation pass ran."""
    stamp = time.strftime("%F %T")
    have, target = reserve(), int(cfg.get("pool_target", 12))
    backlog, cap = queued_count(), int(cfg.get("max_queue", 30))
    runs, max_runs = curations_today(), int(cfg.get("max_curations_per_day", 8))

    if not force and have >= target and backlog == 0:
        print(f"{stamp} {have} approved wallpapers waiting (target {target}); nothing to do")
        return False
    if not force and runs >= max_runs:
        print(f"{stamp} {runs} curation passes in the last 24 h (max_curations_per_day {max_runs}); "
              f"waiting, with {have} approved wallpapers waiting")
        return False
    if backlog >= cap:
        print(f"{stamp} queue holds {backlog} unjudged candidates "
              f"(max_queue {cap}); intake paused until curation drains it")
    elif force or have < target:
        intake(cfg, want=min(cap - backlog, max(12, (target - have) * 10)))
    sys.stdout.flush()
    if "--no-curate" in sys.argv:
        return False
    subprocess.run(["/bin/bash", str(BASE / "curate.sh")], check=False)
    return True


def main() -> None:
    cfg = load_json(BASE / "config.json", {})
    QUEUE.mkdir(parents=True, exist_ok=True)
    force = "--force" in sys.argv
    target = int(cfg.get("pool_target", 12))
    for i in range(FILL_ROUNDS):
        before = reserve()
        if not one_round(cfg, force and i == 0):
            return
        after = reserve()
        if after >= target or after <= before:   # full, or a round that added nothing
            return
        print(f"{time.strftime('%F %T')} {after} of {target} approved wallpapers waiting; another round")


if __name__ == "__main__":
    main()
