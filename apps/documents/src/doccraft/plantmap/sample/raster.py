"""A drawing as a scanner would give it: a PDF page rendered to an image, tilted, with noise."""

from __future__ import annotations

import random
from pathlib import Path


def scan(pdf: Path, png: Path, *, dpi: int = 200, noise: float = 0.0, seed: int = 0) -> None:
    import pypdfium2
    from PIL import Image, ImageFilter

    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        image = doc[0].render(scale=dpi / 72).to_pil().convert("L")
    finally:
        doc.close()
    if noise > 0:
        rnd = random.Random(seed)
        image = image.rotate(noise * 0.6, resample=Image.BICUBIC, expand=False, fillcolor=255)
        image = image.filter(ImageFilter.GaussianBlur(radius=0.6 * noise))
        pixels = image.load()
        w, h = image.size
        for _ in range(int(w * h * 0.002 * noise)):
            x, y = rnd.randrange(w), rnd.randrange(h)
            pixels[x, y] = 0 if rnd.random() < 0.5 else 255
    image.save(png, dpi=(dpi, dpi))
