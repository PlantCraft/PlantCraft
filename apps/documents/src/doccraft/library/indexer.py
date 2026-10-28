"""Reads one revision's file and indexes it: extract, cut into passages, find the tags, embed.

``index_revision`` is the whole job of one file. It runs in the app's worker thread today, and
on a compute worker's executor (no network, no secrets) when the app sends it there; the
function only needs the file's bytes, the plant's known tags and the embedder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from doccraft.library import extract as reader
from doccraft.library.embed import Embedder
from doccraft.library.passages import Passage, cut
from doccraft.library.store import DocumentStore
from doccraft.library.tags import known

log = logging.getLogger(__name__)


@dataclass
class Indexed:
    format: str
    pages: int
    title: str
    passages: list[Passage]
    assets: list[list[str]]
    vectors: np.ndarray


def index_file(
    data: bytes, filename: str, tag_ids: dict[str, str], embedder: Embedder, title: str = ""
) -> Indexed:
    extracted = reader.extract(data, filename)
    passages = cut(extracted.sections)
    if not passages:
        raise reader.Unreadable(
            "No text was found in the file. A scanned document needs text recognition (OCR), "
            "which is not switched on."
        )
    heading = title or extracted.title
    # Each passage is embedded with its document's title and headings, so "the manual of U-200,
    # section Emergency procedures" is part of what it means.
    texts = [" > ".join([heading, *p.heading]) + "\n" + p.text for p in passages]
    vectors = embedder.passages(texts)
    assets = [known(" ".join(p.heading) + " " + p.text, tag_ids) for p in passages]
    return Indexed(extracted.format, extracted.pages, extracted.title, passages, assets, vectors)


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
        store.set_status(rev_id, "failed", f"Indexing failed: {type(error).__name__}.")
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
    return True
