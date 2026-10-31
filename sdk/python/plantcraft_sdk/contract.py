"""Shapes and rules of PlantCraft API v1 shared by the server, the client and the fake.

``docs/api-v1.md`` is the contract; this module holds the parts code needs in
more than one place (limits, ``window`` parsing, aggregations, how a series is
written) so PlantCraft, ``plantcraft_sdk.client`` and
``plantcraft_sdk.testing`` cannot drift apart.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

import numpy as np
import pandas as pd

from plantcraft_sdk.i18n import t

ISSUER = "processcraft"
# The audience of tokens PlantCraft itself accepts; apps also accept their own id.
CENTRAL_AUDIENCE = "processcraft"
TOKEN_COOKIE = "processcraft_token"
USER_TOKEN_SECONDS = 15 * 60
SERVICE_TOKEN_SECONDS = 60 * 60
# Tokens PlantCraft ended before they expire (a person disabled, a new password or access, an
# app key revoked), for apps that verify offline: ``{"users": [{"sub_sha256", "not_before"}],
# "keys": [{"key_id", "revoked_at"}]}``. Entries stay listed as long as a token could still live.
REVOKED_PATH = "/api/v1/auth/revoked"
LEVELS = ("dashboards", "viewer", "editor", "admin")
APP_ACCESS = ("viewer", "editor")
AGGREGATIONS = ("last", "mean", "min", "max", "std")
# What a signal holds: numbers, or text labels such as controller modes ("AUTO", "MAN").
KINDS = ("number", "text")
MAX_POINTS = 200_000
# A regular grid holds a signal's last value into empty steps (step-hold) for at most this
# many times the larger of ``step`` and the signal's usual spacing between samples; past that
# the source is taken as silent (an outage) and the steps stay null (docs/api-v1.md, series).
# Signals recorded on change (``recorded_on_change``) have no such limit.
HOLD_STEPS = 10
# Signals recorded on change: a text signal (a mode's labels) or one whose tag ends in one of
# these words (``FIC-101.SP``, ``scenario:mode``). A source writes them only when they change,
# so their spacing says nothing about an outage: their hold has no limit (``on_change``).
ON_CHANGE_NAMES = frozenset({"SP", "SETPOINT", "MODE"})
_LAST_WORD = re.compile(r"[^A-Za-z0-9]+")
# ``POST /api/v1/series``: signals per request, and points across all of its series. Signals
# past the points budget are answered with a 413 error each: ask for them in another request.
MAX_BATCH_SIGNALS = 500
# A list route answers in pages when asked (``plantcraft_sdk.server.paging``): at most
# MAX_PAGE items, the next page's cursor in this header, the whole count in TOTAL_COUNT.
MAX_PAGE = 5000
NEXT_CURSOR = "X-Next-Cursor"
TOTAL_COUNT = "X-Total-Count"
MAX_BATCH_POINTS = 2_000_000
BATCH_FULL_STATUS = 413
# The longest span one series or value request may cover.
MAX_SPAN = timedelta(days=366)
DEFAULT_SPAN = timedelta(hours=24)

_WINDOW = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class ContractError(ValueError):
    """A request value breaks the contract; the message is shown to the caller (422)."""


# Typed shapes ------------------------------------------------------------------


class Jwk(TypedDict):
    kid: str
    kty: str
    crv: str
    x: str


class TokenGrant(TypedDict):
    token: str
    expires_at: str


class Me(TypedDict):
    username: str
    name: str
    level: str
    apps: dict[str, str]


class App(TypedDict):
    id: str
    name: str
    url: str
    access: str
    version: str | None


class AssetRelation(TypedDict):
    type: str  # controls, measures, feeds, downstream_of
    to: str


class Asset(TypedDict):
    id: str
    name: str
    kind: str
    # Root type first, the asset's own type (= kind) last. Added 2026-10-20.
    type_path: list[str]
    parent_id: str | None
    # description, kind_label, origin and the record's values by attribute key.
    attributes: dict[str, Any]
    signals: dict[str, str]
    # Outgoing relations. Added 2026-10-20.
    relations: list[AssetRelation]


class AssetAttribute(TypedDict):
    key: str
    name: str
    data_type: str  # text, number, choice, date, asset
    unit: str
    required: bool
    default: Any
    options: list[str]


class AssetRole(TypedDict):
    key: str
    name: str
    unit: str
    required: bool


class AssetType(TypedDict):
    id: str
    name: str
    description: str
    icon: str
    parent: str | None
    path: list[str]
    attributes: list[AssetAttribute]
    roles: list[AssetRole]
    children: list[str]


class Signal(TypedDict):
    id: str
    name: str
    source: str
    unit: str
    description: str
    low: float | None
    high: float | None
    kind: str


class DerivedSignal(Signal, total=False):
    """A signal an app published with ``PUT /api/v1/series`` (``source`` is ``app-<app id>``).

    With HistCraft as the data layer any signal may also carry ``mode``
    (``source``, ``archive`` or ``both``).
    """

    app: str
    subject: str | None
    result: str | None
    mode: str


class Series(TypedDict):
    signal: str
    kind: str
    t: list[str]
    v: list[float | str | None]


class SeriesError(TypedDict):
    signal: str
    status: int
    detail: str


class SeriesBatch(TypedDict):
    series: list[Series]
    errors: list[SeriesError]


class Value(TypedDict):
    signal: str
    agg: str
    window: str
    value: float | str | None
    at: str | None


class AuditReceipt(TypedDict):
    id: int


# Rules -------------------------------------------------------------------------


def parse_window(text: str | None) -> timedelta:
    """``"1h"``, ``"24h"``, ``"7d"``, ``"30m"``, ``"90s"`` as a positive duration up to 366 days."""

    match = _WINDOW.match(text or "")
    if not match:
        raise ContractError(t("Invalid window: use a number and a unit, like 30m, 1h, 24h or 7d."))
    seconds = float(match.group(1)) * _UNITS[match.group(2)]
    if seconds <= 0:
        raise ContractError(t("The window must be longer than zero."))
    if seconds > MAX_SPAN.total_seconds():
        raise ContractError(t("The window can cover at most 366 days."))
    return timedelta(seconds=seconds)


def parse_time(value: str | datetime | None, name: str) -> datetime | None:
    """An ISO 8601 instant as an aware UTC datetime; a time without offset is taken as UTC."""

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError(
                t("Invalid {name}: use ISO 8601, like 2026-10-19T08:00:00Z.", name=name)
            ) from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def series_range(
    start: str | datetime | None,
    end: str | datetime | None,
    step: float | None,
    *,
    default_end: datetime,
) -> tuple[datetime, datetime, float | None]:
    """The checked ``(start, end, step)`` of a series request (UTC)."""

    end_at = parse_time(end, "end") or default_end.astimezone(timezone.utc)
    start_at = parse_time(start, "start") or end_at - DEFAULT_SPAN
    if start_at >= end_at:
        raise ContractError(t("start must come before end."))
    if end_at - start_at > MAX_SPAN:
        raise ContractError(t("A series can cover at most 366 days."))
    if step is not None:
        if not math.isfinite(step) or step <= 0:
            raise ContractError(t("step must be a positive number of seconds."))
        if (end_at - start_at).total_seconds() / step > MAX_POINTS:
            raise ContractError(
                t(
                    "Too many points: at most {count} per request. Use a larger step.",
                    count=MAX_POINTS,
                )
            )
    return start_at, end_at, step


def iso(stamp: Any) -> str:
    """An instant as ISO 8601 UTC with offset."""

    value = pd.Timestamp(stamp)
    value = value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
    return value.isoformat()


class _Recent:
    """A small, thread-safe memo of the last few results (series of one read share times)."""

    def __init__(self, size: int = 16):
        self.size = size
        self._items: OrderedDict[Any, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        with self._lock:
            found = self._items.get(key)
            if found is not None:
                self._items.move_to_end(key)
            return found

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)


_ISO_MEMO = _Recent()
_PARSE_MEMO = _Recent()
# Longer series are not memoized (memory stays bounded).
_MEMO_POINTS = 20_000


def iso_many(index: Any) -> list[str]:
    """``iso`` of every instant of ``index`` (naive means UTC), vectorized for whole seconds.

    The signals of one read usually share their times, so the last few answers are memoized.
    """

    stamps = pd.DatetimeIndex(index)
    if not len(stamps):
        return []
    stamps = stamps.tz_localize("UTC") if stamps.tz is None else stamps.tz_convert("UTC")
    naive = stamps.tz_localize(None).as_unit("ns")
    nanos = naive.asi8
    key = (len(nanos), nanos.tobytes()) if len(nanos) <= _MEMO_POINTS else None
    found = _ISO_MEMO.get(key) if key is not None else None
    if found is not None:
        return list(found)
    fraction = nanos % 1_000_000_000
    if stamps.hasnans or (fraction % 1000).any():
        # Missing or nanosecond instants: written one by one, exactly as ``iso`` does.
        text = [iso(stamp) for stamp in stamps]
    else:
        # Whole seconds without a fraction, the others with microseconds, as ``iso`` writes
        # them; one by one this was most of a raw read of millisecond samples (0.6.0 load test).
        moments = naive.to_numpy()
        whole = fraction == 0
        written = np.empty(len(moments), dtype=object)
        if whole.any():
            written[whole] = np.datetime_as_string(moments[whole].astype("datetime64[s]"), unit="s")
        if not whole.all():
            written[~whole] = np.datetime_as_string(
                moments[~whole].astype("datetime64[us]"), unit="us"
            )
        text = [item + "+00:00" for item in written.tolist()]
    if key is not None:
        _ISO_MEMO.put(key, text)
    return list(text)


def parse_times(values: list[str]) -> pd.DatetimeIndex:
    """``t`` of a v1 series as a UTC DatetimeIndex (fast path for the ``+00:00`` PlantCraft writes).

    Series read together usually share their times: the last few answers are memoized.
    """

    if not values:
        return pd.DatetimeIndex([], tz="UTC")
    try:
        key = (len(values), values[0], values[-1])
        found = _PARSE_MEMO.get(key)
        if found is not None and found[0] == values:
            return found[1]
    except TypeError:
        key = None
    parsed: pd.DatetimeIndex | None = None
    try:
        if all(value.endswith("+00:00") for value in values):
            naive = np.array([value[:-6] for value in values], dtype="datetime64[ns]")
            parsed = pd.DatetimeIndex(naive).tz_localize("UTC")
    except (AttributeError, TypeError, ValueError):
        parsed = None
    if parsed is None:
        parsed = pd.DatetimeIndex(pd.to_datetime(list(values), utc=True, format="ISO8601"))
    if key is not None and len(values) <= _MEMO_POINTS:
        _PARSE_MEMO.put(key, (list(values), parsed))
    return parsed


def kind_of(item: Any) -> str:
    """``"text"`` or ``"number"`` from a signal's ``kind`` (or a source's ``data_type``)."""

    return "text" if str(item or "").strip().lower() in {"text", "string", "str"} else "number"


def text_label(value: Any) -> str | None:
    """One text sample as a label: numbers without a needless ``.0``, blanks and NaN as None."""

    if value is None or isinstance(value, bool | np.bool_):
        return None if value is None else str(bool(value))
    if isinstance(value, int | np.integer):
        return str(int(value))
    if isinstance(value, float | np.floating):
        if not math.isfinite(float(value)):
            return None
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    if value is pd.NaT:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def recorded_on_change(signal_id: str, kind: str = "number") -> bool:
    """Whether a signal is recorded on change (a setpoint or a mode), so its step-hold has
    no limit: a text signal, or a tag whose last word is in ``ON_CHANGE_NAMES``."""

    if kind == "text":
        return True
    words = [word for word in _LAST_WORD.split(str(signal_id)) if word]
    return bool(words) and words[-1].upper() in ON_CHANGE_NAMES


def shape_series(
    values: pd.Series,
    start: datetime,
    end: datetime,
    step: float | None,
    *,
    now: datetime | None = None,
    on_change: bool = False,
) -> tuple[list[str], list[float | None]]:
    """Recorded values (``step`` None) or one value per ``step`` seconds, as ``t`` and ``v``.

    ``values`` has a UTC (or naive UTC) DatetimeIndex. Recorded values keep
    only the samples inside ``[start, end]``. A regular grid starts at
    ``start``: each point is the mean of the samples in ``[t, t + step)``; a
    step without samples holds the last value before it (``hold_positions``),
    else it is ``None``. A sample before ``start`` (a reader's look-back
    point) only seeds that hold. A null sample (NaN, or text that is not a
    number) says "no value" and ends the hold; callers drop the NaN a wide
    read leaves where a signal has no sample at all. ``on_change`` (a signal
    recorded on change, ``recorded_on_change``) holds without ``hold_limit``.
    """

    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    numeric = _utc_index(numeric)
    numeric = numeric.loc[numeric.index <= end]
    if step is None:
        numeric = numeric.loc[numeric.index >= start].dropna()
        if len(numeric) > MAX_POINTS:
            raise ContractError(
                t(
                    "Too many recorded values: at most {count} per request. Give a step.",
                    count=MAX_POINTS,
                )
            )
        return iso_many(numeric.index), _numbers(numeric.to_numpy())
    grid = pd.date_range(start, end, freq=pd.Timedelta(seconds=step), inclusive="left")
    inside = numeric.loc[numeric.index >= start]
    if inside.empty:
        means = np.full(len(grid), np.nan)
    else:
        bins = np.asarray((inside.index - start) // pd.Timedelta(seconds=step), dtype="int64")
        kept = bins < len(grid)
        grouped = inside[kept].groupby(bins[kept]).mean()
        means = np.full(len(grid), np.nan)
        means[grouped.index.to_numpy()] = grouped.to_numpy(dtype=float)
    held = hold_positions(grid, step, numeric.index, now=now, on_change=on_change)
    empty = ~np.isfinite(means) & (held >= 0)
    means[empty] = numeric.to_numpy(dtype=float)[held[empty]]
    return iso_many(grid), _numbers(means)


def _utc_index(values: pd.Series) -> pd.Series:
    """``values`` sorted on a UTC DatetimeIndex, without unknown instants."""

    index = values.index
    if (
        isinstance(index, pd.DatetimeIndex)
        and str(index.tz) == "UTC"
        and not index.hasnans
        and index.is_monotonic_increasing
    ):
        return values  # already so (a reader's series): no copy (scale review E14)
    index = pd.DatetimeIndex(index)
    values = values.copy()
    values.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    return values.loc[~values.index.isna()].sort_index(kind="stable")


def hold_limit(times: pd.DatetimeIndex, step: float) -> float:
    """Seconds a sample may be held for: ``HOLD_STEPS`` times the larger of ``step`` and the
    median spacing of ``times``; unbounded with fewer than three samples (a signal recorded
    on change, such as a setpoint left alone, has no spacing to judge an outage by)."""

    stamps = np.unique(np.asarray(times.as_unit("ns").asi8, dtype="int64"))
    if len(stamps) < 3:
        return math.inf
    spacing = float(np.median(np.diff(stamps))) / 1e9
    return HOLD_STEPS * max(float(step), spacing)


def hold_positions(
    grid: pd.DatetimeIndex,
    step: float,
    times: pd.DatetimeIndex,
    *,
    now: datetime | None = None,
    on_change: bool = False,
) -> np.ndarray:
    """For each grid point, the position in ``times`` (sorted, UTC) of the value it holds, or -1.

    A point holds the last sample before its step ends, when there is one (never before
    the first sample), it is at most ``hold_limit`` seconds older than the point (any age
    for a signal recorded ``on_change``), and the point is not after ``now`` (nothing is
    held into the future).
    """

    if not len(times) or not len(grid):
        return np.full(len(grid), -1, dtype="int64")
    points = np.asarray(grid.as_unit("ns").asi8, dtype="int64")
    stamps = np.asarray(times.as_unit("ns").asi8, dtype="int64")
    last = np.searchsorted(stamps, points + int(round(step * 1e9)), side="left") - 1
    found = last >= 0
    limit = math.inf if on_change else hold_limit(times, step)
    if math.isfinite(limit):
        age = points - stamps[np.clip(last, 0, None)]
        found &= age <= int(limit * 1e9)
    moment = pd.Timestamp(now or datetime.now(timezone.utc))
    moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
    found &= points <= moment.as_unit("ns").value
    return np.where(found, last, -1)


def _numbers(values: np.ndarray) -> list[float | None]:
    """Floats for JSON: NaN and infinities as None."""

    array = np.asarray(values, dtype=float)
    finite = np.isfinite(array)
    if finite.all():
        return array.tolist()
    return [value if keep else None for value, keep in zip(array.tolist(), finite, strict=True)]


def shape_text_series(
    values: pd.Series,
    start: datetime,
    end: datetime,
    step: float | None,
    *,
    now: datetime | None = None,
    on_change: bool = True,
) -> tuple[list[str], list[str | None]]:
    """A text signal's labels inside ``[start, end]`` (``step`` None), or the last label of
    each ``[t, t + step)`` on a regular grid from ``start``; a step without labels holds the
    last label before it as ``shape_series`` does (a blank label ends the hold), else it is
    ``None``. Text signals are recorded on change, so ``on_change`` defaults to true."""

    labels = pd.Series([text_label(value) for value in values.to_numpy()], index=values.index)
    labels = _utc_index(labels)
    labels = labels.loc[labels.index <= end]
    if step is None:
        labels = labels.loc[labels.index >= start].dropna()
        if len(labels) > MAX_POINTS:
            raise ContractError(
                t(
                    "Too many recorded values: at most {count} per request. Give a step.",
                    count=MAX_POINTS,
                )
            )
        return iso_many(labels.index), labels.astype(object).tolist()
    grid = pd.date_range(start, end, freq=pd.Timedelta(seconds=step), inclusive="left")
    found: list[str | None] = [None] * len(grid)
    inside = labels.loc[labels.index >= start].dropna()
    if not inside.empty:
        bins = np.asarray((inside.index - start) // pd.Timedelta(seconds=step), dtype="int64")
        kept = bins < len(grid)
        last = inside[kept].groupby(bins[kept]).last()
        for position, label in zip(last.index.tolist(), last.tolist(), strict=True):
            found[position] = label
    held = hold_positions(grid, step, labels.index, now=now, on_change=on_change)
    every = labels.tolist()
    for position, source in enumerate(held.tolist()):
        if found[position] is None and source >= 0 and isinstance(every[source], str):
            found[position] = every[source]
    return iso_many(grid), found


def shape_values(
    values: pd.Series,
    start: datetime,
    end: datetime,
    step: float | None,
    kind: str = "number",
    *,
    now: datetime | None = None,
    signal_id: str = "",
) -> tuple[list[str], list[Any]]:
    """``shape_series`` or ``shape_text_series``, by the signal's ``kind``; the hold of a
    signal recorded on change (``recorded_on_change(signal_id, kind)``) has no limit."""

    on_change = recorded_on_change(signal_id, kind)
    if kind == "text":
        return shape_text_series(values, start, end, step, now=now, on_change=on_change)
    return shape_series(values, start, end, step, now=now, on_change=on_change)


class BatchBuilder:
    """Collects the answer of ``POST /api/v1/series`` within its points budget.

    The first series is always kept; after that, a series that would take the
    batch past ``MAX_BATCH_POINTS`` and every one after it get a 413 error, so
    the caller asks for them again, in order, in another request.
    """

    def __init__(self, budget: int = MAX_BATCH_POINTS):
        self.budget = budget
        self.points = 0
        self.full = False
        self.series: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def fail(self, signal: str, status: int, detail: str) -> None:
        self.errors.append({"signal": signal, "status": int(status), "detail": str(detail)})

    def postpone(self, signal: str) -> None:
        self.fail(
            signal,
            BATCH_FULL_STATUS,
            t(
                "This request reached its limit of {count} points: ask for this signal in "
                "another request.",
                count=self.budget,
            ),
        )

    def add(self, signal: str, kind: str, stamps: list[str], values: list[Any]) -> None:
        if self.full or (self.series and self.points + len(stamps) > self.budget):
            self.full = True
            self.postpone(signal)
            return
        self.points += len(stamps)
        self.series.append({"signal": signal, "kind": kind, "t": stamps, "v": values})

    def payload(self) -> dict[str, Any]:
        return {"series": self.series, "errors": self.errors}


def unique_signals(signal_ids: Any) -> list[str]:
    """The ids of a batch request in order, without repeats."""

    return list(dict.fromkeys(str(item) for item in signal_ids))


def aggregate(values: pd.Series, agg: str, kind: str = "number") -> tuple[float | str | None, Any]:
    """``(value, at)`` of ``agg`` over ``values``; ``at`` is the last sample's time for ``last``.

    A text signal has only ``last`` (its newest label).
    """

    if agg not in AGGREGATIONS:
        raise ContractError(t("Invalid agg: use one of {aggs}.", aggs=", ".join(AGGREGATIONS)))
    if kind == "text":
        if agg != "last":
            raise ContractError(t("A text signal has only agg=last."))
        labels = pd.Series([text_label(v) for v in values.to_numpy()], index=values.index)
        labels = labels.loc[~pd.DatetimeIndex(labels.index).isna()].dropna()
        if labels.empty:
            return None, None
        labels = labels.sort_index(kind="stable")
        return labels.iloc[-1], labels.index[-1]
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return None, None
    numeric = numeric.sort_index()
    if agg == "last":
        return _number(numeric.iloc[-1]), numeric.index[-1]
    if agg == "std":
        return (_number(numeric.std(ddof=1)) if len(numeric) > 1 else 0.0), None
    return _number(getattr(numeric, agg)()), None


def series_to_pandas(series: Series | dict[str, Any]) -> pd.Series:
    """A v1 series payload as a ``pandas.Series`` with a UTC DatetimeIndex.

    Numbers give a float series (None as NaN); a ``"kind": "text"`` series gives
    an object series of labels (None where a step had none). A series read with its
    quality keeps the changes in ``attrs["quality"]``.
    """

    index = parse_times(list(series.get("t") or []))
    raw = list(series.get("v") or [])
    if series.get("kind") == "text":
        column = pd.Series(raw, index=index, name=series.get("signal"), dtype=object)
    else:
        # None becomes NaN in a float array.
        values = np.array(raw, dtype=float) if raw else np.array([], dtype=float)
        column = pd.Series(values, index=index, name=series.get("signal"), dtype=float)
    return with_quality(column, series)


def with_quality(column: pd.Series, series: Series | dict[str, Any]) -> pd.Series:
    """``column`` with the series' quality changes in ``attrs["quality"]``, when it has any."""

    if "quality" in series:
        column.attrs["quality"] = list(series.get("quality") or [])
    return column


def subject_digest(subject: str) -> str:
    """How the revocation list names a person: the SHA-256 of the token's ``sub``."""

    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


__all__ = [
    "AGGREGATIONS",
    "APP_ACCESS",
    "App",
    "Asset",
    "AuditReceipt",
    "BATCH_FULL_STATUS",
    "BatchBuilder",
    "CENTRAL_AUDIENCE",
    "ContractError",
    "DerivedSignal",
    "HOLD_STEPS",
    "ISSUER",
    "Jwk",
    "KINDS",
    "LEVELS",
    "MAX_BATCH_POINTS",
    "MAX_BATCH_SIGNALS",
    "MAX_POINTS",
    "Me",
    "ON_CHANGE_NAMES",
    "Series",
    "SeriesBatch",
    "SeriesError",
    "Signal",
    "TOKEN_COOKIE",
    "TokenGrant",
    "Value",
    "aggregate",
    "iso",
    "iso_many",
    "kind_of",
    "parse_time",
    "parse_times",
    "parse_window",
    "recorded_on_change",
    "series_range",
    "series_to_pandas",
    "hold_limit",
    "hold_positions",
    "shape_series",
    "shape_text_series",
    "shape_values",
    "subject_digest",
    "with_quality",
    "text_label",
    "unique_signals",
]
