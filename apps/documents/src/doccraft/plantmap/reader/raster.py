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

from doccraft.plantmap.reader import tags as isa
from doccraft.plantmap.reader.primitives import Circle, Page, Text
from doccraft.plantmap.reader.svg import DrawingError

MAX_PIXELS = 60_000_000
OCR_SECONDS = 120


def read_image(data: bytes) -> Page:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - the image has it
        raise DrawingError("Reading images needs Pillow.") from exc
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # Pillow raises many kinds on a broken or huge file
        raise DrawingError("This image cannot be read (broken, or too large).") from exc
    dpi = image.info.get("dpi", (150, 150))[0] or 150
    return read_image_array(image, scale=float(dpi) / 72.0)


def read_image_array(image, *, scale: float) -> Page:
    """``scale``: pixels per point, so the page keeps the drawing's size in points."""

    gray = image.convert("L")
    width, height = gray.size
    page = Page(width=width / scale, height=height / scale, source="raster")
    words = ocr(gray)
    if words is None:
        page.notes.append("This drawing is a scan and OCR (Tesseract) is not installed here.")
        return page
    heights = sorted(b[3] - b[1] for _, b in words) or [12]
    text_px = heights[len(heights) // 2]
    taken = []
    for cx, cy, r in find_circles(gray, int(1.6 * text_px), int(4.5 * text_px)):
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
    _stacked_bubbles(page)
    page.notes.append("Scanned drawing: tags and their places are read; lines are not traced.")
    return page


def find_circles(gray, rmin: int, rmax: int) -> list[tuple[float, float, float]]:
    """Instrument bubbles: a Hough transform for circles of the bubbles' size (numpy only)."""

    import numpy as np

    step = 2 if max(gray.size) > 2500 else 1
    dark = np.asarray(gray, dtype=np.uint8)[::step, ::step] < 140
    ys, xs = np.nonzero(dark)
    if len(xs) == 0 or rmax <= rmin:
        return []
    if len(xs) > 1_500_000:
        pick = np.random.default_rng(0).choice(len(xs), 1_500_000, replace=False)
        ys, xs = ys[pick], xs[pick]
    h, w = dark.shape
    angles = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    found: list[tuple[float, float, float, float]] = []
    for r in range(max(rmin // step, 4), max(rmax // step, 5) + 1):
        acc = np.zeros(h * w, dtype=np.int32)
        for a in angles:
            cx = (xs - r * np.cos(a)).round().astype(np.int64)
            cy = (ys - r * np.sin(a)).round().astype(np.int64)
            ok = (cx >= 0) & (cx < w) & (cy >= 0) & (cy < h)
            acc += np.bincount(cy[ok] * w + cx[ok], minlength=h * w).astype(np.int32)
        best = np.nonzero(acc >= 0.8 * len(angles))[0]
        for idx in best:
            found.append((float(acc[idx]), float(idx % w), float(idx // w), float(r)))
    found.sort(reverse=True)
    kept: list[tuple[float, float, float]] = []
    for votes, x, y, r in found:
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
        raise DrawingError("Reading this scan took too long.") from exc
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


def _stacked_bubbles(page: Page) -> None:
    """Letters over a number (an ISA bubble) become one circle with both words inside."""

    letters = [t for t in page.texts if isa.LETTERS.match(t.text) and 2 <= len(t.text) <= 5]
    numbers = [t for t in page.texts if isa.NUMBER.match(t.text)]
    for top in letters:
        best = None
        for low in numbers:
            dy = low.cy - top.cy
            if 0.6 * top.height < dy < 2.6 * top.height and abs(low.cx - top.cx) < top.height:
                if best is None or dy < best[0]:
                    best = (dy, low)
        if best is None:
            continue
        low = best[1]
        cx = (top.cx + low.cx) / 2
        cy = (top.cy + low.cy) / 2
        r = max(top.box[2] - top.box[0], low.box[2] - low.box[0], low.cy - top.cy) * 0.9
        page.circles.append(Circle(cx, cy, r))
