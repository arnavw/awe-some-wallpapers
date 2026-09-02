#!/bin/bash
# Curation pass: rebuild the bandit from reactions, run the headless curator
# over the queue, render captions for promotions, publish state. Chained by
# fetch.py after every intake; also `wp curate`.
set -euo pipefail
BASE="$HOME/.wallpaper-rotator"

/usr/bin/python3 "$BASE/learn.py" --quiet

shopt -s nullglob
queued=("$BASE/queue/"*.jpg "$BASE/queue/"*.png)
if [[ ${#queued[@]} -eq 0 ]]; then
  echo "$(date '+%F %T') queue empty; nothing to curate"
  exit 0
fi

CLAUDE=$(command -v claude || echo "$HOME/.local/bin/claude")
MODEL=$(/usr/bin/python3 -c "import json;print(json.load(open('$BASE/config.json')).get('curator_model','claude-fable-5'))")
echo "$(date '+%F %T') curating ${#queued[@]} queued images with $MODEL"
"$CLAUDE" -p "$(cat "$BASE/CURATOR.md")" \
  --model "$MODEL" \
  --allowedTools "Read,Glob,Write,Edit,Bash(/usr/bin/python3:*)" \
  2>&1

UV=$(command -v uv || echo "$HOME/.local/bin/uv")
"$UV" run --script "$BASE/compose.py" || true
bash "$BASE/publish.sh" || true
echo "$(date '+%F %T') curation pass done"
