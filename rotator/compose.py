#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Render captioned copies of wallpapers: .display/ for Macs, .ipad/ for the iPad.

Mac treatments (.display/):
- Photos: the image full-bleed with a minimal shadowed caption (title +
  credit) in the bottom-right, placed inside the region that survives macOS
  fill-cropping.
- Art (meta kind == "art") in portrait/square aspect: a gallery mat — the
  work centered on a near-black canvas at the screen's aspect ratio with a
  soft drop shadow, like a piece hung on a museum wall.

iPad treatment (.ipad/): one square file. iPadOS fits a photo to portrait and
landscape alike, so only the centred square whose side is the screen's short
edge shows in both. The square is IPAD_SIDE px (the 13" panel's long edge) and
the caption sits at the bottom-right of the region the 11" and 13" iPad Pro
both show in both orientations; artworks are matted inside that region.

Caption text comes straight from meta.json; the curation pass authors those
fields deliberately, so no cleanup happens here beyond truncation.

Idempotent: skips images whose copies already exist.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = Path.home() / ".wallpaper-rotator"
IMAGES = Path.home() / "Pictures" / "WorldWallpapers"
DISPLAY = IMAGES / ".display"
IPAD = IMAGES / ".ipad"

# Fill-scaling crops the image to the screen's aspect; captions must sit in
# the surviving region. 1.547 = 16" MacBook Pro.
SCREEN_ASPECT = 1.547

# iPad Pro M4/M5: 13" 2752x2064, 11" 2420x1668. Scaled to cover the long edge,
# a 2752 px square shows its centre 2064 px (13") or 1897 px (11") in both
# orientations, so the region every size and orientation shows is 428..2324.
IPAD_SIDE = 2752
IPAD_SAFE = (428, 2324)

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


def center_crop_to_screen(img: Image.Image) -> Image.Image:
    """Fill treatment for unbounded imagery (nebulae, aerial abstracts):
    center-crop to screen aspect instead of matting."""
    w, h = img.size
    if w / h < SCREEN_ASPECT:
        ch = w / SCREEN_ASPECT
        box = (0, (h - ch) / 2, w, (h + ch) / 2)
    else:
        cw = h * SCREEN_ASPECT
        box = ((w - cw) / 2, 0, (w + cw) / 2, h)
    img = img.crop(tuple(round(v) for v in box))
    if img.width < 3840:
        img = img.resize((3840, round(3840 / SCREEN_ASPECT)), Image.LANCZOS)
    return img


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


def draw_caption(img: Image.Image, meta: dict, corner=None, s=None) -> Image.Image:
    """Minimal shadowed caption, right-aligned above a bottom-right corner.

    corner is the (right, bottom) point the text block hangs from; by default
    the bottom-right of the region a Mac shows, inset. s scales type and insets.
    """
    w, h = img.size
    s = s if s is not None else w / 3840
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

    if corner is None:
        crop_x, crop_y = visible_box(w, h)
        corner = (round(w - crop_x - 130 * s), round(h - crop_y - 200 * s))
    right = corner[0]
    ty = corner[1] - text_h

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(layer)
    for (text, font, alpha), bbox in zip(rows, sizes):
        row_w = bbox[2] - bbox[0]
        ldraw.text((right - row_w - bbox[0], ty - bbox[1]), text, font=font, fill=(255, 255, 255, alpha))
        ty += (bbox[3] - bbox[1]) + gap
    shadow = layer.split()[3].filter(ImageFilter.GaussianBlur(6 * s))
    img.paste((0, 0, 0), (round(2 * s), round(3 * s)), shadow.point(lambda a: a * 0.55))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def ipad_square(img: Image.Image, meta: dict) -> Image.Image:
    """The image as an IPAD_SIDE square: photos centre-cropped, bounded art
    matted inside the both-orientations region with room left for the caption."""
    side = IPAD_SIDE
    if meta.get("kind") == "art" and img.width / img.height < 1.35 and meta.get("treatment") != "fill":
        lo, hi = IPAD_SAFE
        span = hi - lo
        scale = min(0.74 * span / img.height, 0.86 * span / img.width)
        iw, ih = round(img.width * scale), round(img.height * scale)
        canvas = Image.new("RGB", (side, side), (16, 15, 17))
        x, y = (side - iw) // 2, lo + round(0.05 * span)
        shadow = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle((x, y + 10, x + iw, y + ih + 10), fill=(0, 0, 0, 130))
        canvas.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(28)).split()[3])
        canvas.paste(img.resize((iw, ih), Image.LANCZOS), (x, y))
        return canvas
    edge = min(img.size)
    box = ((img.width - edge) // 2, (img.height - edge) // 2)
    return img.crop((*box, box[0] + edge, box[1] + edge)).resize((side, side), Image.LANCZOS)


def compose_ipad(src: Path, dest: Path, meta: dict) -> None:
    img = ipad_square(Image.open(src).convert("RGB"), meta)
    s = 0.9   # type a little larger than the Mac's at the iPad's viewing distance
    corner = (IPAD_SAFE[1] - round(70 * s), IPAD_SAFE[1] - round(90 * s))
    img = draw_caption(img, meta, corner=corner, s=s)
    dest.parent.mkdir(exist_ok=True)
    img.save(dest, quality=90, subsampling=0)


def compose(src: Path, dest: Path, meta: dict) -> None:
    img = Image.open(src).convert("RGB")
    if meta.get("kind") == "art" and img.width / img.height < 1.35:
        # Bounded works (paintings, prints) get the museum mat; unbounded
        # imagery (space, textures) marked treatment=fill gets cropped
        # full-bleed instead — space has no composition edges to respect.
        if meta.get("treatment") == "fill":
            img = center_crop_to_screen(img)
        else:
            img = gallery_mat(img)
    img = draw_caption(img, meta)
    dest.parent.mkdir(exist_ok=True)
    img.save(dest, quality=93, subsampling=0)


def main() -> None:
    with open(BASE / "meta.json") as f:
        meta = json.load(f)
    done = skipped = 0
    for src in sorted(IMAGES.glob("*.[jp]*g")):
        if src.name not in meta:
            skipped += 1
            continue
        for folder, render in ((DISPLAY, compose), (IPAD, compose_ipad)):
            dest = folder / src.name
            if not dest.exists():
                render(src, dest, meta[src.name])
                done += 1
    for folder in (DISPLAY, IPAD):
        for orphan in folder.glob("*.[jp]*g"):
            if not (IMAGES / orphan.name).exists():
                orphan.unlink()
    print(f"composed {done}, skipped {skipped} (no metadata)")


if __name__ == "__main__":
    main()
