#!/usr/bin/python3
"""Pick the next wallpaper, and name the pool images that are spent.

Never-repeat (the owner's rule): an image shown on any Mac is never shown
again. "Shown" means a `shown` event in any machine's event stream; follower
Macs' streams are pulled into ~/.wallpaper-rotator/ by publish.py before
rotate.sh calls this.

  next_image.py [current]       print the next image's path, or nothing when no
                                fresh image exists (the current one stays up);
                                consumes the playlist up to the pick
  next_image.py --retire KEEP   print "archive NAME" or "delete NAME" for every
                                pool image already shown somewhere, except KEEP;
                                images someone banned are deleted, the rest go
                                to the keeper archive
  --dry                         leave the playlist untouched

Selection: the first playlist entry that is in the pool with its captioned
copy ready, is not current and was never shown; otherwise a random fresh,
ready pool image.
"""

import random
import sys
from pathlib import Path

BASE = Path.home() / ".wallpaper-rotator"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
PLAYLIST = BASE / "playlist.txt"
sys.path.insert(0, str(BASE))


def history() -> tuple:
    """(shown, banned): image names shown on any Mac, and those someone banned."""
    from events import load
    shown, banned = set(), set()
    for e in load():
        if e.get("type") == "shown":
            shown.add(e.get("image"))
        elif e.get("type") == "reaction" and e.get("cmd") == "ban":
            banned.add(e.get("image"))
    return shown, banned


def pool() -> list:
    return sorted(p.name for p in IMAGES.iterdir() if p.suffix.lower() in (".jpg", ".png"))


def pick(current: str, shown: set, dry: bool) -> str:
    """The next fresh image name ("" if none); consumes the playlist prefix.

    Only images whose captioned copy exists are ready: a tick that lands while
    a curation pass is still composing waits rather than showing a bare image.
    """
    lines = PLAYLIST.read_text().split() if PLAYLIST.exists() else []
    in_pool = {name for name in pool() if (IMAGES / ".display" / name).exists()}
    for i, cand in enumerate(lines):
        if cand != current and cand not in shown and cand in in_pool:
            if not dry:
                rest = lines[i + 1:]
                PLAYLIST.write_text("\n".join(rest) + ("\n" if rest else ""))
            return cand
    fresh = [p for p in in_pool if p != current and p not in shown]
    return random.choice(fresh) if fresh else ""


def retire(keep: str, shown: set, banned: set) -> list:
    """(action, name) for each spent pool image other than keep."""
    return [("delete" if name in banned else "archive", name)
            for name in pool() if name in shown and name != keep]


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--dry"]
    shown, banned = history()
    if args[:1] == ["--retire"]:
        keep = Path(args[1]).name if len(args) > 1 else ""
        for action, name in retire(keep, shown, banned):
            print(action, name)
        return
    current = Path(args[0]).name if args else ""
    name = pick(current, shown, "--dry" in sys.argv)
    if name:
        print(IMAGES / name)


if __name__ == "__main__":
    main()
