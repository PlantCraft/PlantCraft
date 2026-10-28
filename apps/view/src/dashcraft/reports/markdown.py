"""The Markdown of a report's text cells, read once into blocks every format writes.

A text cell is Markdown, as a Jupyter notebook's: headings ``#`` to ``####``, paragraphs,
bulleted and numbered lists, tables, quotes, rules, and ``**bold**``, ``*italic*``, ``code`` and
``[links](https://…)`` inside them (the part of Markdown the suite's help pages and
``renderMarkdown`` in @plantcraft/ui draw). The PDF, Word, HTML and Markdown files are all
written from these blocks, so a heading is a heading in every one of them, and the report's
outline (the side navigation, the PDF's bookmarks, Word's navigation pane) is its headings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

MAX_LEVEL = 4
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+")
_RULE = re.compile(r"^\s*(---+|\*\*\*+|___+)\s*$")
_TABLE_LINE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_INLINE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*]+\*|_[^_]+_)")
_LINK = re.compile(r"^\[([^\]]+)\]\(([^)\s]+)\)$")
# Only links a reader may follow safely: the web, a page of the suite, an anchor.
_SAFE_LINK = re.compile(r"^(https?://|/(?!/)|#)", re.IGNORECASE)


@dataclass(frozen=True)
class Span:
    """A run of text inside a block: plain, bold, italic, code or a link."""

    text: str
    style: Literal["plain", "bold", "italic", "code", "link"] = "plain"
    href: str = ""


@dataclass
class Block:
    kind: Literal["heading", "paragraph", "list", "table", "quote", "rule"]
    spans: list[Span] = field(default_factory=list)
    # A heading's level (1 to 4); a list's items; a table's head and rows; a list is numbered.
    level: int = 0
    items: list[list[Span]] = field(default_factory=list)
    head: list[list[Span]] = field(default_factory=list)
    rows: list[list[list[Span]]] = field(default_factory=list)
    align: list[str] = field(default_factory=list)
    numbered: bool = False
    # A heading's anchor in the HTML (set by ``outline``).
    anchor: str = ""

    @property
    def text(self) -> str:
        return plain(self.spans)


def inline(text: str) -> list[Span]:
    """The spans of one line of Markdown."""

    spans: list[Span] = []
    cursor = 0
    for match in _INLINE.finditer(text):
        if match.start() > cursor:
            spans.append(Span(text[cursor : match.start()]))
        token = match.group(0)
        if token.startswith(("**", "__")):
            spans.append(Span(token[2:-2], "bold"))
        elif token.startswith("`"):
            spans.append(Span(token[1:-1], "code"))
        elif token.startswith("["):
            link = _LINK.match(token)
            if link and _SAFE_LINK.match(link.group(2)):
                spans.append(Span(link.group(1), "link", link.group(2)))
            else:
                spans.append(Span(link.group(1) if link else token))
        else:
            spans.append(Span(token[1:-1], "italic"))
        cursor = match.end()
    if cursor < len(text):
        spans.append(Span(text[cursor:]))
    return spans


def plain(spans: list[Span]) -> str:
    return "".join(span.text for span in spans)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _starts_block(line: str, following: str) -> bool:
    return bool(
        _HEADING.match(line)
        or _BULLET.match(line)
        or _NUMBER.match(line)
        or _RULE.match(line)
        or line.lstrip().startswith(">")
        or ("|" in line and _TABLE_LINE.match(following or ""))
    )


def parse(text: str) -> list[Block]:
    """The blocks of a text cell, in order."""

    lines = (text or "").replace("\r\n", "\n").split("\n")
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if not line.strip():
            index += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            level = min(len(heading.group(1)), MAX_LEVEL)
            blocks.append(Block("heading", inline(heading.group(2)), level=level))
            index += 1
            continue
        if _RULE.match(line):
            blocks.append(Block("rule"))
            index += 1
            continue
        if "|" in line and _TABLE_LINE.match(following):
            head = _cells(line)
            align = []
            for cell in _cells(following):
                right, left = cell.endswith(":"), cell.startswith(":")
                align.append("center" if left and right else "right" if right else "left")
            index += 2
            rows: list[list[list[Span]]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                cells = _cells(lines[index])
                cells = (cells + [""] * len(head))[: len(head)]
                rows.append([inline(cell) for cell in cells])
                index += 1
            blocks.append(
                Block(
                    "table",
                    head=[inline(cell) for cell in head],
                    rows=rows,
                    align=(align + ["left"] * len(head))[: len(head)],
                )
            )
            continue
        if _BULLET.match(line) or _NUMBER.match(line):
            numbered = bool(_NUMBER.match(line))
            pattern = _NUMBER if numbered else _BULLET
            items: list[str] = []
            while index < len(lines) and pattern.match(lines[index]):
                item = pattern.sub("", lines[index], count=1)
                index += 1
                # A line indented under an item continues it.
                while (
                    index < len(lines)
                    and lines[index].strip()
                    and re.match(r"^\s{2,}\S", lines[index])
                    and not pattern.match(lines[index])
                ):
                    item += " " + lines[index].strip()
                    index += 1
                items.append(item)
            blocks.append(Block("list", items=[inline(item) for item in items], numbered=numbered))
            continue
        if line.lstrip().startswith(">"):
            quote: list[str] = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            blocks.append(Block("quote", inline(" ".join(part.strip() for part in quote))))
            continue
        paragraph = [line.strip()]
        index += 1
        while (
            index < len(lines)
            and lines[index].strip()
            and not _starts_block(lines[index], lines[index + 1] if index + 1 < len(lines) else "")
        ):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append(Block("paragraph", inline(" ".join(paragraph))))
    return blocks


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:60] or "section"


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    anchor: str


def outline_of(texts: list[list[Block]]) -> list[Heading]:
    """Every heading of the report's text cells, in order, each given a unique anchor."""

    used: set[str] = set()
    found: list[Heading] = []
    for blocks in texts:
        for block in blocks:
            if block.kind != "heading":
                continue
            base = slug(block.text)
            anchor, n = base, 2
            while anchor in used:
                anchor, n = f"{base}-{n}", n + 1
            used.add(anchor)
            block.anchor = anchor
            found.append(Heading(block.level, block.text, anchor))
    return found


__all__ = ["MAX_LEVEL", "Block", "Heading", "Span", "inline", "outline_of", "parse", "plain"]
