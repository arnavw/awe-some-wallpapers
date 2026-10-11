#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Curation helper: re-frame a queued image to a detail crop.

Usage: refine.py <filename> <x0> <y0> <x1> <y1>
Coordinates are FRACTIONS of image width/height (0.0-1.0) describing the
region of interest. The crop is expanded to the screen aspect ratio around
that region and written back over the queued original — so a stunning detail
inside a merely good image can become the wallpaper (e.g. the Creation of
Adam fingers). A crop narrower than MIN_WIDTH is refused, never upscaled: a
detail is worth keeping only if the source resolves it at screen size.
"""

import sys
from pathlib import Path

from PIL import Image

SCREEN_ASPECT = 1.547
MIN_WIDTH = 3840
QUEUE = Path.home() / ".wallpaper-rotator" / "queue"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"

name = Path(sys.argv[1]).name
fx0, fy0, fx1, fy1 = (float(v) for v in sys.argv[2:6])
src = QUEUE / name if (QUEUE / name).exists() else IMAGES / name
img = Image.open(src).convert("RGB")
w, h = img.size

cx, cy = (fx0 + fx1) / 2 * w, (fy0 + fy1) / 2 * h
cw, ch = (fx1 - fx0) * w, (fy1 - fy0) * h
# Expand the requested region to screen aspect.
if cw / ch < SCREEN_ASPECT:
    cw = ch * SCREEN_ASPECT
else:
    ch = cw / SCREEN_ASPECT
# Clamp to the image bounds, preserving aspect by shrinking if needed.
scale = min(1.0, w / cw, h / ch)
cw, ch = cw * scale, ch * scale
x0 = max(0, min(w - cw, cx - cw / 2))
y0 = max(0, min(h - ch, cy - ch / 2))

if round(cw) < MIN_WIDTH:
    sys.exit(f"refused: at screen shape that region is {round(cw)} px wide, under {MIN_WIDTH}; "
             f"widen it or judge the full frame. {name} is unchanged.")
crop = img.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))
crop.save(src, quality=95, subsampling=0)
print(f"refined {name}: {crop.width}x{crop.height} crop at ({fx0},{fy0})-({fx1},{fy1})")
