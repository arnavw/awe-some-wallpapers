# awe-some-wallpapers

Awe-inspiring macOS desktop + lock screen wallpapers, curated for you by Claude.

Awe needs two things: vastness, and something that violates your model of the
world. A recommender that only learns what you loved gets very good at the
first and slowly kills the second. This one is built to keep both alive.

## How it works

1. **Intake** (`fetch.py`, checked hourly) keeps about a dozen approved
   wallpapers waiting: whenever the reserve runs low it runs six queries across
   photography (Unsplash, Flickr, Wikimedia Commons Featured and Quality
   images), the ESA/Webb, ESA/Hubble, ESO and NOIRLab archives, NASA's
   Photojournal, Earth Observatory, ISS astronaut photography and image
   library, Copernicus Image of the Day, and open-access art (the National Gallery of Art, Cleveland, SMK,
   The Met, the Art Institute of Chicago, Commons). The queries come from the curator's own plan; the
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
4. **Rotate** (`rotate.sh`) plays the playlist after each image has had two
   hours of screen time: time counts only while the Mac is awake, unlocked and
   in use (`screentime.py`, ticked every five minutes), so an image put up just
   before the lid closed is still there when it opens. Nothing is ever shown
   twice; shown images retire to `archive/`.
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
subscription, [uv](https://docs.astral.sh/uv/). API keys are optional and stored with
`wp key unsplash|iss|flickr`: [Unsplash](https://unsplash.com/developers), the
[ISS photo database](https://eol.jsc.nasa.gov/SearchPhotos/PhotosDatabaseAPI/) (free, by email) and
[Flickr](https://www.flickr.com/services/apps/create/) (free, non-commercial). Each source
without a key sits out.

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

## iPad

The iPad mirrors the primary. Whenever the primary's wallpaper changes, it
leaves one square, captioned copy in `AweSomeWallpapers/feed/ipad/`; two
small shortcuts on the iPad put it up and send reactions back. Build them on
the iPad, since the wallpaper action targets a wallpaper on that device.

Once: make a photo wallpaper (Settings › Wallpaper › Add New Wallpaper ›
Photos, any photo, set as a pair) and keep it active; in its editor turn off
Perspective Zoom and spatial scene, and give the Home Screen the original
photo, not the blur. In Files, long-press `AweSomeWallpapers › feed` and
choose Keep Downloaded.

**Sync wallpaper**

1. Get Contents of Folder: `AweSomeWallpapers › feed › ipad`
2. If: Contents of Folder has any value
3. Set Wallpaper Photo: Contents of Folder. Wallpaper: the photo wallpaper
   above. Lock Screen and Home Screen. Show Preview, Crop to Subject and
   Legibility Blur off.
4. Append to Text File: `Current Date applied Name` (Current Date formatted
   ISO 8601 with time; Name is Contents of Folder › Name) to
   `AweSomeWallpapers › feed › ipad-log.txt`, Make New Line on
5. Move File: Contents of Folder to `AweSomeWallpapers › feed › ipad-done`
6. End If

Run it once by hand and answer every prompt with Always Allow. Then trigger
it every hour or two (one Time of Day trigger per hour) and when the charger
connects, with Allow Running When Locked on. The Mac rotates on its own screen
time, not on the clock, so a run simply picks up whatever it has put up since.

**Love wallpaper**: one action, Append to Text File: `Current Date love` to
`AweSomeWallpapers › feed › reactions.ipad.txt`, Make New Line on. Put it in
a Home Screen widget or Control Center. Copies with `interesting`, `meh` or
`ban` instead of `love` work the same way.

`wp status` on the primary shows what the iPad last applied and when.

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
