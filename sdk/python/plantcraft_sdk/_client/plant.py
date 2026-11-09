"""``PlantCraftClient``'s reads of the plant: assets, signals, series, summaries, runs, lab samples and values."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

import numpy as np
import pandas as pd

from plantcraft_sdk import wire
from plantcraft_sdk._client.base import (
    SERIES_TIMEOUT,
    BadRequest,
    NotFound,
    PlantCraftError,
    Unavailable,
    _time,
    error_for,
)
from plantcraft_sdk.assets import MAX_RESULT_ASSETS
from plantcraft_sdk.contract import (
    BATCH_FULL_STATUS,
    MAX_BATCH_SIGNALS,
    Asset,
    AssetType,
    Series,
    SeriesBatch,
    SeriesError,
    Signal,
    Value,
    series_to_pandas,
    unique_signals,
)


class _PlantCalls:
    """The client's calls for assets, signals and series (mixed into ``PlantCraftClient``)."""

    def assets(
        self,
        *,
        kind: str | None = None,
        type: str | None = None,
        parent_id: str | None = None,
        results: bool = False,
    ) -> list[Asset]:
        """The asset tree; ``kind`` is the exact type, ``type`` also takes its subtypes.

        Result assets (what apps record about assets) come with ``results=True`` or
        ``kind="result"``.
        """

        params: dict[str, Any] = {"kind": kind, "type": type, "parent_id": parent_id}
        if results:
            params["results"] = "true"
        return self._all_pages(self._exchange, "/api/v1/assets", params)

    def sync_result_assets(self, assets: Iterable[Mapping[str, Any]]) -> dict[str, int]:
        """``PUT /api/v1/assets/results``: the app's whole set of result assets.

        Each is ``{"id": "<app id>.<name>", "parent_id", "name", "description", "made_by",
        "points": [{"role", "signal": "app-<app id>:<name>", "name", "unit"}]}``; those the app
        listed before and not now are ended, not removed. Needs a service token.
        ``{"saved", "ended"}``.
        """

        return self._send(
            "PUT", "/api/v1/assets/results", json={"assets": [dict(item) for item in assets]}
        )

    def remove_result_assets(self, ids: Iterable[str]) -> dict[str, int]:
        """``POST /api/v1/assets/results/remove``: drop result assets of the app. ``{"removed"}``."""

        wanted = list(dict.fromkeys(ids))
        removed = 0
        for start in range(0, len(wanted), MAX_RESULT_ASSETS):
            answer = self._send(
                "POST",
                "/api/v1/assets/results/remove",
                json={"ids": wanted[start : start + MAX_RESULT_ASSETS]},
            )
            removed += int((answer or {}).get("removed") or 0)
        return {"removed": removed}

    def asset_types(self) -> list[AssetType]:
        """The type catalog, inherited attributes and roles resolved."""

        return self._send("GET", "/api/v1/asset-types")

    def asset(self, asset_id: str) -> Asset:
        return self._send("GET", f"/api/v1/assets/{quote(asset_id, safe='')}")

    def signals(
        self,
        q: str | None = None,
        *,
        app: str | None = None,
        subject: str | None = None,
        result: str | None = None,
    ) -> list[Signal]:
        """Every signal; ``app``, ``subject`` and ``result`` keep the derived signals that have them."""

        params = {"q": q, "app": app, "subject": subject, "result": result}
        return self._all_pages(self._read_exchange, "/api/v1/signals", params)

    def signal(self, signal_id: str) -> Signal:
        return self._read("GET", f"/api/v1/signals/{quote(signal_id, safe='')}")

    def series(
        self,
        signal_id: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
        *,
        sampling: str | None = None,
        max_gap: float | None = None,
    ) -> Series:
        """Recorded values (``step`` None) or one mean per ``step`` seconds. Naive datetimes are UTC.

        ``sampling="interpolated"`` (with ``step``, numbers only): the value at each grid time
        from ``start`` to ``end`` on the straight line between the samples around it, as PI's
        and Seeq's interpolated reads; ``max_gap`` (seconds) is the longest span between two
        samples it interpolates across. Needs the Historian."""

        params: dict[str, Any] = {"start": _time(start), "end": _time(end), "step": step}
        if sampling:
            params["sampling"] = sampling
        if max_gap is not None:
            params["max_gap"] = max_gap
        return self._read(
            "GET",
            f"/api/v1/signals/{quote(signal_id, safe='')}/series",
            params=params,
            timeout=SERIES_TIMEOUT,
        )

    def summary(
        self,
        signal_id: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        *,
        per: str = "h",
    ) -> dict[str, Any]:
        """What ``[start, end]`` holds: ``count`` (values recorded), ``covered_pct`` (time
        with a value), ``good_pct`` (time with good quality; None for a signal read from its
        source), ``total`` (the time integral per ``per``: ``s``, ``min``, ``h`` or ``d``, so
        a flow in t/h totals to tonnes) and the time-weighted ``mean``, ``min``, ``max`` and
        ``std``. Needs the Historian."""

        return self._send(
            "GET",
            f"/api/v1/signals/{quote(signal_id, safe='')}/summary",
            params={"start": _time(start), "end": _time(end), "per": per},
            timeout=SERIES_TIMEOUT,
        )

    def series_runs(
        self, signal_id: str, *, run: str | datetime | None = None, last: int | None = None
    ) -> list[dict[str, Any]]:
        """The executions of a runs point, newest first: ``[{"run_at", "t", "v"}]``.

        The run at ``run`` (its time), else the ``last`` newest (1 to 50), else the latest.
        """

        answer = self._send(
            "GET",
            f"/api/v1/signals/{quote(signal_id, safe='')}/series",
            params={"run": _time(run) if run is not None else None, "runs": last},
        )
        return list((answer or {}).get("runs") or [])

    def series_run_list(self, signal_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """What a runs point keeps: ``[{"run_at", "start", "end", "n"}]``, newest first."""

        answer = self._send(
            "GET", f"/api/v1/signals/{quote(signal_id, safe='')}/runs", params={"limit": limit}
        )
        return list((answer or {}).get("runs") or [])

    def lab_samples(
        self,
        signal_id: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
    ) -> list[dict[str, Any]]:
        """A laboratory signal's samples (``laboratory:<analysis>``), oldest first:
        ``[{"sampled_at", "value", "status", "received_at", "approved_at", "written_at",
        "written_by", "writes", "delay_hours"}]``; ``status`` is ``entered``, ``approved`` or
        ``rejected``. The Historian keeps them (``GET /api/v1/lab/{signal}``, default: the
        last 30 days); with no Historian, or one that keeps none, the list is empty."""

        historian = self._historian
        if historian is None or not self._historian_serves(historian):
            return []
        try:
            answer = self._send(
                "GET",
                f"/api/v1/lab/{quote(signal_id, safe='')}",
                params={
                    "start": _time(start),
                    "end": _time(end),
                },
                base=historian.url,
            )
        except PlantCraftError as exc:
            if exc.status_code == 404:
                return []
            raise
        return list((answer or {}).get("samples") or [])

    def series_pandas(
        self,
        signal_id: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
        *,
        sampling: str | None = None,
        max_gap: float | None = None,
    ) -> pd.Series:
        """``series`` as a float ``pandas.Series`` with a UTC DatetimeIndex."""

        return series_to_pandas(
            self.series(signal_id, start, end, step, sampling=sampling, max_gap=max_gap)
        )

    def series_many(
        self,
        signal_ids: Iterable[str],
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
        *,
        binary: bool = False,
        quality: bool = False,
        extremes: bool = False,
        sampling: str | None = None,
        max_gap: float | None = None,
    ) -> SeriesBatch:
        """Many signals' series: ``{"series": [...], "errors": [{signal, status, detail}]}``.

        ``binary``: a Historian that writes the binary answer (``plantcraft_sdk.wire``) sends
        it, and its series hold numpy arrays (``t`` int64 ms, ``v`` floats) instead of lists;
        ``series_many_pandas`` uses it.

        ``quality``: each series also lists where its samples were not good,
        ``"quality": [{"t", "quality"}]`` (the quality from ``t`` to the next change:
        ``uncertain``, ``substituted``, ``bad``, or ``good`` again). Without it a bad sample is
        just a null value and an uncertain one looks good. A server that keeps no quality
        leaves the list out.

        ``extremes`` (with ``step``): each number series also holds every step's lowest and
        highest value, ``"low"`` and ``"high"`` beside the means in ``"v"`` (``None`` where a
        step had none), so a min or max trend needs no raw samples. A server that cannot tell
        them (a source read live, a span past what it keeps) leaves them out.

        ``sampling`` and ``max_gap``: as in ``series`` (an interpolated grid).

        One ``POST /api/v1/series`` per 500 signals; signals a request had no
        room for (413) are asked for again in the next one, so ``errors`` holds
        only real failures (404 unknown signal, 422 too many points, 502 source
        failed). Series come back in the order asked. A PlantCraft without the
        batch route is read one signal at a time, with the same result.
        """

        pending = unique_signals(item for item in signal_ids if item)
        found: dict[str, Series] = {}
        errors: dict[str, SeriesError] = {}
        while pending:
            chunk, pending = pending[:MAX_BATCH_SIGNALS], pending[MAX_BATCH_SIGNALS:]
            answer = self._series_batch(
                chunk,
                start,
                end,
                step,
                binary=binary,
                quality=quality,
                extremes=extremes,
                sampling=sampling,
                max_gap=max_gap,
            )
            for item in answer.get("series") or []:
                item.setdefault("kind", "number")
                found[item["signal"]] = item
            postponed = []
            for error in answer.get("errors") or []:
                if error.get("status") == BATCH_FULL_STATUS:
                    postponed.append(error["signal"])
                else:
                    errors[error["signal"]] = error
            if postponed and len(postponed) == len(chunk):
                # Nothing fitted: never loop forever on a server that serves none.
                for signal_id in postponed:
                    errors[signal_id] = {
                        "signal": signal_id,
                        "status": BATCH_FULL_STATUS,
                        "detail": "PlantCraft had no room for this signal.",
                    }
                postponed = []
            pending = postponed + pending
        order = unique_signals(item for item in signal_ids if item)
        return {
            "series": [found[item] for item in order if item in found],
            "errors": [errors[item] for item in order if item in errors],
        }

    def _series_batch(
        self,
        signal_ids: list[str],
        start: str | datetime | None,
        end: str | datetime | None,
        step: float | None,
        *,
        binary: bool = False,
        quality: bool = False,
        extremes: bool = False,
        sampling: str | None = None,
        max_gap: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "signals": signal_ids,
            "start": _time(start),
            "end": _time(end),
            "step": step,
        }
        if quality:
            body["quality"] = True
        if extremes and step:
            body["extremes"] = True
        if sampling:
            body["sampling"] = sampling
        if max_gap is not None:
            body["max_gap"] = max_gap
        historian = self._historian
        if historian is not None and self._historian_serves(historian):
            accept = (
                f"{wire.MEDIA_TYPE}, application/json;q=0.5"
                if binary and wire.FORMAT in historian.formats
                else "application/json"
            )
            try:
                return self._send(
                    "POST",
                    "/api/v1/series",
                    json=body,
                    base=historian.url,
                    timeout=SERIES_TIMEOUT,
                    accept=accept,
                )
            except Unavailable as exc:
                if exc.status_code is not None:
                    raise
                historian.set(False)
        if self._batch:
            try:
                return self._send("POST", "/api/v1/series", json=body, timeout=SERIES_TIMEOUT)
            except (NotFound, BadRequest) as exc:
                if exc.status_code not in (404, 405):
                    raise
                self._batch = False
        series: list[Series] = []
        errors: list[SeriesError] = []
        for signal_id in signal_ids:
            try:
                series.append(
                    self.series(signal_id, start, end, step, sampling=sampling, max_gap=max_gap)
                )
            except (BadRequest, NotFound, Unavailable) as exc:
                if exc.status_code is None:
                    raise
                errors.append(
                    {"signal": signal_id, "status": exc.status_code, "detail": str(exc.detail)}
                )
        return {"series": series, "errors": errors}

    def series_many_pandas(
        self,
        signal_ids: Iterable[str],
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
        *,
        quality: bool = False,
    ) -> tuple[dict[str, pd.Series], list[SeriesError]]:
        """``series_many`` as ``({signal id: pandas.Series}, errors)``; text signals hold labels.

        ``quality``: each series' ``attrs["quality"]`` holds its quality changes, as
        ``series_many`` gives them.
        """

        batch = self.series_many(
            signal_ids, start, end, step, binary=self.binary_reads, quality=quality
        )
        columns = {
            item["signal"]: (
                wire.binary_to_pandas(item)
                if isinstance(item.get("t"), np.ndarray)
                else series_to_pandas(item)
            )
            for item in batch["series"]
        }
        return columns, batch["errors"]

    def series_frame(
        self,
        signal_ids: Iterable[str],
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
    ) -> pd.DataFrame:
        """Several signals side by side, one column each (outer join on time).

        Read with ``series_many``; the first signal that failed raises its typed error.
        """

        columns, errors = self.series_many_pandas(signal_ids, start, end, step)
        if errors:
            first = errors[0]
            raise error_for(first["status"], first["detail"])
        if not columns:
            return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
        return pd.concat(columns, axis=1).sort_index()

    def value(
        self,
        signal_id: str,
        agg: str = "last",
        window: str = "1h",
        end: str | datetime | None = None,
    ) -> Value:
        """One aggregate over ``window`` ending now, or at ``end`` (a window that closed
        earlier, like last week; never later than now)."""

        params = {"agg": agg, "window": window}
        if end is not None:
            params["end"] = _time(end)
        return self._read(
            "GET", f"/api/v1/signals/{quote(signal_id, safe='')}/value", params=params
        )
