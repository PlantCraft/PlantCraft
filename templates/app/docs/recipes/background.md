# Background work

Some apps work on their own: compute a result every ten minutes, watch a signal, clean old rows.
That work starts in `Runtime.start()` and stops in `Runtime.shutdown()`; the SDK calls both when
the server starts and stops.

`src/starter/worker.py` (a module of its own, between the objects and the API: in `LAYERS` of
`tests/test_suite_rules.py`, add `"worker": 3` and move `api` and `cli` to 4):

```python
"""Every ten minutes, publish how many notes each asset has."""

import logging
import threading
from collections import Counter

from starter.notes.service import NoteService
from starter.suite import Suite

LOGGER = logging.getLogger(__name__)
EVERY = 600  # seconds


class Worker:
    def __init__(self, notes: NoteService, suite: Suite):
        self.notes, self.suite = notes, suite
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> None:
        counts = Counter(note["asset_id"] for note in self.notes.list())
        self.suite.note_counts(dict(counts))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # one bad round never stops the worker
                LOGGER.exception("Round failed")
            self._stop.wait(EVERY)

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="starter-worker", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
```

In `Runtime`:

```python
self.worker = Worker(self.notes, self.suite)


def start(self) -> None:
    if self.settings.worker:  # a setting, so tests and a second process can turn it off
        self.worker.start()


def shutdown(self) -> None:
    self.worker.stop()
    self.close_platform()


def status(self) -> dict[str, Any]:  # GET /api/status
    return {"service_key": self.has_service_key, "worker": self.worker._thread is not None}
```

Rules:

- Background work uses the **app key** (`rt.service_client`) through `suite/`. Without one, it
  does nothing and says so in `status()`; it never crashes the server.
- Test `run_once()` directly; keep the thread off in tests.
- A computation that takes long belongs in a queue the person can see (PlantCraft's
  `docs/app-standard.md`, "A work queue looks the same in every app") or in the suite's compute
  workers (`docs/compute.md`), not in a request.
- The server runs one process: if you run several, only one should do the background work.
