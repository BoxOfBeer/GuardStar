"""Normalize map raster icons: trim near-pure-white pixels, resize to 96px."""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def clip_near_white(im: Image.Image, floor: int = 253) -> Image.Image:
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and r >= floor and g >= floor and b >= floor:
                px[x, y] = (0, 0, 0, 0)
    return im


def main() -> None:
    d = Path(__file__).resolve().parents[1] / "app" / "static" / "img" / "map"
    for p in sorted(d.glob("*.png")):
        im = Image.open(p).convert("RGBA")
        im = clip_near_white(im)
        im.thumbnail((96, 96), Image.Resampling.LANCZOS)
        out = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        x = (96 - im.width) // 2
        y = (96 - im.height) // 2
        out.paste(im, (x, y), im)
        out.save(p, "PNG", optimize=True)
        print(p.name, p.stat().st_size)


if __name__ == "__main__":
    main()
