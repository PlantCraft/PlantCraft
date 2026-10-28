"""Search by words and by meaning, fused.

Industrial documents are full of tags and numbers ("FV-1003", "WO-25-1182") that a word index
finds exactly and a meaning model blurs, and of questions in other words ("why does the recycle
flow jump?") that only meaning finds. Both run, each gives its best 60 passages among those the
person may read, and reciprocal rank fusion (k = 60) merges them. Passages that name the asset
asked about, or whose document is linked to it, rank higher.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np
from plantcraft_sdk.asset_scope import EVERYTHING, AssetScope

from doccraft.library.access import about
from doccraft.library.embed import Embedder
from doccraft.library.store import DocumentStore
from doccraft.library.tags import TAG

RRF_K = 60
CANDIDATES = 60
ASSET_BOOST = 1.5
DOC_BOOST = 1.2
STOP = set(
    "a an and are as at be by can do does for from has have how i in is it its of on or should "
    "that the this to was what when where which who why will with "
    "o a os as de da do das dos e em no na nos nas um uma por para que qual quais quando como "
    "se ser sobre com ao".split()
)


@dataclass
class Hit:
    passage: dict[str, Any]
    score: float
    by: list[str]  # "words", "meaning"


class Searcher:
    def __init__(self, store: DocumentStore, embedder: Embedder):
        self.store = store
        self.embedder = embedder
        self._cache: tuple[int, np.ndarray, np.ndarray] | None = None
        self._lock = threading.Lock()

    def _vectors(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            if self._cache is None or self._cache[0] != self.store.version:
                ids, matrix = self.store.vectors()
                self._cache = (self.store.version, ids, matrix)
            return self._cache[1], self._cache[2]

    def search(
        self,
        query: str,
        *,
        folders: set[str] | None = None,
        assistant: bool = False,
        assets: list[str] | None = None,
        kind: str | None = None,
        limit: int = 8,
        scope: AssetScope = EVERYTHING,
    ) -> list[Hit]:
        query = (query or "").strip()[:500]
        if not query:
            return []
        ranked: dict[int, float] = {}
        by: dict[int, list[str]] = {}

        words = self.store.keyword(fts_query(query), CANDIDATES, folders, assistant)
        for rank, passage_id in enumerate(words):
            ranked[passage_id] = ranked.get(passage_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            by.setdefault(passage_id, []).append("words")

        ids, matrix = self._vectors()
        if len(ids) and matrix.shape[1]:
            vector = self.embedder.query(query)
            if vector.shape[0] == matrix.shape[1]:
                scores = matrix @ vector
                allowed = self.store.allowed_ids(folders, assistant)
                if allowed is not None:
                    scores = np.where(np.isin(ids, allowed), scores, -np.inf)
                top = np.argsort(-scores)[:CANDIDATES]
                for rank, index in enumerate(top):
                    if not np.isfinite(scores[index]):
                        break
                    passage_id = int(ids[index])
                    ranked[passage_id] = ranked.get(passage_id, 0.0) + 1.0 / (RRF_K + rank + 1)
                    by.setdefault(passage_id, []).append("meaning")

        rows = {row["passage_id"]: row for row in self.store.passage_rows(list(ranked))}
        if not scope.everything:
            # Passages of documents about assets the person does not see stay out.
            linked_to = self.store.doc_assets([row["doc_id"] for row in rows.values()])
            rows = {
                key: row
                for key, row in rows.items()
                if about(scope, linked_to.get(row["doc_id"], []))
            }
        linked = self.store.linked_docs(assets or [])
        asked = set(assets or [])
        hits = []
        for passage_id, score in ranked.items():
            row = rows.get(passage_id)
            if row is None or (kind and row["kind"] != kind):
                continue
            if asked and asked & set(row["assets"]):
                score *= ASSET_BOOST
            elif row["doc_id"] in linked:
                score *= DOC_BOOST
            hits.append(Hit(row, score, by[passage_id]))
        hits.sort(key=lambda hit: -hit.score)
        return hits[: max(1, min(limit, 50))]


def fts_query(text: str) -> str:
    """The words of a question as an FTS5 query: each word or tag quoted, joined by OR, so BM25
    ranks the passages that hold more of the rarer words first. "FIC1003" also finds "FIC-1003"."""

    terms: list[str] = []
    for letters, number in TAG.findall(text.upper()):
        terms.append(f'"{letters} {number}"')
    for word in re.findall(r"[\wÀ-ÿ]+", text.lower()):
        if len(word) > 1 and word not in STOP and not word.isdigit():
            terms.append(f'"{word}"')
    unique = list(dict.fromkeys(terms))
    return " OR ".join(unique) if unique else '""'
