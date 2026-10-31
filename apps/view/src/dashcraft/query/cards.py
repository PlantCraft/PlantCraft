"""Turn a card into chart-ready data, reading only PlantCraft API v1.

Every problem with one signal (unknown asset, a role the asset lacks, a dead
source, a text signal on a trend) becomes that item's ``error``, worded for a
person, and the rest of the card still draws. Only a refused token (401) leaves
this module, so the caller can tell a person to sign in again.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.client import PlantCraftError, Unauthorized
from plantcraft_sdk.refs import asset_ref, signal_ref

from dashcraft.dashboards.fields import effective, finite_number, state_of
from dashcraft.dashboards.model import (
    ALL_ROLES,
    CONTEXT,
    TABLE_AGGREGATIONS,
    Card,
    CardItem,
    window_seconds,
)
from dashcraft.dashboards.variables import MAX_VALUES, interpolate, referenced, whole
from dashcraft.i18n import t
from dashcraft.query.apc import read_apc
from dashcraft.query.cache import TtlCache

# Signals one card reads at most once its variables and "every signal" items are expanded.
MAX_SIGNALS = 24
# Roles first in this order when a card shows every signal of an asset; the rest by name.
ROLE_ORDER = ("pv", "sp", "mv", "op", "out")
# Points per line in a trend: enough for a wide screen, small enough to draw at once.
TREND_POINTS = 600
NICE_STEPS = (
    1,
    2,
    5,
    10,
    15,
    30,
    60,
    120,
    300,
    600,
    900,
    1800,
    3600,
    7200,
    10800,
    21600,
    43200,
    86400,
)
# How far back to look for the newest sample when a trend window is empty (a recorded
# file, a source that stopped): a week first, then the longest window API v1 allows.
ANCHOR_WINDOWS = ("7d", "366d")


def trend_step(seconds: int) -> int:
    """The grid step of a trend over ``seconds``: a round number giving at most ~600 points."""

    raw = seconds / TREND_POINTS
    return next((step for step in NICE_STEPS if step >= raw), int(math.ceil(raw / 3600)) * 3600)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Reader:
    """API v1 reads for cards; with caches, one read serves every viewer for a while."""

    client: Any
    data_cache: TtlCache | None = None
    meta_cache: TtlCache | None = None
    clock: Callable[[], datetime] = field(default=_utc_now)
    # Answers this request already read in one batch (``results_of``), by ``result``'s key.
    known: dict[tuple[str, str], Any] = field(default_factory=dict)
    # Set when every read ends at a fixed past instant (a report of last week): values ask API
    # v1 for the window that closed then (``end``), series end there.
    closed_at: datetime | None = None

    def until(self, end: datetime) -> Reader:
        """This reader with every read ending at ``end``."""

        return replace(self, clock=lambda: end, closed_at=end, known={})

    def _cached(self, cache: TtlCache | None, key: tuple, load: Callable[[], Any]) -> Any:
        return cache.get(key, load) if cache is not None else load()

    def asset(self, asset_id: str) -> dict[str, Any]:
        return self._cached(
            self.meta_cache, ("asset", asset_id), lambda: self.client.asset(asset_id)
        )

    def assets(self, kind: str | None = None) -> list[dict[str, Any]]:
        return self._cached(
            self.meta_cache, ("assets", kind), lambda: self.client.assets(kind=kind)
        )

    def signal(self, signal_id: str) -> dict[str, Any]:
        return self._cached(
            self.meta_cache, ("signal", signal_id), lambda: self.client.signal(signal_id)
        )

    def value(self, signal_id: str, agg: str, window: str) -> dict[str, Any]:
        if self.closed_at is not None:
            end = self.closed_at
            return self._cached(
                self.data_cache,
                ("value", signal_id, agg, window, end.isoformat()),
                lambda: self.client.value(signal_id, agg=agg, window=window, end=end),
            )
        return self._cached(
            self.data_cache,
            ("value", signal_id, agg, window),
            lambda: self.client.value(signal_id, agg=agg, window=window),
        )

    def derived(self, subject: str, result: str) -> dict[str, Any] | None:
        """The series an app archives for ``result`` (``<app>.<name>``) about ``subject``.

        Apps write what they compute (a loop's health over time) to HistCraft as derived
        signals, listed by API v1 like any signal with ``app``, ``subject`` and ``result``.
        The id is PlantCraft's, never built here; numbers win over a text (status) series.
        """

        app, _, name = result.partition(".")
        found = list(
            self._cached(
                self.meta_cache,
                ("derived", app, subject, name),
                lambda: self.client.signals(app=app, subject=subject, result=name),
            )
        )
        found.sort(key=lambda signal: (signal.get("kind") or "number") != "number")
        return found[0] if found else None

    def result(self, subject: str, kind: str) -> dict[str, Any] | None:
        """The latest result of ``kind`` (``<app>.<name>``) about ``subject``, or None."""

        if (subject, kind) in self.known:
            return self.known[(subject, kind)]
        rows = self._cached(
            self.data_cache,
            ("result", subject, kind),
            lambda: self.client.results([subject], kind=kind),
        )
        return rows[0] if rows else None

    def results_of(self, subjects: list[str], kind: str) -> None:
        """The latest ``kind`` about many subjects in one request, for ``result`` to answer from;
        a subject the answer does not name is asked on its own later."""

        wanted = list(dict.fromkeys(subjects))
        rows = self._cached(
            self.data_cache,
            ("results", tuple(wanted), kind),
            lambda: list(self.client.results(wanted, kind=kind)),
        )
        for row in rows:
            if row.get("subject") in wanted:
                self.known[(row["subject"], kind)] = row

    def recent(self, signal_ids: list[str], seconds: int) -> dict[str, dict[str, Any]]:
        """Each signal's newest point of the last ``seconds``, from one raw batch read: what
        ``value(..., "last", ...)`` answers one signal at a time. A signal with no point in
        that time, or a failed one, is left out."""

        end = self.clock()
        batch = self._cached(
            self.data_cache,
            ("recent", tuple(signal_ids), seconds),
            lambda: self.client.series_many(
                signal_ids, end - timedelta(seconds=seconds), end, None
            ),
        )
        found: dict[str, dict[str, Any]] = {}
        for item in batch.get("series") or []:
            stamps, values = item.get("t") or [], item.get("v") or []
            if stamps and values and values[-1] is not None:
                found[item["signal"]] = {"value": values[-1], "at": stamps[-1]}
        return found

    def events(self, kind: str, limit: int) -> list[dict[str, Any]]:
        """The latest ``limit`` events of ``kind`` (oldest first, as API v1 answers)."""

        return self._cached(
            self.data_cache,
            ("events", kind, limit),
            lambda: list(self.client.events(kind=kind, limit=limit)),
        )

    def event_titles(self) -> dict[str, str]:
        """Each declared event's title by its kind (``alarmcraft.alarm.raised``: "Alarm raised")."""

        def load() -> dict[str, str]:
            titles: dict[str, str] = {}
            for app in self.client.event_catalog() or []:
                for spec in app.get("events") or []:
                    kind = spec.get("kind") or f"{app.get('app')}.{spec.get('name')}"
                    titles[str(kind)] = str(spec.get("title") or kind)
            return titles

        return self._cached(self.meta_cache, ("event-titles",), load)

    def series(
        self, signal_ids: list[str], start: datetime, end: datetime, step: int
    ) -> dict[str, Any]:
        # Cached on the step-rounded window, so viewers a few seconds apart share one read.
        bucket = int(end.timestamp() // max(step, 1))
        key = ("series", tuple(signal_ids), int((end - start).total_seconds()), step, bucket)
        return self._cached(
            self.data_cache, key, lambda: self.client.series_many(signal_ids, start, end, step)
        )


def derived_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The signals apps computed (they name their ``app`` and ``result``), not plant ones."""

    return [signal for signal in signals if signal.get("app") and signal.get("result")]


def _problem(exc: PlantCraftError) -> str:
    if exc.status_code == 403:
        return t(
            "PlantCraft does not let this dashboard read the signal: {detail}", detail=exc.detail
        )
    if exc.status_code == 404:
        return t("Not found in PlantCraft.")
    return str(exc.detail)


@dataclass
class Resolved:
    label: str
    signal_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    role: str | None = None
    asset: str | None = None

    def base(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "signal": self.signal_id,
            "role": self.role,
            "asset": self.asset,
            "unit": self.meta.get("unit") or "",
            "kind": self.meta.get("kind") or "number",
            "low": self.meta.get("low"),
            "high": self.meta.get("high"),
            "error": self.error,
        }


@dataclass
class Concrete:
    """A card item with its variables filled in: one asset or signal, one role.

    ``short``: the label leaves out the asset (one asset picked at the top, as before
    variables: "PV", not "FIC-101 PV"). ``error``: why it cannot be read (no value picked).
    """

    item: CardItem
    short: bool = False
    error: str | None = None
    # Shown on the item although it reads (more signals were cut).
    note: str | None = None


def ordered_roles(signals: dict[str, Any], wanted: list[str]) -> list[str]:
    """The roles an "every signal" item shows: those asked for, in that order, else all the
    asset has, PV, SP and MV first."""

    if wanted:
        return [role for role in wanted if role in signals] or wanted
    rank = {role: index for index, role in enumerate(ROLE_ORDER)}
    return sorted(signals, key=lambda role: (rank.get(role.lower(), len(rank)), role.lower()))


def concrete_items(
    reader: Reader,
    items: list[CardItem],
    values: dict[str, list[str]],
    labels: dict[str, str] | None = None,
    texts: dict[str, list[str]] | None = None,
) -> list[Concrete]:
    """Each item for each value of the variables it names, and each role of an "every
    signal" item; at most ``MAX_SIGNALS`` (a note on the last when more were cut)."""

    labels = labels or {}
    texts = texts if texts is not None else values
    out: list[Concrete] = []
    for item in items:
        name = whole(item.asset_id) if item.asset_id != CONTEXT else None
        # (asset, short label, the variables' values as this one item shows them)
        assets: list[tuple[str | None, bool, dict[str, list[str]]]]
        if name is not None:
            picked = list(values.get(name) or [])[:MAX_VALUES]
            if not picked:
                what = labels.get(name) or t("an asset")
                error = t("Pick {what} at the top of the dashboard.", what=what)
                out.append(Concrete(item, True, error))
                continue
            shown = list(texts.get(name) or picked)
            assets = [
                (asset, len(picked) == 1, {name: [shown[index] if index < len(shown) else asset]})
                for index, asset in enumerate(picked)
            ]
        else:
            assets = [(item.asset_id, item.asset_id == CONTEXT, {})]
        signals: list[tuple[str | None, dict[str, list[str]]]] = [(item.signal_id, {})]
        if item.signal_id and referenced(item.signal_id):
            signals = _signal_values(item.signal_id, values)
        for asset_id, short, own in assets:
            for signal_id, local in signals:
                label = interpolate(item.label, {**texts, **own, **local}) if item.label else ""
                if label and own and not short and not referenced(item.label):
                    # Several assets under one typed label: each says which asset it is.
                    label = f"{next(iter(own.values()))[0]} {label}"
                one = item.model_copy(
                    update={"asset_id": asset_id, "signal_id": signal_id, "label": label}
                )
                if item.every_role:
                    out.extend(_every_role(reader, one, short))
                else:
                    out.append(Concrete(one, short))
    if len(out) > MAX_SIGNALS:
        cut = out[:MAX_SIGNALS]
        last = cut[-1]
        cut[-1] = Concrete(
            last.item, last.short, last.error, t("Showing the first {n} signals.", n=MAX_SIGNALS)
        )
        return cut
    return out


def _signal_values(
    template: str, values: dict[str, list[str]]
) -> list[tuple[str | None, dict[str, list[str]]]]:
    """A signal id with ``${tag}`` for each value of the variables it names, and those values."""

    found: list[tuple[str, dict[str, list[str]]]] = [(template, {})]
    for name in sorted(referenced(template)):
        choices = list(values.get(name) or [])[:MAX_VALUES]
        if not choices:
            continue
        found = [
            (interpolate(text, {name: [choice]}), {**local, name: [choice]})
            for text, local in found
            for choice in choices
        ]
    return list(found[:MAX_SIGNALS])


def _every_role(reader: Reader, item: CardItem, short: bool) -> list[Concrete]:
    asset_id = item.asset_id or ""
    try:
        asset = reader.asset(asset_id)
    except Unauthorized:
        raise
    except PlantCraftError as exc:
        missing = (
            t("Asset {asset} not found.", asset=asset_id)
            if exc.status_code == 404
            else _problem(exc)
        )
        return [Concrete(item.model_copy(update={"role": "*"}), short, missing)]
    roles = ordered_roles(asset.get("signals") or {}, item.roles)
    if not roles:
        name = asset.get("name") or asset_id
        return [Concrete(item, short, t("{asset} has no signals.", asset=name))]
    return [
        Concrete(
            item.model_copy(
                update={
                    "role": role,
                    "roles": [],
                    "label": item.label and f"{item.label} {role.upper()}",
                }
            ),
            short,
        )
        for role in roles
    ]


def resolve(
    reader: Reader, item: Any, context: str | None = None, short: bool | None = None
) -> Resolved:
    """The signal a card item names, its metadata and a label; problems become ``error``."""

    if item.result is not None:
        return _resolve_derived(reader, item, context, short)
    short = item.asset_id == CONTEXT if short is None else short
    label = item.label
    signal_id = item.signal_id
    asset_id = context if item.asset_id == CONTEXT else item.asset_id
    if signal_id is None:
        role_name = (item.role or "").upper()
        if not asset_id:
            return Resolved(
                label or role_name,
                error=t("Pick an asset at the top of the dashboard."),
                role=item.role,
            )
        try:
            asset = reader.asset(asset_id)
        except Unauthorized:
            raise
        except PlantCraftError as exc:
            message = (
                t("Asset {asset} not found.", asset=asset_id)
                if exc.status_code == 404
                else _problem(exc)
            )
            return Resolved(label or role_name, error=message, role=item.role, asset=asset_id)
        name = asset.get("name") or asset_id
        signal_id = (asset.get("signals") or {}).get(item.role or "")
        if not signal_id:
            return Resolved(
                label or f"{name} {role_name}",
                error=t("{asset} has no {role} signal.", asset=name, role=role_name),
                role=item.role,
                asset=asset_id,
            )
        label = label or (role_name if short else f"{name} {role_name}")
    try:
        meta = reader.signal(signal_id)
    except Unauthorized:
        raise
    except PlantCraftError as exc:
        message = (
            t("Signal {signal} not found.", signal=signal_id)
            if exc.status_code == 404
            else _problem(exc)
        )
        return Resolved(
            label or signal_id, signal_id, error=message, role=item.role, asset=asset_id
        )
    meta = {**meta, "kind": meta.get("kind") or "number"}
    return Resolved(
        label or meta.get("name") or signal_id, signal_id, meta, role=item.role, asset=asset_id
    )


def _resolve_derived(
    reader: Reader, item: Any, context: str | None, short: bool | None
) -> Resolved:
    """A result item on a trend: the history its app archives in HistCraft."""

    app, _, name = item.result.partition(".")
    what = name.replace("_", " ")
    short = item.asset_id == CONTEXT if short is None else short
    asset_id = context if item.asset_id == CONTEXT else item.asset_id
    if item.signal_id is not None:
        subject, label = signal_ref(item.signal_id), item.label or f"{item.signal_id} {what}"
    else:
        if not asset_id:
            return Resolved(
                item.label or what, error=t("Pick an asset at the top of the dashboard.")
            )
        try:
            asset = reader.asset(asset_id)
        except Unauthorized:
            raise
        except PlantCraftError as exc:
            missing = t("Asset {asset} not found.", asset=asset_id)
            return Resolved(
                item.label or what,
                error=missing if exc.status_code == 404 else _problem(exc),
                asset=asset_id,
            )
        subject = asset_ref(asset_id)
        label = item.label or (what if short else f"{asset.get('name') or asset_id} {what}")
    try:
        found = reader.derived(subject, item.result)
    except Unauthorized:
        raise
    except PlantCraftError as exc:
        return Resolved(label, error=_problem(exc), asset=asset_id)
    if found is None:
        return Resolved(
            label,
            error=t("{app} keeps no history of {kind} here yet.", app=app, kind=what),
            asset=asset_id,
        )
    meta = {**found, "kind": found.get("kind") or "number"}
    return Resolved(label, str(found["id"]), meta, asset=asset_id)


def result_subject(item: Any, context: str | None = None) -> str | None:
    """The subject ``read_result`` asks about for ``item``: its signal, else its asset."""

    if item.signal_id is not None:
        return signal_ref(item.signal_id)
    asset_id = context if item.asset_id == CONTEXT else item.asset_id
    return asset_ref(asset_id) if asset_id else None


def read_result(
    reader: Reader, item: Any, context: str | None = None, short: bool | None = None
) -> dict[str, Any]:
    """A row for an app result item: its score (or value), the producer's status and summary.

    The status is the producing app's own verdict (ok, warning, alarm, unknown; an expired result
    reads unknown): DashCraft shows it as it is and never recomputes it from limits.
    """

    app, _, name = item.result.partition(".")
    short = item.asset_id == CONTEXT if short is None else short
    asset_id = context if item.asset_id == CONTEXT else item.asset_id
    row: dict[str, Any] = {
        "label": item.label or name.replace("_", " "),
        "signal": None,
        "role": None,
        "asset": asset_id,
        "unit": "",
        "kind": "result",
        "low": None,
        "high": None,
        "error": None,
        "value": None,
        "at": None,
        "agg": "result",
        "state": "unknown",
        "summary": "",
        "result": item.result,
    }
    if item.signal_id is not None:
        subject = signal_ref(item.signal_id)
        row["label"] = item.label or f"{item.signal_id} {row['label']}"
    else:
        if not asset_id:
            return {**row, "error": t("Pick an asset at the top of the dashboard.")}
        try:
            asset = reader.asset(asset_id)
        except Unauthorized:
            raise
        except PlantCraftError as exc:
            missing = t("Asset {asset} not found.", asset=asset_id)
            return {**row, "error": missing if exc.status_code == 404 else _problem(exc)}
        if not short and not item.label:
            row["label"] = f"{asset.get('name') or asset_id} {row['label']}"
        subject = asset_ref(asset_id)
    try:
        found = reader.result(subject, item.result)
    except Unauthorized:
        raise
    except PlantCraftError as exc:
        return {**row, "error": _problem(exc)}
    if found is None:
        return {
            **row,
            "error": t(
                "{app} has published no {kind} here yet (not installed, or not run).",
                app=app,
                kind=name,
            ),
        }
    score = finite_number(found.get("score"))
    status = "unknown" if found.get("stale") else str(found.get("status") or "unknown")
    return {
        **row,
        "value": score if score is not None else finite_number(found.get("value")),
        "unit": "/100" if score is not None else "",
        "at": found.get("at"),
        "state": status if status in ("ok", "warning", "alarm") else "unknown",
        "summary": str(found.get("summary") or ""),
        "stale": bool(found.get("stale")),
        "priority": None if found.get("stale") else _worst_priority(found.get("detail")),
    }


PRIORITY_ORDER = ("critical", "high", "medium", "low")


def _worst_priority(detail: Any) -> str | None:
    """The most urgent priority among a result's active alarms (``detail.active[].priority``,
    as Alarms publishes ``alarm_state``), so a diagram can draw its alarm mark by priority."""

    if not isinstance(detail, dict) or not isinstance(detail.get("active"), list):
        return None
    found = {item.get("priority") for item in detail["active"] if isinstance(item, dict)}
    return next((p for p in PRIORITY_ORDER if p in found), None)


def _value(reader: Reader, resolved: Resolved, agg: str, window: str) -> dict[str, Any]:
    if resolved.meta.get("kind") == "text":
        agg = "last"
    try:
        answer = reader.value(resolved.signal_id or "", agg, window)
    except Unauthorized:
        raise
    except PlantCraftError as exc:
        return {"value": None, "at": None, "error": _problem(exc)}
    return {"value": answer.get("value"), "at": answer.get("at"), "error": None}


def _resolved(reader: Reader, one: Concrete) -> Resolved:
    if one.error is not None:
        role = None if one.item.role == ALL_ROLES else one.item.role
        label = one.item.label or (role or "").upper() or t("Signal")
        return Resolved(label, error=one.error, role=role, asset=one.item.asset_id)
    found = resolve(reader, one.item, None, one.short)
    if one.note and found.error is None:
        found.error = one.note
    return found


def _state(card: Card, row: dict[str, Any], value: Any) -> str:
    return state_of(effective(card.field, card.overrides, row), value, row)


def read_values(
    reader: Reader, card: Card, items: list[Concrete], window: str
) -> list[dict[str, Any]]:
    """Stat, gauge and bar cards: one value per item, coloured by the card's thresholds."""

    rows = []
    for one in items:
        item = one.item
        if item.result and one.error is None:
            rows.append(read_result(reader, item, None, one.short))
            continue
        resolved = _resolved(reader, one)
        row = {**resolved.base(), "value": None, "at": None, "agg": card.agg}
        if resolved.error is None:
            agg = "last" if resolved.meta.get("kind") == "text" else card.agg
            got = _value(reader, resolved, agg, window)
            row.update(got)
            row["agg"] = agg
            row["error"] = got["error"]
        row["state"] = _state(card, row, row.get("value"))
        rows.append(row)
    return rows


def read_table(
    reader: Reader, card: Card, items: list[Concrete], window: str
) -> list[dict[str, Any]]:
    """Table cards: the columns the card shows (last, mean, min, max, std) of each item."""

    wanted = [agg for agg in TABLE_AGGREGATIONS if agg in card.options.columns or agg == "last"]
    rows = []
    for one in items:
        item = one.item
        if item.result and one.error is None:
            found = read_result(reader, item, None, one.short)
            rows.append({**found, "values": {"last": found["value"]}})
            continue
        resolved = _resolved(reader, one)
        row = {**resolved.base(), "values": {}, "at": None}
        if resolved.error is None:
            aggs = ("last",) if resolved.meta.get("kind") == "text" else wanted
            for agg in aggs:
                got = _value(reader, resolved, agg, window)
                if got["error"]:
                    row["error"] = got["error"]
                    break
                row["values"][agg] = got["value"]
                if agg == "last":
                    row["at"] = got["at"]
        row["state"] = _state(card, row, row["values"].get("last"))
        rows.append(row)
    return rows


def read_trend(
    reader: Reader, card: Card, items: list[Concrete] | str | None = None, window: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Trend cards: one line per numeric item on a regular grid ending now.

    When every line comes back empty (a recorded file, a source that stopped),
    the window is moved to end at the newest sample, so the card still shows
    the latest data it can; ``range.shifted`` tells the viewer.
    """

    if items is None or isinstance(items, str):
        # The call before variables: (reader, card, context, window).
        values = {"asset": [items]} if isinstance(items, str) else {}
        items = concrete_items(reader, card.items, values)
    window = window or card.window
    seconds = window_seconds(window)
    step = trend_step(seconds)
    resolved = [_resolved(reader, one) for one in items]
    lines = []
    wanted: list[str] = []
    for item in resolved:
        line = {**item.base(), "t": [], "v": []}
        if item.error is None and item.meta.get("kind") == "text":
            line["error"] = t("A text signal has no line: show it on a stat or table panel.")
        elif item.error is None and item.signal_id:
            wanted.append(item.signal_id)
        lines.append(line)
    end = reader.clock()
    shifted = False
    answers: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    if wanted:
        batch = _batch(reader, wanted, end - timedelta(seconds=seconds), end, step)
        if batch is None:
            failures = {signal: t("PlantCraft could not be reached.") for signal in wanted}
        else:
            answers, failures = batch
            if not failures and not any(
                any(v is not None for v in item.get("v") or []) for item in answers.values()
            ):
                anchor = _newest_sample(reader, wanted)
                if anchor is not None and anchor < end - timedelta(seconds=step):
                    moved = _batch(
                        reader, wanted, anchor - timedelta(seconds=seconds), anchor, step
                    )
                    if moved is not None:
                        answers, failures = moved
                        end, shifted = anchor, True
    for line, item in zip(lines, resolved, strict=True):
        if line["error"] or not item.signal_id:
            continue
        if item.signal_id in failures:
            line["error"] = failures[item.signal_id]
            continue
        answer = answers.get(item.signal_id) or {}
        line["t"], line["v"] = answer.get("t") or [], answer.get("v") or []
    start = end - timedelta(seconds=seconds)
    return lines, {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": step,
        "shifted": shifted,
    }


def _batch(
    reader: Reader, signals: list[str], start: datetime, end: datetime, step: int
) -> tuple[dict[str, dict[str, Any]], dict[str, str]] | None:
    try:
        batch = reader.series(signals, start, end, step)
    except Unauthorized:
        raise
    except PlantCraftError:
        return None
    answers = {item["signal"]: item for item in batch.get("series") or []}
    failures = {
        item["signal"]: t("Not found in PlantCraft.")
        if item.get("status") == 404
        else str(item.get("detail") or "")
        for item in batch.get("errors") or []
    }
    return answers, failures


def _newest_sample(reader: Reader, signals: list[str]) -> datetime | None:
    newest = None
    for signal_id in signals:
        answer: dict[str, Any] = {}
        for window in ANCHOR_WINDOWS:
            try:
                answer = reader.value(signal_id, "last", window)
            except Unauthorized:
                raise
            except PlantCraftError:
                answer = {}
                continue
            if answer.get("value") is not None:
                break
        if answer.get("value") is None or not answer.get("at"):
            continue
        try:
            stamp = datetime.fromisoformat(str(answer["at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        newest = stamp if newest is None or stamp > newest else newest
    return newest


def card_window(card: Card, values: dict[str, list[str]], window: str | None = None) -> str:
    """The window a card reads: the dashboard's Time picker, else its own (an interval
    variable's value when it names one)."""

    if window:
        return window
    name = whole(card.window)
    if name is None:
        return card.window
    picked = [value for value in values.get(name) or [] if value]
    return picked[0] if picked else "1h"


def read_card(
    reader: Reader,
    card: Card,
    context: str | None = None,
    window: str | None = None,
    *,
    values: dict[str, list[str]] | None = None,
    labels: dict[str, str] | None = None,
    texts: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """The data of one card. ``window`` overrides the card's own (the dashboard's time picker);
    ``values`` are the variables picked at the top (``context``: the old dashboard's asset, the
    variable ``asset``)."""

    values = dict(values or {})
    if context and "asset" not in values:
        values["asset"] = [context]
    window = card_window(card, values, window)
    items = concrete_items(reader, card.items, values, labels, texts)
    result: dict[str, Any] = {"card_id": card.card_id, "kind": card.kind, "window": window}
    if card.kind in {"trend", "scatter"}:
        result["lines"], result["range"] = read_trend(reader, card, items, window)
    elif card.kind == "apc":
        result["apc"] = read_apc(reader, card.apc_id.strip(), window)
    elif card.kind in ("text", "diagram"):
        # A diagram card's drawing and values come from the diagram it names, which the api
        # layer reads as its viewer may (``api.views.diagram_card``, a layer above this one).
        pass
    elif card.kind == "table":
        result["rows"] = read_table(reader, card, items, window)
    else:
        result["agg"] = card.agg
        result["rows"] = read_values(reader, card, items, window)
        if card.kind == "stat" and card.options.graph == "area":
            result["lines"], result["range"] = read_trend(reader, card, items, window)
    result["read_at"] = reader.clock().isoformat()
    return result
