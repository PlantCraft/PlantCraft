"""Scanned drawings (PNG, JPEG, TIFF, a PDF page with no text): the tags, read with OCR.

Tesseract (Apache-2.0) reads the words with their boxes, run as a separate program with no
network. Instrument bubbles are recognised from their stacked words (letters over the number);
equipment and instrument tags come out with their place on the drawing. The lines and symbols of
a scan are not traced yet: a scan gives the tags and where they are, and the review page says so.
"""

from __future__ import annotations

import io
import shutil
import subprocess

from doccraft.i18n import t
from doccraft.plantmap.reader.primitives import Circle, Page, Text
from doccraft.plantmap.reader.svg import DrawingError

MAX_PIXELS = 60_000_000
# A scan is read within a time and size budget: larger pages are scaled down first, and the
# bubbles are read one by one only while time is left (real scans with hatching or dense text
# once gave thousands of candidate circles and ran for minutes).
WORK_PIXELS = 16_000_000
MAX_BUBBLES = 250
BUDGET_SECONDS = 90.0
MAX_RADII = 24
OCR_SECONDS = 120


def read_image(data: bytes) -> Page:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - the image has it
        raise DrawingError(t("Reading images needs Pillow.")) from exc
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # Pillow raises many kinds on a broken or huge file
        raise DrawingError(t("This image cannot be read (broken, or too large).")) from exc
    dpi = image.info.get("dpi", (150, 150))[0] or 150
    return read_image_array(image, scale=float(dpi) / 72.0)


def read_image_array(image, *, scale: float) -> Page:
    """``scale``: pixels per point, so the page keeps the drawing's size in points."""

    import time

    started = time.monotonic()
    gray = image.convert("L")
    width, height = gray.size
    page = Page(width=width / scale, height=height / scale, source="raster")
    if width * height > WORK_PIXELS:
        shrink = (WORK_PIXELS / (width * height)) ** 0.5
        gray = gray.resize((max(1, int(width * shrink)), max(1, int(height * shrink))))
        scale *= shrink
    words = ocr(gray)
    if words is None:
        page.notes.append(t("This drawing is a scan and OCR (Tesseract) is not installed here."))
        return page
    heights = sorted(b[3] - b[1] for _, b in words) or [12]
    text_px = heights[len(heights) // 2]
    taken = []
    circles = find_circles(gray, int(1.6 * text_px), int(4.5 * text_px))
    if len(circles) > MAX_BUBBLES:
        page.notes.append(
            t(
                "{n} round shapes found; only the {most} clearest were read.",
                n=len(circles),
                most=MAX_BUBBLES,
            )
        )
        circles = circles[:MAX_BUBBLES]
    for n, (cx, cy, r) in enumerate(circles):
        if time.monotonic() - started > BUDGET_SECONDS:
            page.notes.append(
                t("Time budget reached: {n} round shapes were not read.", n=len(circles) - n)
            )
            break
        inner = read_bubble(gray, cx, cy, r, 0.82) or read_bubble(gray, cx, cy, r, 0.93)
        if not inner:
            continue
        taken.append((cx, cy, r))
        page.circles.append(Circle(cx / scale, cy / scale, r / scale))
        for k, word in enumerate(inner):
            y = (cy - r * 0.3 + k * r * 0.6) / scale
            h = text_px / scale
            page.texts.append(Text(word, (cx / scale - h, y - h / 2, cx / scale + h, y + h / 2)))
    for text, (x0, y0, x1, y1) in words:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        if any((mx - cx) ** 2 + (my - cy) ** 2 < r * r for cx, cy, r in taken):
            continue
        page.texts.append(Text(text, (x0 / scale, y0 / scale, x1 / scale, y1 / scale)))
    from doccraft.plantmap.reader.graph import stacked_bubbles

    stacked_bubbles(page)
    page.notes.append(t("Scanned drawing: tags and their places are read; lines are not traced."))
    return page


def find_circles(gray, rmin: int, rmax: int) -> list[tuple[float, float, float]]:
    """Instrument bubbles: a Hough transform for circles of the bubbles' size (numpy only).

    Each centre counts the dark pixels on a ring of 40 points around it, as whole shifted
    copies of the page added together: the same votes as each dark pixel voting for the
    centres around it, 11 times faster on a demo sheet (5.2 s to 0.46 s)."""

    import numpy as np

    step = 2 if max(gray.size) > 2500 else 1
    dark = np.asarray(gray, dtype=np.uint8)[::step, ::step] < 140
    if not dark.any() or rmax <= rmin:
        return []
    h, w = dark.shape
    angles = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    found: list[tuple[float, float, float, float]] = []
    low, high = max(rmin // step, 4), max(rmax // step, 5)
    stride = max(1, (high - low + 1) // MAX_RADII)
    pad = high + 1
    padded = np.zeros((h + 2 * pad, w + 2 * pad), dtype=np.uint8)
    padded[pad : pad + h, pad : pad + w] = dark
    acc = np.empty((h, w), dtype=np.uint8)  # at most 40 votes
    for r in range(low, high + 1, stride):
        dx = np.rint(r * np.cos(angles)).astype(int)
        dy = np.rint(r * np.sin(angles)).astype(int)
        acc[:] = 0
        for ox, oy in zip(dx, dy, strict=True):
            acc += padded[pad + oy : pad + oy + h, pad + ox : pad + ox + w]
        votes = acc.ravel()
        best = np.flatnonzero(votes >= 0.8 * len(angles))
        if len(best) > 20_000:  # a filled or hatched area votes everywhere: keep the strongest
            best = best[np.argsort(votes[best], kind="stable")[-20_000:]]
        for idx in best:
            found.append((float(votes[idx]), float(idx % w), float(idx // w), float(r)))
    found.sort(reverse=True)
    kept: list[tuple[float, float, float]] = []
    for _, x, y, r in found[:200_000]:
        if len(kept) >= 2 * MAX_BUBBLES:
            break
        if all((x - kx) ** 2 + (y - ky) ** 2 > (max(r, kr)) ** 2 for kx, ky, kr in kept):
            kept.append((x, y, r))
    return [(x * step, y * step, r * step) for x, y, r in kept]


def read_bubble(gray, cx: float, cy: float, r: float, part: float = 0.82) -> list[str]:
    """The words inside one bubble, read on their own (the ring hides them from a page OCR)."""

    from PIL import Image, ImageDraw

    inner = r * part
    box = (int(cx - inner), int(cy - inner), int(cx + inner), int(cy + inner))
    crop = gray.crop(box)
    mask = Image.new("L", crop.size, 255)
    ImageDraw.Draw(mask).ellipse((0, 0, crop.size[0] - 1, crop.size[1] - 1), fill=0)
    crop = Image.composite(Image.new("L", crop.size, 255), crop, mask)
    # The shared-display line across the middle: drop rows that are mostly dark.
    pixels = crop.load()
    w, h = crop.size
    for y in range(h):
        if sum(1 for x in range(w) if pixels[x, y] < 140) > 0.6 * w:
            for x in range(w):
                pixels[x, y] = 255
    crop = crop.resize((w * 3, h * 3), Image.LANCZOS)
    padded = Image.new("L", (crop.size[0] + 40, crop.size[1] + 40), 255)
    padded.paste(crop, (20, 20))
    words = ocr(padded, psm="6") or []
    lines: list[str] = []
    for text, (_, y0, _, y1) in sorted(words, key=lambda w: (w[1][1], w[1][0])):
        if text:
            lines.append(text)
    return lines if any(ch.isalpha() for ch in "".join(lines)) else []


def ocr(gray, psm: str = "11") -> list[tuple[str, tuple[int, int, int, int]]] | None:
    binary = shutil.which("tesseract")
    if not binary:
        return None
    buffer = io.BytesIO()
    # Upscale small scans: Tesseract wants letters at least ~20 px high.
    gray.save(buffer, format="PNG")
    try:
        done = subprocess.run(
            [binary, "stdin", "stdout", "--psm", psm, "-c", "preserve_interword_spaces=0", "tsv"],
            input=buffer.getvalue(),
            capture_output=True,
            timeout=OCR_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DrawingError(t("Reading this scan took too long.")) from exc
    out = []
    for line in done.stdout.decode("utf-8", "replace").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            conf = float(cols[10])
            x, y, w, h = (int(cols[k]) for k in (6, 7, 8, 9))
        except ValueError:
            continue
        if conf < 30:
            continue
        out.append((_clean(cols[11].strip()), (x, y, x + w, y + h)))
    return out


def _clean(word: str) -> str:
    """Common OCR slips inside a tag: O for 0 in the number, l or | for 1."""
    word = word.strip(".,;:()[]{}'\"")
    if "-" in word:
        letters, _, number = word.partition("-")
        number = number.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
        word = f"{letters}-{number}"
    return word
