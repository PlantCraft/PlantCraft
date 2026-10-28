"""The signal picker's answer (scale review A5): one ranking for every app's ``/api/signals``.

The ui's ``SignalSearch`` asks the app it is drawn in ``GET <prefix>/api/signals?q=<text>``; the
app reads PlantCraft's signals with the person's own token and answers with
``signal_choices``, so PlantCraft decides what they can see and every app lists the same
signals in the same order::

    from plantcraft_sdk.server.picker import signal_choices

    @router.get("/api/signals")
    def list_signals(rt: RuntimeDep, user: EditorUser, q: str = Query("", max_length=120),
                     limit: int = Query(30, ge=1, le=200)) -> list[dict]:
        found = guarded(lambda: rt.user_client(user).signals(q.strip() or None), service=False)
        return signal_choices(found, q, limit=limit, numbers_only=True)

Plant signals come before the series apps derived (``app-<app id>:...``), then the exact, the
prefix and the other matches of the tag or name; PlantCraft's order is kept within each group.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from plantcraft_sdk.derived import SOURCE_PREFIX

__all__ = ["CHOICE_FIELDS", "is_derived", "rank_signals", "signal_choices"]

#: What a picker shows of a signal.
CHOICE_FIELDS = ("id", "name", "unit", "description", "kind", "source", "low", "high")


def is_derived(item: Mapping[str, Any]) -> bool:
    """A series an app computed (source ``app-<app id>``), not a plant signal."""

    return bool(item.get("app")) or str(item.get("source") or "").startswith(SOURCE_PREFIX)


def _match_rank(item: Mapping[str, Any], query: str) -> int:
    """0 exact, 1 prefix, 2 anywhere: of the tag (the id without its source) or the name."""

    signal_id = str(item.get("id") or "")
    words = {
        signal_id.lower(),
        signal_id.partition(":")[2].lower(),
        str(item.get("name") or "").lower(),
    }
    words.discard("")
    if query in words:
        return 0
    if any(word.startswith(query) for word in words):
        return 1
    return 2


def rank_signals(found: Iterable[Mapping[str, Any]], query: str) -> list[Mapping[str, Any]]:
    """Plant signals first, then exact, prefix and other matches; stable within each group."""

    text = query.strip().lower()
    return sorted(
        found, key=lambda item: (is_derived(item), _match_rank(item, text) if text else 0)
    )


def signal_choices(
    found: Iterable[Mapping[str, Any]],
    query: str = "",
    *,
    limit: int = 30,
    numbers_only: bool = False,
    fields: Sequence[str] = CHOICE_FIELDS,
) -> list[dict[str, Any]]:
    """The first ``limit`` signals of ``found`` in the picker's order, with ``fields`` only
    (``name`` falls back to the id, ``unit`` and ``description`` to ""); ``numbers_only``
    leaves text signals out (a rule's or a model's input is a number)."""

    kept = [
        item for item in found if not numbers_only or (item.get("kind") or "number") == "number"
    ]
    answer = []
    for item in rank_signals(kept, query)[:limit]:
        row = {key: item.get(key) for key in fields}
        if "name" in row:
            row["name"] = item.get("name") or item.get("id")
        for key in ("unit", "description"):
            if key in row:
                row[key] = item.get(key) or ""
        answer.append(row)
    return answer
