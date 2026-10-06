#!/bin/bash
# Curation pass: rebuild the bandit from reactions, run the headless curator
# over the queue, render captions for promotions, publish state. Chained by
# fetch.py after every intake; also `wp curate`.
#
# Auth. Headless runs use the long-lived token `wp auth` keeps in the login
# keychain. CLAUDE_CODE_OAUTH_TOKEN in the curator's environment outranks every other credential
# the CLI can find (its own claude.ai login, shared ~/.config/anthropic
# profiles), so an interactive login, logout or expired profile can no longer
# stall curation. With no token stored, the CLI falls back to its own login.
#
# Health. Every pass that reaches the curator appends a `curation` event
# (outcome ok|failed, reason). `wp` reads them through health.py to warn while
# curation is failing, and a failed pass raises a macOS notification at most
# once a day, so a broken curator cannot go unnoticed for days.
set -euo pipefail
BASE="$HOME/.wallpaper-rotator"
TOKEN_SERVICE="awe-some-wallpapers.claude-token"   # shared with wp auth and health.py

# cfg KEY DEFAULT — one value from config.json
cfg() {
  /usr/bin/python3 -I -c "import json,sys;print(json.load(open('$BASE/config.json')).get(sys.argv[1],sys.argv[2]))" "$1" "$2"
}

# record OUTCOME [REASON] — append a curation health event
record() {
  /usr/bin/python3 -I "$BASE/events.py" append curation "outcome=$1" "reason=${2:-}" >/dev/null
}

# alert REASON — notify on failure, at most once a day
alert() {
  local stamp="$BASE/.last-curation-alert"
  if [[ -f "$stamp" ]] && (( $(date +%s) - $(/usr/bin/stat -f %m "$stamp") < 86400 )); then
    return
  fi
  touch "$stamp"
  /usr/bin/osascript \
    -e 'on run argv' \
    -e 'display notification (item 1 of argv) with title "Wallpaper curation failed" subtitle "wp status for details"' \
    -e 'end run' "$1" || echo "$(date '+%F %T') could not raise the failure notification"
}

/usr/bin/python3 -I "$BASE/learn.py" --quiet

shopt -s nullglob
queued=("$BASE/queue/"*.jpg "$BASE/queue/"*.png)
if [[ ${#queued[@]} -eq 0 ]]; then
  echo "$(date '+%F %T') queue empty; nothing to curate"
  exit 0
fi

# The curator gets the same minimal environment whether launchd or a terminal
# started this pass: variables a terminal can carry (ANTHROPIC_BASE_URL,
# ANTHROPIC_API_KEY, CLAUDECODE, ...) would change which endpoint and identity
# the CLI uses. wp auth tests tokens in this same environment.
curator_env=(env -i HOME="$HOME" USER="$(id -un)" LOGNAME="$(id -un)" SHELL="${SHELL:-/bin/zsh}"
             PATH="/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin" TMPDIR="${TMPDIR:-/tmp/}")
if token=$(/usr/bin/security find-generic-password -s "$TOKEN_SERVICE" -w 2>/dev/null); then
  curator_env+=("CLAUDE_CODE_OAUTH_TOKEN=$token")
  auth="stored token"
else
  rc=$?
  # 44 = no such item: wp auth has not been run, so the CLI's own login is used.
  (( rc == 44 )) || echo "$(date '+%F %T') keychain read failed (security exit $rc); using the CLI's own login"
  auth="CLI login"
fi
unset token

CLAUDE=$(command -v claude || echo "$HOME/.local/bin/claude")
MODEL=$(cfg curator_model claude-opus-5-5)
# Opus 5.5 defaults to medium effort; visual judgment wants more, so set it explicitly.
EFFORT=$(cfg curator_effort xhigh)
echo "$(date '+%F %T') curating ${#queued[@]} queued images with $MODEL (effort $EFFORT, $auth)"

# System binaries by path: wp curate runs from a shell where GNU tools may come first.
transcript=$(/usr/bin/mktemp -t curate)
trap 'rm -f "$transcript"' EXIT
set +e
"${curator_env[@]}" "$CLAUDE" -p "$(cat "$BASE/CURATOR.md")" \
  --model "$MODEL" \
  --effort "$EFFORT" \
  --allowedTools "Read,Glob,Write,Edit,Bash(/usr/bin/python3:*)" \
  2>&1 | tee "$transcript"
status=${PIPESTATUS[0]}
set -e

if (( status != 0 )); then
  reason=$(/usr/bin/grep -v '^[[:space:]]*$' "$transcript" | /usr/bin/tail -1 | /usr/bin/cut -c1-240)
  reason=${reason:-"claude exited $status with no output"}
  echo "$(date '+%F %T') curation FAILED (exit $status): $reason"
  record failed "$reason"
  alert "$reason"
  exit "$status"
fi
record ok

UV=$(command -v uv || echo "$HOME/.local/bin/uv")
"$UV" run --script "$BASE/compose.py" || true
/usr/bin/python3 -I "$BASE/publish.py" push || echo "$(date '+%F %T') feed publish failed; followers catch up on the next one"

# A rotation tick that found nothing fresh is still owed. If the wallpaper has
# been up longer than the rotation interval (install.sh's StartInterval), use
# what this pass promoted now rather than at the next tick.
ROTATE_INTERVAL=10800
if [[ -f "$BASE/current.txt" ]] &&
   (( $(date +%s) - $(/usr/bin/stat -f %m "$BASE/current.txt") >= ROTATE_INTERVAL )); then
  echo "$(date '+%F %T') wallpaper overdue; rotating now"
  bash "$BASE/rotate.sh" || echo "$(date '+%F %T') overdue rotation failed; the next tick retries"
fi
echo "$(date '+%F %T') curation pass done"
