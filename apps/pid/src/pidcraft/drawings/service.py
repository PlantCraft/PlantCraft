"""Sending, reading and removing drawings.

A file is read by the drawing reader (``pidcraft.plantmap.reader``) in a worker process with a
time and memory limit, no network and no file writes (``plantcraft_sdk.sandbox``): a crafted file
that makes a reader spin or swell stops there, not in the app. ``PIDCRAFT_READ_TIMEOUT_SECONDS``
(120) and ``PIDCRAFT_READ_MEMORY_MB`` (1024) set the limits; ``PIDCRAFT_READ_SANDBOX=inline``
reads in this process (tests).
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import PurePath
from typing import Any

from pidcraft.drawings.models import DrawingFields
from pidcraft.drawings.store import DrawingStore
from pidcraft.plantmap.reader import DrawingError, kind_of

LOG = logging.getLogger(__name__)
READ = "PIDCRAFT_READ"
MAX_BYTES = 40 * 1024 * 1024
# The reader's kinds as the pages that draw them know them.
FORMATS = {
    "pdf": "pdf",
    "svg": "drawing",
    "dexpi": "drawing",
    "png": "image",
    "jpeg": "image",
    "tiff": "image",
}


class Refused(ValueError):
    """The file or its fields cannot be taken (the message is for the person)."""


def _read_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    from pidcraft.plantmap.diagrams import read_diagrams

    return read_diagrams(payload["data"], payload["filename"])


def read_isolated(data: bytes, filename: str) -> list[dict[str, Any]]:
    from plantcraft_sdk.sandbox import CodeError, pool

    os.environ.setdefault(f"{READ}_TIMEOUT_SECONDS", "120")
    os.environ.setdefault(f"{READ}_WORKERS", "1")
    try:
        return pool(READ).run(_read_payload, {"data": data, "filename": filename})
    except CodeError as error:
        raise Refused(f"The drawing could not be read within the limits: {error}") from error


def _number_from(filename: str) -> str:
    stem = PurePath(filename).stem
    clean = re.sub(r"[^A-Za-z0-9 ._/-]+", "-", stem).strip(" .-_/")[:60]
    return clean or "drawing"


class DrawingService:
    def __init__(self, store: DrawingStore):
        self.store = store
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def list(self) -> list[dict[str, Any]]:
        return self.store.drawings()

    def get(self, drawing_id: str) -> dict[str, Any] | None:
        return self.store.drawing(drawing_id)

    def add(self, data: bytes, filename: str, fields: DrawingFields, by: str) -> dict[str, Any]:
        """A new drawing, or a new file of the drawing with the same number; read later."""

        if not data:
            raise Refused("The file is empty.")
        if len(data) > MAX_BYTES:
            raise Refused("The file is larger than 40 MB.")
        try:
            kind = kind_of(data, filename)
        except DrawingError as error:
            raise Refused(str(error)) from error
        number = fields.number or _number_from(filename)
        found = self.store.by_number(number)
        if found is None:
            drawing_id = self.store.create_drawing(number, fields.title, fields.unit, by)
        else:
            drawing_id = found["drawing_id"]
            self.store.update_drawing(
                drawing_id,
                **{k: v for k, v in (("title", fields.title), ("unit", fields.unit)) if v},
            )
        sha = self.store.save_file(data)
        safe_name = PurePath(filename).name[:200] or "drawing"
        rev_id = self.store.add_revision(drawing_id, safe_name, FORMATS[kind], sha, len(data), by)
        self._wake.set()
        return {"drawing_id": drawing_id, "rev_id": rev_id, **(self.get(drawing_id) or {})}

    def read_one(self, rev_id: str) -> dict[str, Any] | None:
        rev = self.store.revision(rev_id)
        if rev is None:
            return None
        self.store.set_status(rev_id, "reading")
        try:
            data = self.store.file_path(rev["sha256"]).read_bytes()
            pages = read_isolated(data, rev["filename"])
        except (OSError, Refused) as error:
            self.store.set_status(rev_id, "failed", str(error))
            return self.store.revision(rev_id)
        self.store.store_diagrams(rev_id, pages)
        self.store.set_status(
            rev_id, "read", "" if pages else "No diagram was recognised.", len(pages)
        )
        return self.store.revision(rev_id)

    def read_queued(self) -> int:
        count = 0
        for rev in self.store.queued():
            self.read_one(rev["rev_id"])
            count += 1
        return count

    def delete(self, drawing_id: str) -> None:
        for sha in self.store.delete_drawing(drawing_id):
            try:
                self.store.file_path(sha).unlink()
            except OSError:
                pass

    # The reader in the background --------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="pidcraft-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.read_queued()
            except Exception:  # noqa: BLE001 - one bad file never stops the reader
                LOG.exception("reading the queued drawings failed")
            self._wake.wait(30)
            self._wake.clear()
