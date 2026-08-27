#!/usr/bin/python3
"""Legacy wallpaper setter for macOS 15 (Sequoia) and earlier — stamps every
Space/display entry of the wallpaper store (~/Library/Application Support/
com.apple.wallpaper/Store/Index.plist) and restarts WallpaperAgent, which is
the only path that covers all Spaces plus the lock screen on those systems.

On macOS 26+ (Tahoe) this file is NOT used: the sandboxed renderer ignores
ungranted store paths, so apply.sh swaps the contents of a single
Settings-granted file instead. apply.sh dispatches by OS version.

Usage: set_wallpaper.py /path/to/image.jpg
"""

import base64
import os
import plistlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

STORE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.apple.wallpaper"
    / "Store"
    / "Index.plist"
)

# {backgroundColor, placement: 1} — the standard image-choice Configuration
# blob captured from a System Settings-written store; it is image-independent
# on pre-26 systems.
FALLBACK_CONFIG = base64.b64decode(
    "YnBsaXN0MDDSAQIDDF8QD2JhY2tncm91bmRDb2xvcllwbGFjZW1lbnTSBAUGC1pjb21wb25l"
    "bnRzWmNvbG9yU3BhY2WkBwgJCiM/0FBQUFBQUCM/2lpaWlpaWiM/5VVVVVVVVSM/8AAAAAAA"
    "AE8QQ2JwbGlzdDAwXxAXa0NHQ29sb3JTcGFjZUdlbmVyaWNSR0IIAAAAAAAAAQEAAAAAAAAA"
    "AQAAAAAAAAAAAAAAAAAAACIQAQgNHykuOURJUltkbbMAAAAAAAABAQAAAAAAAAANAAAAAAAA"
    "AAAAAAAAAAAAtQ=="
)


def find_existing_config(node) -> Optional[bytes]:
    """Reuse the Configuration blob from any existing image choice in the store."""
    if isinstance(node, dict):
        if node.get("Provider") == "com.apple.wallpaper.choice.image":
            blob = node.get("Configuration")
            if blob:
                return bytes(blob)
        for v in node.values():
            found = find_existing_config(v)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            found = find_existing_config(v)
            if found:
                return found
    return None


def update_desktops(node, choice: dict, now: datetime) -> int:
    """Recursively replace every Desktop/Linked content choice in the store.
    Returns the number of entries updated."""
    count = 0
    if isinstance(node, dict):
        for entry_key in ("Desktop", "Linked"):
            entry = node.get(entry_key)
            if isinstance(entry, dict) and "Content" in entry:
                entry["Content"]["Choices"] = [dict(choice)]
                entry["LastSet"] = now
                entry["LastUse"] = now
                count += 1
        for key, v in node.items():
            if key not in ("Desktop", "Linked"):
                count += update_desktops(v, choice, now)
    elif isinstance(node, list):
        for v in node:
            count += update_desktops(v, choice, now)
    return count


def main() -> None:
    image = Path(sys.argv[1]).resolve()
    if not image.is_file():
        sys.exit(f"no such image: {image}")

    with open(STORE, "rb") as f:
        store = plistlib.load(f)

    config = find_existing_config(store) or FALLBACK_CONFIG
    choice = {
        "Provider": "com.apple.wallpaper.choice.image",
        "Files": [{"relative": image.as_uri()}],
        "Configuration": config,
    }
    # plistlib requires naive datetimes (interpreted as UTC); this form avoids
    # the Python 3.12+ utcnow() deprecation while staying 3.9-compatible.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    updated = update_desktops(store, choice, now)
    if updated == 0:
        sys.exit("no Desktop entries found in wallpaper store; aborting")

    # Write atomically: serialize fully to a temp file, then rename over the
    # store, so a crash mid-write can never leave a corrupt Index.plist.
    tmp = STORE.with_suffix(".plist.tmp")
    with open(tmp, "wb") as f:
        plistlib.dump(store, f, fmt=plistlib.FMT_BINARY)
    os.replace(tmp, STORE)

    subprocess.run(["/usr/bin/killall", "WallpaperAgent"], check=False)
    print(f"updated {updated} desktop entries -> {image.name}")


if __name__ == "__main__":
    main()
