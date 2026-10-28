"""Sections into passages: about 350 words each, with 15 % overlap, never across a heading.

A passage keeps where it came from (the pages and the headings above it), so a citation can say
"Rev. C, p. 4, 9.1 Recycle flow FIC-1003 jumps and cycles" and the viewer can open that page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from doccraft.library.extract import Section

WORDS = 350
OVERLAP = 50
MIN_WORDS = 25  # a shorter tail joins the passage before it


@dataclass
class Passage:
    seq: int
    text: str
    page_from: int | None
    page_to: int | None
    heading: list[str]

    @property
    def section(self) -> str:
        return " > ".join(self.heading)


def cut(sections: list[Section], words: int = WORDS, overlap: int = OVERLAP) -> list[Passage]:
    passages: list[Passage] = []
    groups: list[tuple[list[str], list[tuple[str, int | None]]]] = []
    for section in sections:  # consecutive sections under the same heading form one group
        tokens = [(word, section.page) for word in re.split(r"(?<=\S)\s+", section.text) if word]
        if groups and groups[-1][0] == section.heading:
            groups[-1][1].extend(tokens)
        else:
            groups.append((section.heading, tokens))
    for heading, tokens in groups:
        start = 0
        while start < len(tokens):
            end = min(len(tokens), start + words)
            if len(tokens) - end < MIN_WORDS:
                end = len(tokens)
            part = tokens[start:end]
            pages = [page for _, page in part if page is not None]
            passages.append(
                Passage(
                    seq=len(passages),
                    text=_join(part),
                    page_from=min(pages) if pages else None,
                    page_to=max(pages) if pages else None,
                    heading=list(heading),
                )
            )
            if end >= len(tokens):
                break
            start = end - overlap
    return passages


def _join(tokens: list[tuple[str, int | None]]) -> str:
    return " ".join(word for word, _ in tokens)
