#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Render display copies of wallpapers into .display/.

Two treatments:
- Photos: the image full-bleed with a minimal shadowed caption (title +
  credit) in the bottom-right, placed inside the region that survives macOS
  fill-cropping.
- Art (meta kind == "art") in portrait/square aspect: a gallery mat — the
  work centered on a near-black canvas at the screen's aspect ratio with a
  soft drop shadow, like a piece hung on a museum wall.

Caption text comes straight from meta.json; the curation pass authors those
fields deliberately, so no cleanup happens here beyond truncation.

Idempotent: skips images whose display copy already exists.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = Path.home() / ".wallpaper-rotator"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
DISPLAY = IMAGES / ".display"

# Fill-scaling crops the image to the screen's aspect; captions must sit in
# the surviving region. 1.547 = 16" MacBook Pro.
SCREEN_ASPECT = 1.547

TITLE_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
]
BODY_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
]


def load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def visible_box(w: int, h: int) -> tuple:
    """(side, top/bottom) margins removed by fill-scaling to SCREEN_ASPECT."""
    if w / h > SCREEN_ASPECT:
        return (w - h * SCREEN_ASPECT) / 2, 0.0
    return 0.0, (h - w / SCREEN_ASPECT) / 2


def gallery_mat(img: Image.Image) -> Image.Image:
    """Center a portrait/square artwork on a dark museum-wall canvas."""
    cw = 5120
    ch = round(cw / SCREEN_ASPECT)
    scale = min(0.86 * ch / img.height, 0.90 * cw / img.width)
    iw, ih = round(img.width * scale), round(img.height * scale)
    art = img.resize((iw, ih), Image.LANCZOS)

    canvas = Image.new("RGB", (cw, ch), (16, 15, 17))
    x, y = (cw - iw) // 2, (ch - ih) // 2 - round(0.012 * ch)

    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((x, y + 14, x + iw, y + ih + 14), fill=(0, 0, 0, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(38))
    canvas.paste((0, 0, 0), (0, 0), shadow.split()[3])
    canvas.paste(art, (x, y))
    return canvas


def draw_caption(img: Image.Image, meta: dict) -> Image.Image:
    """Minimal shadowed caption, right-aligned in the bottom-right safe area."""
    w, h = img.size
    s = w / 3840
    title = truncate(meta.get("title") or "", 48)
    credit = truncate(meta.get("credit", ""), 36)
    rows = [(t, f, a) for t, f, a in (
        (title, load_font(TITLE_FONTS, round(38 * s)), 230),
        (credit, load_font(BODY_FONTS, round(28 * s)), 175),
    ) if t]
    if not rows:
        return img

    measure = ImageDraw.Draw(img)
    sizes = [measure.textbbox((0, 0), t, font=f) for t, f, _ in rows]
    gap = round(10 * s)
    text_h = sum(b[3] - b[1] for b in sizes) + gap * (len(rows) - 1)

    crop_x, crop_y = visible_box(w, h)
    right = round(w - crop_x - 130 * s)
    ty = round(h - crop_y - 200 * s) - text_h

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer)
    for (text, font, alpha), bbox in zip(rows, sizes):
        row_w = bbox[2] - bbox[0]
        ldraw.text((right - row_w - bbox[0], ty - bbox[1]), text, font=font, fill=(255, 255, 255, alpha))
        ty += (bbox[3] - bbox[1]) + gap
    shadow = layer.split()[3].filter(ImageFilter.GaussianBlur(6 * s))
    img.paste((0, 0, 0), (round(2 * s), round(3 * s)), shadow.point(lambda a: a * 0.55))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def compose(src: Path, dest: Path, meta: dict) -> None:
    img = Image.open(src).convert("RGB")
    if meta.get("kind") == "art" and img.width / img.height < 1.35:
        img = gallery_mat(img)
    img = draw_caption(img, meta)
    dest.parent.mkdir(exist_ok=True)
    img.save(dest, quality=93, subsampling=0)


def main() -> None:
    with open(BASE / "meta.json") as f:
        meta = json.load(f)
    done = skipped = 0
    for src in sorted(IMAGES.glob("*.[jp]*g")):
        dest = DISPLAY / src.name
        if dest.exists():
            continue
        if src.name not in meta:
            skipped += 1
            continue
        compose(src, dest, meta[src.name])
        done += 1
    for orphan in DISPLAY.glob("*.[jp]*g"):
        if not (IMAGES / orphan.name).exists():
            orphan.unlink()
    print(f"composed {done}, skipped {skipped} (no metadata)")


if __name__ == "__main__":
    main()
