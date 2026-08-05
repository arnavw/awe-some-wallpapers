#!/bin/bash
# Print info about the wallpaper currently showing; `info.sh open` opens its
# source page (Unsplash / Wikimedia Commons) in the browser.

set -euo pipefail
name=$(basename "$(cat "$HOME/.wallpaper-rotator/current.txt")")
entry=$(/usr/bin/python3 -c "
import json, sys
meta = json.load(open('$HOME/.wallpaper-rotator/meta.json'))
e = meta.get('$name')
print(json.dumps(e) if e else '')
")
if [[ -z "$entry" ]]; then
  echo "current: $name (no metadata)"
  exit 0
fi
echo "$entry" | /usr/bin/python3 -c "
import json, sys
e = json.load(sys.stdin)
print(f\"{e['title']}\n{e['credit']} — {e['source']}\n{e['url']}\")
"
if [[ "${1:-}" == "open" ]]; then
  open "$(echo "$entry" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"
fi
