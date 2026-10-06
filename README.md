# awe-some-wallpapers

Awe-inspiring macOS desktop + lock screen wallpapers, curated for you by Claude.

Awe needs two things: vastness, and something that violates your model of the
world. A recommender that only learns what you loved gets very good at the
first and slowly kills the second. This one is built to keep both alive.

## How it works

1. **Intake** (`fetch.py`, launchd 9/15/21h) runs six queries per pass across
   Unsplash, Wikimedia Commons Featured Pictures, The Met, the Art Institute
   of Chicago, and NASA. The queries come from the curator's own plan; the
   first run bootstraps them from a Thompson-sampling bandit over twenty
   registers (night sky, storm, volcanic, ice, art, illustration, science,
   wildlife, interiors, industrial, underwater, …). Every query is ledgered
   and never repeated. No like-count floors — popularity finds postcards.
2. **Learn** (`learn.py`) rebuilds the bandit from your reactions before every
   curation: loves, "interesting", fast skips, mehs, bans, long dwells.
3. **Curate** (`curate.sh` → headless Claude with `CURATOR.md`) views every
   candidate. The bar is *vastness or accommodation, plus craft*. Keeps are
   calibrated to your love distribution with about a third reserved for
   registers with few pulls; it authors captions, can re-crop a detail, writes
   the next six queries (three exploit, two surprise, one orthogonal), programs
   the playlist with a jolt every fourth slot, and keeps `taste.md` under
   twelve bullets.
4. **Rotate** (`rotate.sh`, every 3h) plays the playlist. Nothing is ever
   shown twice; shown images retire to `archive/`.
5. **Apply** (`apply.sh`): on macOS 26 the wallpaper is one stable file in
   `/Users/Shared` that macOS was pointed at once (`wp seed`); rotation swaps
   its contents and restarts WallpaperAgent — the only path that works from
   launchd under Tahoe's sandboxed renderer. Pre-26 Macs use the legacy
   store stamp.
6. **Other Macs** (`publish.py`, `follower/`): the primary Mac is the only one
   that fetches, curates and rotates. It publishes a small read-only feed to
   iCloud Drive: the captioned pool, what it is showing, the playlist, and
   everything ever shown. A follower Mac mirrors the primary's wallpaper and,
   while the primary sleeps, keeps the show moving with images no Mac has
   shown. Its reactions flow back, so the curator learns from every screen
   and nothing repeats anywhere.

## Install

Requires macOS 14+, [Claude Code](https://claude.com/claude-code) on a Claude
subscription, [uv](https://docs.astral.sh/uv/), an Unsplash API key (optional).

```bash
./install.sh
wp auth      # year-long curator token; headless runs never need a login
wp fetch     # first intake + curation
wp seed      # one-time macOS grant (desktop + lock screen)
```

On another Mac signed into the same iCloud account:

```bash
git clone https://github.com/arnavw/awe-some-wallpapers ~/awe-some-wallpapers
cd ~/awe-some-wallpapers && ./install.sh --follower
```

`wp` works there too: reactions, skip, ban, info. Intake and curation stay on
the primary.

## Commands

```
wp / wp skip    next        wp love         moved you
wp interesting  engaged you wp meh          left you cold
wp ban          never again wp info / open  what is this
wp fetch        intake now  wp curate       curate the queue
wp seed         re-grant    wp auth         curator token
wp status       health, pool, queue, bandit
```

State lives in `~/.wallpaper-rotator/` (config, meta, bandit, query ledger,
taste, logs) and `~/Pictures/WorldWallpapers/` (pool, captions, archive).
