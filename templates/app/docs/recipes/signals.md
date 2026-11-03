# Reading the plant: assets, signals and series

Plant data always comes from PlantCraft's API v1: the asset tree, the signals of each data
source, and their time series (from Historian when it is installed). An app keeps ids, never
copies, and reads what it needs when it needs it.

`app.toml`:

```toml
[permissions]
read = ["assets", "signals", "series"]
```

## As the person, for a page

A page reads with the person's own client, so PlantCraft's permissions decide what each person
sees. The example answers the mean of an asset's process value over the last hour:

```python
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from starter.api.deps import CurrentUser, RuntimeDep, guarded
from starter.i18n import t


@router.get("/assets/{asset_id}/pv")
def asset_pv(asset_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    client = rt.user_client(user)
    asset = guarded(lambda: client.asset(asset_id), service=False)  # 404 if it is not there
    signal = asset.get("signals", {}).get("pv")  # signals by role
    if not signal:
        raise HTTPException(422, t("{asset} has no process value.", asset=asset_id))
    end = datetime.now(UTC)
    series = guarded(
        lambda: client.series(signal, end - timedelta(hours=1), end, step=60), service=False
    )
    values = [v for v in series["v"] if isinstance(v, (int, float))]
    if len(values) < 10:
        # No silent wrong answers: say why there is no number.
        return {"signal": signal, "mean": None, "reason": t("Not enough data in the last hour.")}
    return {"signal": signal, "mean": sum(values) / len(values), "points": len(values)}
```

What the client gives you:

| Call | Answers |
|---|---|
| `client.assets()` | The asset tree the person may see |
| `client.asset(id)` | One asset: `name`, `kind`, `type_path`, `parent_id`, `attributes`, `signals` (role to signal id), `relations` |
| `client.signals()`, `client.signal(id)` | Signals: `name`, `source`, `unit`, `description`, limits |
| `client.series(id, start, end, step=None)` | `{"t": [...], "v": [...]}`: recorded values, or one mean per `step` seconds |
| `client.series_pandas(...)`, `client.series_frame(...)` | The same as pandas objects (UTC index) |
| `client.series_many(...)` | Many signals in one request |
| `client.value(id, ...)` | One aggregate (last, mean, min, max) over a window |

Times are UTC. A signal can be dead, frozen, full of gaps or in the wrong unit: check what you get
and answer "not usable" with a reason a person can act on, never an exception.

## As the app, in the background

Background work has no person, so it reads with `rt.service_client` (the app key), with the same
calls. That client is `None` without an app key; say so in the app's status instead of failing
([background.md](background.md)).

## Test

The fake PlantCraft's test plant has the Simulator's loops as assets (`FIC-1001` and others),
each with `pv`, `sp` and `op` signals and twelve hours of data ending at `tests.plant.NOW`.
Read the series around `NOW` in tests, not around the real clock:

```python
from tests.plant import NOW
```
