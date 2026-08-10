#!/bin/bash
# Run a headless Claude (Fable 5) curation pass over the wallpaper queue,
# then compose captions for whatever was promoted. Chained by fetch.py after
# each daily fetch; also runnable manually via `wp curate`.

set -euo pipefail
BASE="$HOME/.wallpaper-rotator"

shopt -s nullglob
queued=("$BASE/queue/"*.jpg "$BASE/queue/"*.png)
if [[ ${#queued[@]} -eq 0 ]]; then
  echo "$(date '+%F %T') queue empty; nothing to curate"
  exit 0
fi

CLAUDE=$(command -v claude || echo "$HOME/.local/bin/claude")
echo "$(date '+%F %T') curating ${#queued[@]} queued images"
"$CLAUDE" -p "$(cat "$BASE/CURATOR.md")" \
  --model claude-fable-5 \
  --allowedTools "Read,Glob,Write,Edit,Bash(/usr/bin/python3:*),Bash($HOME/.wallpaper-rotator/refine.py:*),Bash(uv run:*)" \
  2>&1

# Compose captions for promoted images regardless of how the session ended.
UV="$HOME/.local/bin/uv"; command -v uv >/dev/null && UV=$(command -v uv)
"$UV" run --script "$BASE/compose.py"
echo "$(date '+%F %T') curation pass done"
