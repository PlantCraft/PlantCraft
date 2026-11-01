# Results

A result is the latest thing your app concluded about an asset or a signal, in the suite's one
status vocabulary: `ok`, `warning`, `alarm` or `unknown`. PlantCraft shows every app's results
on the asset's page, and other apps may read them (that is how apps link, without calling each
other).

`app.toml`:

```toml
[permissions]
write = ["audit", "results"]

[publishes]
results = [{ kind = "note_count", subject = "asset" }]   # read by others as starter.note_count
```

`src/starter/suite/results.py`:

```python
"""The results StarterCraft publishes on assets."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.client import PlantCraftError

from starter.i18n import t

LOGGER = logging.getLogger(__name__)


def note_counts(client: Any, counts: dict[str, int]) -> None:
    """One result per asset: how many notes it has (a warning from five)."""

    if client is None:
        return
    expires = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    items = [
        {
            "subject": f"asset:{asset_id}",
            "kind": "note_count",
            "status": "warning" if count >= 5 else "ok",
            "value": count,
            "summary": t("{count} notes", count=count),
            "expires_at": expires,  # stale (unknown) if the app stops sending
        }
        for asset_id, count in counts.items()
    ]
    try:
        receipt = client.put_results(items)  # up to 500 per request; larger lists are split
        for error in receipt.get("errors", []):
            LOGGER.warning("Result not saved: %s", error)
    except PlantCraftError as exc:
        LOGGER.warning("Results not sent: %s", exc)
```

Rules:

- One row per (app, subject, kind): a new one replaces it. PlantCraft keeps every change of
  status for 90 days.
- Set `expires_at` to about two run periods, so an app that stopped never leaves a green light.
- `score` (0 to 100, 100 best) and `usable` (other apps may trust this subject's data) are
  optional; leave them out rather than guess.
- An app that **reads** another app's result declares it in `[consumes]` and works, with a
  visible "not available", when that app is not installed or its result expired.

A computed time series (a score over time, a filtered flow) is a derived signal instead:
`client.put_series(...)` with `write = ["series"]`, read back by everyone like any other signal.
PlantCraft's `docs/app-standard.md`, section 6, has the details.
