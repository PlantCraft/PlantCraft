"""Reads one revision's file and indexes it: extract, cut into passages, find the tags, embed.

``index_revision`` is the whole job of one file. It runs in the app's worker thread today, and
on a compute worker's executor (no network, no secrets) when the app sends it there; the
function only needs the file's bytes, the plant's known tags and the embedder.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np

from doccraft.i18n import t
from doccraft.library import extract as reader
from doccraft.library.embed import Embedder
from doccraft.library.passages import Passage, cut
from doccraft.library.store import DocumentStore
from doccraft.library.tags import known
from doccraft.plantmap.diagrams import describe

log = logging.getLogger(__name__)

# A document that marks itself as not for the assistant, or holds what looks like a secret, has
# the assistant switched off when its first revision is read (security test D11, 2026-10-31: a
# "not for the assistant" line inside the text is only text, and the answer quoted its PIN). The
# editor switches it back on in the document's settings when that was wrong.
CONFIDENTIAL = re.compile(
    r"\b(?:not\s+for\s+(?:the\s+)?(?:assistant|ai|llm)|confidential|strictly\s+private"
    r"|do\s+not\s+(?:share|distribute|disclose)|n[ãa]o\s+(?:compartilhar|divulgar)"
    r"|confidencial|uso\s+restrito)\b"
    r"|\b(?:password|passwd|passphrase|senha|pin|api[\s_-]?key|secret[\s_-]?key|token)"
    r"(?:\s*[:=]\s*\S{4,}|\s+(?:is|é)\s+[\"'`]?\S*\d\S*)",
    re.IGNORECASE,
)


def looks_confidential(texts: list[str]) -> bool:
    return any(CONFIDENTIAL.search(text) for text in texts)


@dataclass
class Indexed:
    format: str
    pages: int
    title: str
    passages: list[Passage]
    assets: list[list[str]]
    vectors: np.ndarray
    diagrams: list[dict] = field(default_factory=list)


def index_file(
    data: bytes, filename: str, tag_ids: dict[str, str], embedder: Embedder, title: str = ""
) -> Indexed:
    # Text and drawings are both read in a worker process with time and memory limits.
    extracted, diagrams = reader.read_isolated(data, filename)
    kind = reader.format_of(filename)
    # Each diagram page gets a passage saying what it shows, in words.
    for page in diagrams:
        heading = ["Diagram", " ".join(x for x in (page.get("sheet"), page.get("title")) if x)]
        extracted.sections.append(
            reader.Section(describe(page), page=page.get("page"), heading=[h for h in heading if h])
        )
    passages = cut(extracted.sections)
    if not passages:
        raise reader.Unreadable(
            t(
                "No text was found in the file. A scanned document needs text recognition (OCR), "
                "which is not switched on."
            )
            if kind not in reader.DRAWING_ONLY
            else t("No diagram was recognised in this drawing (no tags joined by lines).")
        )
    heading = title or extracted.title
    # Each passage is embedded with its document's title and headings, so "the manual of U-200,
    # section Emergency procedures" is part of what it means.
    texts = [" > ".join([heading, *p.heading]) + "\n" + p.text for p in passages]
    vectors = embedder.passages(texts)
    assets = [known(" ".join(p.heading) + " " + p.text, tag_ids) for p in passages]
    return Indexed(
        extracted.format, extracted.pages, extracted.title, passages, assets, vectors, diagrams
    )


def index_revision(
    store: DocumentStore, rev_id: str, tag_ids: dict[str, str], embedder: Embedder
) -> bool:
    rev = store.revision(rev_id)
    if rev is None:
        return False
    doc = store.document(rev["doc_id"]) or {}
    store.set_status(rev_id, "indexing")
    try:
        data = store.file_path(rev["sha256"]).read_bytes()
        done = index_file(data, rev["filename"], tag_ids, embedder, doc.get("title", ""))
    except reader.Unreadable as error:
        store.set_status(rev_id, "failed", str(error))
        return False
    except Exception as error:  # never leave a revision "indexing" after a crash
        log.exception("indexing %s failed", rev_id)
        store.set_status(
            rev_id, "failed", t("Indexing failed: {error}.", error=type(error).__name__)
        )
        return False
    store.store_passages(
        rev_id,
        done.passages,
        done.assets,
        done.vectors,
        format=done.format,
        pages=done.pages,
        embedder=embedder.name,
    )
    store.store_diagrams(rev_id, done.diagrams)
    first = len(doc.get("revisions") or []) <= 1
    if first and doc.get("assistant") and looks_confidential([p.text for p in done.passages]):
        store.update(rev["doc_id"], {"assistant": False})
        log.warning(
            "document %s looks confidential: the assistant no longer reads it", rev["doc_id"]
        )
    return True
