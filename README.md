# awe-some-wallpapers

Rotating macOS desktop + lock screen wallpapers, curated by Claude's eyes.

The pipeline fetches candidate images daily (Unsplash by topic with a
like-count floor; Wikimedia Commons Featured Pictures as keyless fallback;
Commons museum scans for fine art), quarantines them in a queue, and then a
**headless Claude Code session looks at every image** and decides — against a
written, evolving taste profile — what deserves your screen. Roughly the top
15% survives. Captions (title + credit, bottom-right, baked into a display
copy) are authored by the curator, never raw API text.

## Requirements

- macOS Sonoma/Sequoia (wallpaper store format)
- [Claude Code](https://claude.com/claude-code) CLI, signed in
- [uv](https://docs.astral.sh/uv/) (for Pillow-based composition)
- Optional: a free Unsplash API access key

## Install

```bash
./install.sh
```

Then put your Unsplash key in `~/.wallpaper-rotator/config.json`, check
`SCREEN_ASPECT` in `compose.py`/`refine.py` (1.547 = 16" MacBook Pro), and run
`wp fetch`.

## Daily loop

1. **9:00** — `fetch.py` cycles 6 topics from the config's ~80-topic world
   tour (nature, architecture, cities, fine art), downloads high-res
   candidates (native ≥3840px for photos) into the queue.
2. **fetch chains `curate.sh`** — Claude reviews every queued image visually
   (CURATOR.md is its charter, TASTE.md its rubric), may re-frame an image to
   a stronger detail crop (`refine.py`), promotes winners with an authored
   caption, rejects the rest with written reasons (`curation_log.jsonl`).
3. **Every 3 hours** — `rotate.sh` pops the next image from the curator's
   sequenced `playlist.txt` (exposure history + your reactions decide the
   order; random only as fallback) and writes it into every Space/display
   entry of the macOS wallpaper store (the only reliable way;
   NSWorkspace/AppleScript only touch the active Space). The lock screen
   mirrors it automatically.

## Commands

```
wp          next wallpaper (aliases: skip, n)
wp love     strong positive signal — teaches the curator
wp meh      soft negative signal (image stays)
wp ban      delete current image forever, skip ahead
wp info     place / photographer / source link
wp open     open the photo's source page
wp curate   run a curation pass now
wp fetch    fetch fresh candidates now (then auto-curates)
```

Every command is logged with the image it acted on and its on-screen dwell
time; each curation run distills patterns from that log into dated,
evidence-cited entries in TASTE.md. The profile is the product — after a few
weeks it's genuinely yours.

## Layout

```
rotator/           the system (installed to ~/.wallpaper-rotator)
  fetch.py         topic cycle + Unsplash/Commons/art fetchers
  curate.sh        headless Claude curation harness
  CURATOR.md       the curator's charter (judgment, refining, captions)
  TASTE.seed.md    starting taste profile (becomes ~/.wallpaper-rotator/TASTE.md)
  compose.py       caption + gallery-mat rendering (art gets a museum wall)
  refine.py        detail-crop tool (fractional coords, aspect-aware)
  rotate.sh        wallpaper-store rotation across all Spaces
  set_wallpaper.py the store writer (atomic, all Spaces/displays)
  promote.py / reject.py   curation actions, audit-logged
bin/wp             the control command
install.sh         idempotent installer (launchd agents included)
```

State lives in `~/.wallpaper-rotator/` (config, meta, logs, taste profile);
images in `~/Pictures/WorldWallpapers/` (originals + `.display/` captioned
copies). Nothing phones home; everything is inspectable text.
