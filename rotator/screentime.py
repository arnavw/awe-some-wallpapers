#!/usr/bin/python3
"""Screen time: how long the wallpaper on this Mac has been in front of the user.

The show moves on after ROTATE_S of seen time, not of clock time, so an image
put up minutes before the lid closed is still there when it opens. Time counts
while the Mac is awake, its screen is unlocked, and it has had keyboard or
pointer input within IDLE_LIMIT_S. Input matters because a held power
assertion (caffeinate, a video call) keeps the display lit with nobody there.

A launchd tick samples that every five minutes and credits the time since the
previous tick, capped at TICK_CAP_S and never reaching back past the last
wake, so sleep never counts. The clock belongs to one image and starts over
when the image changes, however it changed (a rotation, wp skip, a ban).

Both programs keep a clock: the primary Mac in ~/.wallpaper-rotator/clock.json,
a follower Mac in ~/.wallpaper-follower/clock.json.

  screentime.py tick <clock.json> <image>   credit a tick; prints "due" when the image should move on
  screentime.py due <clock.json> <image>    prints "due" when <image> has had its full turn
  screentime.py seen <clock.json> <image>   seconds <image> has been seen, as of now
  screentime.py status <clock.json> <image> one line for wp status

Stdlib only, for the stock python3 that launchd runs.
"""

import json
import os
import plistlib
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path

ROTATE_S = 2 * 3600       # seen time an image gets before the show moves on
IDLE_LIMIT_S = 10 * 60    # input more recent than this means someone is at the Mac
TICK_CAP_S = 10 * 60      # the most one tick credits; ticks run every five minutes
RETRY_S = 30 * 60         # how often a due move that found nothing fresh is retried


# ----------------------------------------------------------------- clock ----

def credited(clock: dict, image: str, now: float, woke: float, here: bool) -> dict:
    """The clock after one tick.

    A clock for another image starts over at zero. Otherwise, when someone is
    here, it gains the time since the previous tick, capped at TICK_CAP_S and
    at the time since the Mac last woke.
    """
    if clock.get("image") != image:
        return {"image": image, "seen_s": 0.0, "last_tick": now}
    gain = min(now - clock.get("last_tick", now), now - woke, TICK_CAP_S) if here else 0.0
    return {**clock, "seen_s": clock.get("seen_s", 0.0) + max(0.0, gain), "last_tick": now}


def due(clock: dict, now: float, after: float = ROTATE_S) -> bool:
    """Seen for `after` seconds, and not tried within RETRY_S (a held move retries slowly)."""
    return clock.get("seen_s", 0.0) >= after and now - clock.get("tried_at", 0.0) >= RETRY_S


def describe(seen_s: float) -> str:
    """'47m of 3h' style progress toward ROTATE_S."""
    minutes = int(seen_s // 60)
    shown = f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"
    return f"{shown} of {ROTATE_S // 3600}h"


# --------------------------------------------------------------- signals ----

def idle_seconds() -> float:
    """Seconds since the last keyboard, pointer or touch input."""
    out = subprocess.run(["/usr/sbin/ioreg", "-c", "IOHIDSystem", "-d", "4"],
                         capture_output=True, text=True, check=True).stdout
    found = re.search(r'"HIDIdleTime" = (\d+)', out)
    if not found:
        raise RuntimeError("ioreg reported no HIDIdleTime")
    return int(found.group(1)) / 1e9


def screen_locked() -> bool:
    """True when this user's session is locked or not on the console (fast user switching)."""
    out = subprocess.run(["/usr/sbin/ioreg", "-n", "Root", "-d1", "-a"], capture_output=True, check=True).stdout
    me = pwd.getpwuid(os.getuid()).pw_name
    for user in plistlib.loads(out).get("IOConsoleUsers", []):
        if user.get("kCGSSessionUserNameKey") == me:
            return bool(user.get("CGSSessionScreenIsLocked")) or not user.get("kCGSSessionOnConsoleKey", False)
    return True   # not logged in at the console: nobody sees this Mac's wallpaper


def wake_time() -> float:
    """Epoch seconds of the last wake from sleep (0 when the Mac has not slept since boot)."""
    out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.waketime"], capture_output=True, text=True, check=True).stdout
    found = re.search(r"sec = (\d+)", out)
    return float(found.group(1)) if found else 0.0


def someone_here() -> bool:
    return not screen_locked() and idle_seconds() < IDLE_LIMIT_S


# ------------------------------------------------------------------ state ----

def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def save(path: Path, clock: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(clock))
    os.replace(tmp, path)


def tick(path: Path, image: str, after: float = ROTATE_S) -> dict:
    """Credit one tick to image's clock and save it. When the image is due,
    the returned clock has due=True and the attempt is recorded, so a move that
    finds nothing fresh is retried every RETRY_S rather than every tick."""
    now = time.time()
    clock = credited(load(path), image, now, wake_time(), someone_here())
    is_due = due(clock, now, after)
    if is_due:
        clock["tried_at"] = now
    save(path, clock)
    return {**clock, "due": is_due}


def seen(path: Path, image: str) -> float:
    """Seconds image has been seen, including the tick in progress; nothing is saved."""
    now = time.time()
    return credited(load(path), image, now, wake_time(), someone_here())["seen_s"]


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in ("tick", "due", "seen", "status"):
        print(__doc__)
        sys.exit(64)
    cmd, path, image = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]).name
    if cmd == "tick":
        if tick(path, image)["due"]:
            print("due")
    elif cmd == "due":   # no retry throttle: curation calls this right after promoting
        if seen(path, image) >= ROTATE_S:
            print("due")
    elif cmd == "seen":
        print(int(seen(path, image)))
    else:
        print(f"on screen: {describe(seen(path, image))} seen (counts while unlocked and in use)")


if __name__ == "__main__":
    main()
