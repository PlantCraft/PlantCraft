"""A public demo visit's own copy of the app's database: try anything, keep nothing.

Every visit of PlantCraft's public demo is the same visitor account, so what one visitor changed
another would see. When PlantCraft marks a visit's token as isolated (``demo.isolated``, set by
``PLANTCRAFT_PUBLIC_DEMO_ISOLATED``), the app gives that visit a copy of its database, taken the
first time the visit touches it, and every read and write of the visit goes to the copy:

    data/app.sqlite3                          what everyone else (and the app's workers) use
    data/demo-slots/<visit key>/app.sqlite3   the visit's copy

The app's own file is never written by a visitor, so it stays the demo's fixed starting point
(with the live results the workers keep adding). A visit lasts at most PlantCraft's demo minutes;
its copy is deleted ``KEEP_MINUTES`` after it was taken. Nothing has to tell the app a visit
ended.

``DemoSlots`` (added by ``web.mount``) checks the token's signature with the app's verifier and
sets the visit for the request; ``Database.connect`` (``plantcraft_sdk.server.store``) reads it.
A store that must not be copied (counters a reset must not zero) sets ``DEMO_SHARED = True``.
Work that leaves the request (a queue, a thread) runs on the app's own file unless it carries
``visit_key()`` and runs inside ``using(key)``.

A database larger than ``PLANTCRAFT_DEMO_SLOT_MAX_MB`` (200) is never copied: the app then keeps
its visits read-only, as without isolation.

An app that declares ``Access(label, demo_copy=True)`` lets an isolated visit save (its
``EditorUser`` routes), once every database it opened can be copied. What the visit would send
to PlantCraft with the app's own key (audit, events, notifications, schedules, knowledge) is
refused instead (``plantcraft_sdk.client.DemoVisitWrite``): a visit's play never reaches what
everyone else sees.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextvars import ContextVar
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

FOLDER = "demo-slots"
# A copy is deleted this long after it was taken (a visit lasts 30 minutes at most).
KEEP_MINUTES = 45
SWEEP_SECONDS = 300
DEFAULT_MAX_MB = 200
_KEY = re.compile(r"^[0-9a-f]{16,64}$")

_VISIT: ContextVar[str | None] = ContextVar("plantcraft_sdk_demo_slot", default=None)
_LOCK = threading.Lock()
_SWEEPER: dict[str, Any] = {"thread": None, "roots": set()}
# The app's databases (``Database`` registers each): a visit edits only when all can be copied.
_DATABASES: set[Path] = set()


def key_of(visit: str) -> str:
    """The folder name of a visit's copies: a hash, never the visit's id itself."""

    return hashlib.sha256(visit.encode()).hexdigest()[:32]


def visit_key() -> str | None:
    """The visit the current request works for (None: the app's own data)."""

    return _VISIT.get()


@contextlib.contextmanager
def using(key: str | None) -> Iterator[None]:
    """Run a block for a visit (``visit_key()`` carried by a queue item), or for the app's own
    data (None)."""

    if key is not None and not _KEY.match(key):
        raise ValueError("not a demo visit key")
    token = _VISIT.set(key)
    try:
        yield
    finally:
        _VISIT.reset(token)


def max_bytes() -> int:
    try:
        megabytes = float(os.environ.get("PLANTCRAFT_DEMO_SLOT_MAX_MB", DEFAULT_MAX_MB))
    except ValueError:
        megabytes = DEFAULT_MAX_MB
    return int(max(megabytes, 0) * 1024 * 1024)


def _size(path: Path) -> int:
    total = 0
    for name in (path, Path(f"{path}-wal")):
        with contextlib.suppress(OSError):
            total += name.stat().st_size
    return total


def copyable(path: Path) -> bool:
    """Whether a visit may get its own copy of this database (not too large to copy)."""

    return _size(path) <= max_bytes()


def register(path: Path) -> None:
    _DATABASES.add(path)


def editable() -> bool:
    """Whether the current request is an isolated visit whose every database of this app gets
    its own copy: then the visit may save (``Access(..., demo_copy=True)``)."""

    return _VISIT.get() is not None and all(copyable(path) for path in _DATABASES)


def slot_path(path: Path, key: str) -> Path:
    return path.parent / FOLDER / key / path.name


def prepare(path: Path, key: str) -> Path:
    """The visit's copy of ``path``, taken now if the visit has none yet."""

    target = slot_path(path, key)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, _file_lock(target.parent / ".lock"):
        if target.exists():
            return target
        partial = target.with_name(f".{target.name}.{os.getpid()}.partial")
        source = sqlite3.connect(path, timeout=30)
        try:
            copy = sqlite3.connect(partial)
            try:
                source.backup(copy)
                # A copy of its own, never sharing the original's journal.
                copy.execute("PRAGMA journal_mode = DELETE")
            finally:
                copy.close()
        finally:
            source.close()
        os.replace(partial, target)
        marker = target.parent / ".taken"
        if not marker.exists():
            marker.write_text(str(time.time()))
    _start_sweeper(path.parent / FOLDER)
    return target


@contextlib.contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """The same copy is never taken twice at once, by another process of the app either."""

    try:
        import fcntl
    except ImportError:  # pragma: no cover - not on the suite's Linux images
        yield
        return
    with open(path, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def sweep(root: Path, now: float | None = None, keep_minutes: float = KEEP_MINUTES) -> int:
    """Delete the visits' copies taken more than ``keep_minutes`` ago; how many folders."""

    now = time.time() if now is None else now
    removed = 0
    if not root.is_dir():
        return 0
    for folder in root.iterdir():
        if not folder.is_dir() or not _KEY.match(folder.name):
            continue
        marker = folder / ".taken"
        try:
            taken = float(marker.read_text()) if marker.exists() else folder.stat().st_mtime
        except (OSError, ValueError):
            taken = folder.stat().st_mtime
        if now - taken >= keep_minutes * 60:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed


def _start_sweeper(root: Path) -> None:
    with _LOCK:
        _SWEEPER["roots"].add(root)
        if _SWEEPER["thread"] is not None:
            return

        def run() -> None:
            while True:
                time.sleep(SWEEP_SECONDS)
                for folder in list(_SWEEPER["roots"]):
                    try:
                        sweep(folder)
                    except Exception:  # the sweep never stops the app
                        LOGGER.exception("Demo copies not swept in %s", folder)

        thread = threading.Thread(target=run, name="demo-slots-sweep", daemon=True)
        _SWEEPER["thread"] = thread
        thread.start()


def isolated_claim(claims: dict[str, Any] | None) -> str | None:
    """The visit key of a verified token whose ``demo`` claim asks for isolation, else None."""

    demo = (claims or {}).get("demo")
    if isinstance(demo, dict) and demo.get("visit") and demo.get("isolated") is True:
        return key_of(str(demo["visit"]))
    return None


class DemoSlots:
    """ASGI middleware: the requests of an isolated demo visit work on the visit's copies.

    The token's signature is checked first (``runtime.verifier.claims``): a forged claim never
    picks a copy, nor makes one.
    """

    def __init__(self, app: Any, runtime: Any = None):
        self.app = app
        self.runtime = runtime

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        key = None
        if scope["type"] == "http":
            key = await self._key(scope)
        if key is None:
            await self.app(scope, receive, send)
            return
        token = _VISIT.set(key)
        try:
            await self.app(scope, receive, send)
        finally:
            _VISIT.reset(token)

    async def _key(self, scope: Any) -> str | None:
        from plantcraft_sdk.server.demo import _claimed, _token

        # Cheap first: no demo claim, nothing to verify.
        claimed = _claimed(scope)
        if not claimed or claimed.get("isolated") is not True:
            return None
        verifier = getattr(self.runtime, "verifier", None)
        if verifier is None:
            return None
        import anyio

        try:
            claims = await anyio.to_thread.run_sync(verifier.claims, _token(scope))
        except Exception:  # a refused token: the route answers 401 itself
            return None
        return isolated_claim(claims)


__all__ = [
    "DemoSlots",
    "copyable",
    "editable",
    "register",
    "isolated_claim",
    "key_of",
    "prepare",
    "sweep",
    "using",
    "visit_key",
]
