#!/usr/bin/python3
"""Curator health: is unattended curation working, and will it keep working?

A projection of two facts:
  * the event store's `curation` events — curate.sh appends one per pass that
    reaches the model, with outcome ok|failed and the CLI's last output line;
  * the age of the long-lived token `wp auth` keeps in the login keychain
    (`claude setup-token` tokens last a year).

    health.py           one warning line when something needs the user, else nothing
    health.py --status  a summary line for `wp status`

Stdlib only; runs on the stock macOS python3. Reads keychain metadata only,
never the token itself.
"""

import calendar
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

BASE = Path.home() / ".wallpaper-rotator"
sys.path.insert(0, str(BASE))

TOKEN_SERVICE = "awe-some-wallpapers.claude-token"  # shared with curate.sh and wp auth
TOKEN_LIFETIME_DAYS = 365
RENEW_WITHIN_DAYS = 30
AUTH_WORDS = re.compile(r"login|log in|auth|token|expired|401|403", re.I)


def failing_streak(events: List[dict]) -> List[dict]:
    """The trailing run of failed curation passes, oldest first; empty if the last pass succeeded."""
    streak = []
    for e in reversed([e for e in events if e.get("type") == "curation"]):
        if e.get("outcome") != "failed":
            break
        streak.append(e)
    return streak[::-1]


def last_pass(events: List[dict]) -> Optional[dict]:
    passes = [e for e in events if e.get("type") == "curation"]
    return passes[-1] if passes else None


def token_stored_at() -> Optional[float]:
    """Epoch seconds when the curator token was last written, or None when none is stored."""
    r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", TOKEN_SERVICE],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = re.search(r'"mdat"<timedate>=\S+\s+"(\d{14})Z', r.stdout + r.stderr)
    return calendar.timegm(time.strptime(m.group(1), "%Y%m%d%H%M%S")) if m else None


def ago(ts: float, now: float) -> str:
    s = max(0, int(now - ts))
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 172800:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def stamp(ts: float) -> str:
    return time.strftime("%b %d %H:%M", time.localtime(ts))


def failure_warning(streak: List[dict]) -> Optional[str]:
    """One line naming when curation started failing, why, and what to do."""
    if not streak:
        return None
    reason = streak[-1].get("reason") or "unknown error"
    fix = "run: wp auth" if AUTH_WORDS.search(reason) else "see ~/Library/Logs/*wallpaper-fetch.log"
    n = len(streak)
    return (f"curation failing since {stamp(streak[0]['ts'])} "
            f"({n} pass{'es' if n != 1 else ''}): {reason} — {fix}")


def token_warning(stored: Optional[float], now: float) -> Optional[str]:
    """A renewal reminder in the token's last month."""
    if stored is None:
        return None
    left = TOKEN_LIFETIME_DAYS - (now - stored) / 86400
    if left > RENEW_WITHIN_DAYS:
        return None
    when = "has expired" if left <= 0 else f"expires in about {int(left)} days"
    return f"curator token {when} — run: wp auth"


def status_line(events: List[dict], stored: Optional[float], now: float) -> str:
    """Summary for `wp status`: last pass, failure streak, token."""
    streak = failing_streak(events)
    last = last_pass(events)
    if streak:
        head = failure_warning(streak)
    elif last:
        head = f"curation: ok, last pass {ago(last['ts'], now)}"
    else:
        head = "curation: no passes recorded yet"
    if stored is None:
        tail = "token: none stored, so curation uses the CLI's own login (wp auth fixes that)"
    else:
        left = int(TOKEN_LIFETIME_DAYS - (now - stored) / 86400)
        tail = f"token: stored {time.strftime('%Y-%m-%d', time.localtime(stored))}, ~{left} days left"
    return f"{head}\n{tail}"


def main() -> None:
    from events import load
    events, stored, now = load(), token_stored_at(), time.time()
    if "--status" in sys.argv:
        print(status_line(events, stored, now))
        return
    for line in (failure_warning(failing_streak(events)), token_warning(stored, now)):
        if line:
            print(f"warning: {line}", file=sys.stderr)


if __name__ == "__main__":
    main()
