"""Every page must fit at every display size: nothing cut, nothing wider than the screen.

The user menu offers five display sizes (``@plantcraft/ui`` ``displaySize.ts``, docs/brand.md
"Display size"), from Larger text (1) to More space (5). A page is written once, at the default,
and has to hold at all five on a small laptop and on a large screen. Journeys check it with
these helpers instead of looking at each page by eye. One test per app walks every page of its
menu, on a small laptop and a large screen, at the five sizes::

    from plantcraft_sdk import displayfit

    def test_every_page_fits_at_every_display_size(signed_in, app_url):
        displayfit.assert_fits(signed_in, app_url)

``problems`` reads the page as drawn and names, for each problem, the element and its text:

- **cut text**: text that runs past the edge of a box that hides its overflow (``overflow:
  hidden`` or ``clip``), so part of it is not seen. Text a box shortens on purpose with an
  ellipsis (``text-overflow: ellipsis``) or a line clamp is not counted; neither are boxes
  that scroll, screen-reader-only text, editors, charts and drawings.
- **text out of its frame**: text that runs past the edge of its card, button, table cell or
  dialog and over what is beside it, even where nothing hides it.
- **text over text**: two pieces of text drawn on top of each other (a box too small for what
  it holds, its content running over its title or its neighbour).
- **wider than the screen**: the page scrolls sideways.

An element that cuts its text on purpose in another way says so with ``data-clip-ok``.
"""

from __future__ import annotations

from typing import Any

SIZE_KEY = "plantcraft-ui:display-size"
SIZES = (1, 2, 3, 4, 5)
SIZE_NAMES = {1: "Larger text", 2: "Large", 3: "Default", 4: "Compact", 5: "More space"}
# A small company laptop and a large office screen.
VIEWPORTS = ({"width": 1366, "height": 768}, {"width": 1920, "height": 1080})
CASES = tuple((size, viewport) for viewport in VIEWPORTS for size in SIZES)

PROBLEMS_JS = r"""
() => {
  const skip = 'svg, canvas, .js-plotly-plot, .cm-editor, .be-canvas, [data-clip-ok], [aria-hidden=true], .sr-only, .visually-hidden';
  const frames = '.panel, .pc-wg-card, .tc-card, .pc-cards-cell, button, .button, td, th, [role=dialog], .pcs-user-pop';
  const found = [];
  const seen = new Set();
  const view = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > view + 1) {
    found.push(`wider than the screen: ${document.documentElement.scrollWidth}px on ${view}px`);
  }
  const label = (el) => {
    const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    return el.tagName.toLowerCase() + cls;
  };
  const shortened = (el, stop) => {
    for (let node = el; node && node !== stop.parentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.textOverflow === 'ellipsis') return true;
      const clamp = style.webkitLineClamp || style.getPropertyValue('-webkit-line-clamp');
      if (clamp && clamp !== 'none') return true;
    }
    return false;
  };
  const lines = []; // every line of text as drawn, for text drawn over other text
  // The part of a rectangle the boxes around it let be seen (null: none of it).
  const visible = (rect, el) => {
    let { left, right, top, bottom } = rect;
    for (let box = el; box && box !== document.body; box = box.parentElement) {
      const boxStyle = getComputedStyle(box);
      const edge = box.getBoundingClientRect();
      if (['hidden', 'clip'].includes(boxStyle.overflowX) || ['auto', 'scroll'].includes(boxStyle.overflowX)) { left = Math.max(left, edge.left); right = Math.min(right, edge.right); }
      if (['hidden', 'clip'].includes(boxStyle.overflowY) || ['auto', 'scroll'].includes(boxStyle.overflowY)) { top = Math.max(top, edge.top); bottom = Math.min(bottom, edge.bottom); }
      if (right - left <= 1 || bottom - top <= 1) return null;
    }
    return { left, right, top, bottom };
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let text = walker.nextNode(); text; text = walker.nextNode()) {
    const value = text.textContent.trim();
    const parent = text.parentElement;
    if (!value || !parent || parent.closest(skip)) continue;
    const style = getComputedStyle(parent);
    if (style.visibility !== 'visible' || style.display === 'none') continue;
    // Not drawn: inside a closed <details>, a hidden subtree or one at zero opacity.
    if (parent.checkVisibility && !parent.checkVisibility({ contentVisibilityAuto: true, opacityProperty: true, visibilityProperty: true })) continue;
    const range = document.createRange();
    range.selectNodeContents(text);
    const rects = [...range.getClientRects()].filter((rect) => rect.width > 0 && rect.height > 0);
    if (!rects.length) continue;
    // A glyph box can be taller than a tight line (line-height 1); the part beyond the line box
    // is the font's own space, so a frame's edge and other text are measured from the line box.
    // A box that hides its overflow is measured from the glyph box: what it hides there is ink.
    const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2;
    const slack = (rect) => Math.max(2, (rect.height - line) / 2 + 1);
    // Bars that stay in place (a sticky footer with Save) cover the page on purpose.
    const pinned = (() => {
      for (let node = parent; node && node !== document.body; node = node.parentElement) {
        if (['sticky', 'fixed'].includes(getComputedStyle(node).position)) return true;
      }
      return false;
    })();
    for (const rect of pinned ? [] : rects) {
      const trim = Math.max(0, (rect.height - line) / 2);
      const seen = visible({ left: rect.left, right: rect.right, top: rect.top + trim, bottom: rect.bottom - trim }, parent);
      if (seen) lines.push({ el: parent, value, ...seen });
    }
    for (let box = parent; box && box !== document.body; box = box.parentElement) {
      const boxStyle = getComputedStyle(box);
      // A box that scrolls lets the person reach its text: nothing beyond it is cut.
      if (['auto', 'scroll'].includes(boxStyle.overflowX) || ['auto', 'scroll'].includes(boxStyle.overflowY)) break;
      const hidesX = ['hidden', 'clip'].includes(boxStyle.overflowX);
      const hidesY = ['hidden', 'clip'].includes(boxStyle.overflowY);
      if (!hidesX && !hidesY) continue;
      const edge = box.getBoundingClientRect();
      if (edge.width <= 2 || edge.height <= 2) break; // screen-reader-only text
      const past = rects.some((rect) =>
        (hidesX && (rect.right > edge.right + 2 || rect.left < edge.left - 2)) ||
        (hidesY && (rect.bottom > edge.bottom + 2 || rect.top < edge.top - 2)));
      if (past && !shortened(parent, box)) {
        const key = label(box) + '|' + value.slice(0, 40);
        if (!seen.has(key)) {
          seen.add(key);
          found.push(`cut text in ${label(box)}: "${value.slice(0, 60)}"`);
        }
      }
      break; // the nearest box that hides its overflow decides
    }
    // Text that spills out of its card, button or cell, over what is beside it.
    const frame = parent.closest(frames);
    const scrolls = (() => {
      for (let node = parent; node && node !== frame; node = node.parentElement) {
        const nodeStyle = getComputedStyle(node);
        if (['auto', 'scroll'].includes(nodeStyle.overflowX) || ['auto', 'scroll'].includes(nodeStyle.overflowY)) return true;
      }
      return false;
    })();
    if (frame && !scrolls && !shortened(parent, frame)) {
      const edge = frame.getBoundingClientRect();
      const out = rects.some((rect) => rect.right > edge.right + 2 || rect.left < edge.left - 2 || rect.bottom > edge.bottom + slack(rect) || rect.top < edge.top - slack(rect));
      const key = 'spill|' + label(frame) + '|' + value.slice(0, 40);
      if (out && edge.width > 2 && !seen.has(key)) {
        seen.add(key);
        found.push(`text out of ${label(frame)}: "${value.slice(0, 60)}"`);
      }
    }
  }
  // Text drawn over other text: two lines of different elements sharing more than a sliver.
  lines.sort((a, b) => a.top - b.top);
  for (let i = 0; i < lines.length; i++) {
    const a = lines[i];
    for (let j = i + 1; j < lines.length && lines[j].top < a.bottom; j++) {
      const b = lines[j];
      if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const wide = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const tall = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (wide <= 2 || tall <= Math.min(a.bottom - a.top, b.bottom - b.top) * 0.25) continue;
      const key = 'over|' + a.value.slice(0, 30) + '|' + b.value.slice(0, 30);
      if (!seen.has(key)) {
        seen.add(key);
        found.push(`text over text: "${a.value.slice(0, 40)}" and "${b.value.slice(0, 40)}"`);
      }
    }
  }
  return found;
}
"""


def apply_size(page: Any, size: int) -> None:
    """Switch the open page to a display size at once, as the user menu does (no reload)."""

    page.evaluate(
        """([key, size]) => {
          try { if (size === 3) localStorage.removeItem(key); else localStorage.setItem(key, String(size)); } catch (error) {}
          const root = document.documentElement;
          if (size === 3) delete root.dataset.size; else root.dataset.size = String(size);
          window.dispatchEvent(new CustomEvent('plantcraft-ui:display-size', { detail: size }));
          window.dispatchEvent(new Event('resize'));
        }""",
        [SIZE_KEY, size],
    )


def menu_pages(page: Any, base_url: str) -> list[str]:
    """The pages of the app's menu (its sidebar links on the same host and under ``base_url``)."""

    page.goto(base_url)
    _settle(page)
    links = page.eval_on_selector_all(
        "aside a[href], nav a[href]",
        "links => links.map((link) => link.href)",
    )
    base = base_url.rstrip("/")
    found: list[str] = []
    for href in [base + "/", *links]:
        url = href.split("#")[0]
        if url.startswith(base) and "/api/" not in url and url not in found:
            found.append(url)
    return found


def detail_pages(page: Any, urls: list[str], per_page: int = 2) -> list[str]:
    """A few pages one level down from each menu page (a loop, a signal, a run), so the pages
    with charts and long names are checked too, not only the lists."""

    found: list[str] = []
    for url in urls:
        page.goto(url)
        _settle(page)
        base = url.split("?")[0].rstrip("/") + "/"
        links = page.eval_on_selector_all(
            "main a[href], .pc-main a[href]", "links => links.map((link) => link.href)"
        )
        taken = 0
        for href in links:
            link = href.split("#")[0]
            path = link.split("?")[0]
            if taken >= per_page or not path.startswith(base) or path == base or "/api/" in path:
                continue
            if link in urls or link in found or path.endswith((".csv", ".pdf", ".zip", ".json")):
                continue
            found.append(link)
            taken += 1
    return found


def _settle(page: Any, ms: int = 400) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # A page that keeps a stream open: draw what it has.
        pass
    page.wait_for_timeout(ms)


def check(
    page: Any,
    base_url: str,
    urls: list[str] | None = None,
    screenshots: Any = None,
) -> dict[str, list[str]]:
    """Every page at every case (two screens, five sizes): what does not fit, by page and case.

    Each page is opened once per screen and switched through the five sizes in place, as a
    person does from the user menu. With ``screenshots`` (a folder), a page that does not fit is
    saved as ``fit-<size>-<width>-<page>.png``.
    """

    if not urls:
        urls = menu_pages(page, base_url)
        urls += detail_pages(page, urls)
    report: dict[str, list[str]] = {}
    for viewport in VIEWPORTS:
        page.set_viewport_size(viewport)
        for url in urls:
            page.goto(url)
            _settle(page, 300)
            for size in SIZES:
                apply_size(page, size)
                page.wait_for_timeout(150)
                found = problems(page)
                if found:
                    name = url.removeprefix(base_url.rstrip("/")).strip("/") or "home"
                    report.setdefault(f"{name} ({describe(size, viewport)})", []).extend(found)
                    if screenshots:
                        slug = "".join(ch if ch.isalnum() else "-" for ch in name)[:80]
                        page.screenshot(
                            path=f"{screenshots}/fit-{size}-{viewport['width']}-{slug}.png"
                        )
            apply_size(page, 3)
    return report


def assert_fits(
    page: Any, base_url: str, urls: list[str] | None = None, screenshots: Any = None
) -> None:
    """Fail with the list of pages, cases and texts that do not fit (see ``check``)."""

    report = check(page, base_url, urls, screenshots)
    lines = [f"{case}: {problem}" for case, found in report.items() for problem in found]
    assert not lines, "Pages that do not fit at every display size:\n" + "\n".join(lines[:60])


def set_size(page: Any, size: int, viewport: dict[str, int] | None = None) -> None:
    """Choose a display size (1 to 5) for the pages this browser opens next, and the window size."""

    if size not in SIZES:
        raise ValueError(f"display size {size} is not one of {SIZES}")
    if viewport:
        page.set_viewport_size(viewport)
    page.evaluate(
        "([key, size]) => { try { if (size === 3) localStorage.removeItem(key);"
        " else localStorage.setItem(key, String(size)); } catch (error) {} }",
        [SIZE_KEY, size],
    )


def problems(page: Any) -> list[str]:
    """What does not fit on the page as drawn now: cut text, or a page wider than the screen."""

    return list(page.evaluate(PROBLEMS_JS))


def describe(size: int, viewport: dict[str, int]) -> str:
    """'Larger text at 1366x768', for a failure message."""

    return f"{SIZE_NAMES[size]} at {viewport['width']}x{viewport['height']}"
