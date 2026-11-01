"""The library's rules, without HTTP: sending a file, reading it in the background, searching.

A file sent is kept at once and queued; the indexing thread reads it (``indexer``), so a request
never waits for a long PDF. A document whose number already exists gets a new revision, and the
older one is superseded when the new one is indexed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from doccraft.i18n import t
from doccraft.library import extract
from doccraft.library.embed import Embedder
from doccraft.library.indexer import index_revision
from doccraft.library.search import Hit, Searcher
from doccraft.library.store import DocumentStore
from doccraft.library.tags import index as tag_index

LOGGER = logging.getLogger(__name__)
TAGS_SECONDS = 300


class Refused(ValueError):
    """A file the library does not take, with the reason shown to the person."""


class LibraryService:
    def __init__(
        self,
        store: DocumentStore,
        embedder: Embedder,
        known_ids: Callable[[], list[str]],
        *,
        max_bytes: int,
        quota_bytes: int,
    ):
        self.store = store
        self.embedder = embedder
        self.searcher = Searcher(store, embedder)
        self.known_ids = known_ids
        self.max_bytes = max_bytes
        self.quota_bytes = quota_bytes
        self._tags: tuple[float, dict[str, str]] = (0.0, {})
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # The plant's tags, read from PlantCraft every few minutes

    def tag_ids(self) -> dict[str, str]:
        moment, ids = self._tags
        if not ids or time.monotonic() - moment > TAGS_SECONDS:
            try:
                ids = tag_index(self.known_ids())
            except Exception:  # noqa: BLE001 - without PlantCraft, no tag becomes a link
                LOGGER.warning("Assets not read from PlantCraft", exc_info=True)
            self._tags = (time.monotonic(), ids)
        return ids

    # Sending files

    def add(
        self,
        data: bytes,
        filename: str,
        fields: dict[str, Any],
        revision: str,
        issued: str,
        by: str,
    ) -> dict[str, Any]:
        if not data:
            raise Refused(t("The file is empty."))
        if len(data) > self.max_bytes:
            raise Refused(t("The file is larger than {n} MB.", n=self.max_bytes // (1024 * 1024)))
        if extract.format_of(filename) is None:
            raise Refused(
                t(
                    "This kind of file is not read: send PDF, Word, Excel, PowerPoint, text, "
                    "Markdown, CSV or HTML."
                )
            )
        if self.store.counts()["bytes"] + len(data) > self.quota_bytes:
            raise Refused(
                t(
                    "The documents' disk quota is full: delete old documents or ask an "
                    "administrator to raise it."
                )
            )
        existing = self.store.by_number(fields.get("number") or "")
        if existing is None:
            title = fields.get("title") or filename.rsplit(".", 1)[0]
            existing = self.store.create({**fields, "title": title}, by)
        rev = self.store.add_revision(existing["doc_id"], filename, data, revision, issued, by)
        self._wake.set()
        return {**(self.store.document(existing["doc_id"]) or {}), "added": rev}

    def reindex(self, doc_id: str) -> bool:
        doc = self.store.document(doc_id)
        if not doc or not doc.get("current"):
            return False
        self.store.set_status(doc["current"]["rev_id"], "queued")
        self._wake.set()
        return True

    # Reading files in the background

    def work_once(self) -> int:
        done = 0
        for rev in self.store.queue():
            if rev["status"] != "queued":
                continue
            index_revision(self.store, rev["rev_id"], self.tag_ids(), self.embedder)
            done += 1
        return done

    def start(self) -> None:
        if self._thread is not None:
            return
        # A revision left "indexing" by a stop is read again.
        for rev in self.store.queue():
            if rev["status"] == "indexing":
                self.store.set_status(rev["rev_id"], "queued")

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.work_once()
                except Exception:  # noqa: BLE001 - the thread outlives one bad file
                    LOGGER.exception("Indexing round failed")
                self._wake.wait(30)
                self._wake.clear()

        self._thread = threading.Thread(target=loop, name="doccraft-indexer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # Searching

    def search(self, query: str, **options: Any) -> list[Hit]:
        return self.searcher.search(query, **options)
