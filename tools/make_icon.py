#!/usr/bin/env python3
"""Genera l'icona dell'app (data/icon.png) con Pillow.

Disegno: sfondo teal arrotondato + un "grafico a torta" diviso in due spicchi,
metafora della divisione delle spese. Nessun font richiesto.

Uso (nel venv con Pillow):  python tools/make_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

SIZE = 512
TEAL = (0, 121, 107, 255)        # #00796B  sfondo
TEAL_LIGHT = (77, 182, 172, 255)  # #4DB6AC  spicchio 1
WHITE = (255, 255, 255, 255)      # spicchio 2
RADIUS = 96                       # raggio angoli dello sfondo


def rounded_background() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=RADIUS, fill=TEAL)
    return img


def draw_pie(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    margin = 120
    box = [margin, margin, SIZE - margin, SIZE - margin]
    gap = 6  # piccolo distacco tra gli spicchi
    # spicchio 1 (≈40%) e spicchio 2 (≈60%): due quote diverse
    d.pieslice(box, start=-90 + gap, end=60 - gap, fill=WHITE)
    d.pieslice(box, start=60 + gap, end=270 - gap, fill=TEAL_LIGHT)
    # piccolo cerchio centrale per effetto "donut"
    cx, cy = SIZE // 2, SIZE // 2
    r = 46
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=TEAL)


def main() -> None:
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "icon.png")

    img = rounded_background()
    draw_pie(img)
    img.save(out, "PNG")
    print(f"Icona generata: {out} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
