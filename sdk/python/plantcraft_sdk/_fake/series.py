"""The fake PlantCraft's routes for signals, series, runs and current values."""

import copy
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from plantcraft_sdk import derived as _derived
from plantcraft_sdk._fake.wire import _TYPED_KINDS, _Abort, _Request
from plantcraft_sdk.contract import (
    AGGREGATIONS,
    MAX_BATCH_SIGNALS,
    MAX_POINTS,
    BatchBuilder,
    ContractError,
    aggregate,
    iso,
    parse_time,
    parse_times,
    parse_window,
    series_range,
    unique_signals,
)


class _SeriesRoutes:
    """The fake's routes for signals and series (mixed into the fake)."""

    def _route_signals(self, request: "_Request") -> list[dict[str, Any]]:
        scope = self._scope(self._reader(request))
        needle = (request.query.get("q") or "").strip().lower()
        filters = {key: request.query.get(key) for key in _derived.DERIVED_FIELDS}
        return [
            self._signal_payload(item)
            for item in self.signals
            if (
                not needle or needle in f"{item['id']} {item['name']} {item['description']}".lower()
            )
            and _derived.matches(item, filters)
            and (scope is None or item["id"] in scope[1])
        ]

    def _route_signal(self, request: "_Request", id: str) -> dict[str, Any]:
        self._reader(request)
        self._signal_in_scope(request, id)
        return self._signal_payload(self._signal_or_404(id))

    def _range(self, start: Any, end: Any, step: Any) -> tuple[datetime, datetime, float | None]:
        if isinstance(step, bool) or not (step is None or isinstance(step, int | float | str)):
            raise ContractError("step must be a positive number of seconds.")
        if isinstance(start, bool) or isinstance(end, bool):
            raise ContractError("start and end are ISO 8601 times.")
        if not (start is None or isinstance(start, str)) or not (
            end is None or isinstance(end, str)
        ):
            raise ContractError("start and end are ISO 8601 times.")
        try:
            seconds = None if step in (None, "") else float(step)
        except ValueError as exc:
            raise ContractError("step must be a positive number of seconds.") from exc
        return series_range(start, end, seconds, default_end=self.data_end)

    def _route_series(self, request: "_Request", id: str) -> dict[str, Any]:
        self._reader(request)
        self._signal_in_scope(request, id)
        found = self._signal_or_404(id)["id"]
        query = request.query
        if self.kind(found) == _derived.RUNS_KIND:
            return {"signal": id, "kind": "runs", "runs": self._runs(found, query)}
        start_at, end_at, step = self._range(
            query.get("start"), query.get("end"), query.get("step")
        )
        stamps, values = self._values(found, start_at, end_at, step)
        return {"signal": id, "kind": self.kind(found), "t": stamps, "v": values}

    def _route_series_batch(self, request: "_Request") -> dict[str, Any]:
        self._reader(request)
        payload = request.json()
        if not isinstance(payload, dict):
            raise _Abort(422, "Send a JSON object with signals, start, end and step.")
        signals = payload.get("signals")
        if (
            not isinstance(signals, list)
            or not 1 <= len(signals) <= MAX_BATCH_SIGNALS
            or not all(isinstance(item, str) and 0 < len(item) <= 300 for item in signals)
        ):
            raise _Abort(422, f"signals is a list of 1 to {MAX_BATCH_SIGNALS} signal ids (text).")
        start_at, end_at, step = self._range(
            payload.get("start"), payload.get("end"), payload.get("step")
        )
        batch = BatchBuilder(self.batch_points)
        for signal_id in unique_signals(signals):
            try:
                known = self._known(signal_id)
            except _Abort as abort:
                batch.fail(signal_id, abort.status, str(abort.detail))
                continue
            if known is None:
                batch.fail(signal_id, 404, "Signal not found.")
                continue
            if batch.full:
                batch.postpone(signal_id)
                continue
            found = known["id"]
            if self.kind(found) == _derived.RUNS_KIND:
                latest = self._runs(found, {})
                run = latest[0] if latest else {"run_at": None, "t": [], "v": []}
                batch.add(signal_id, "runs", run["t"], run["v"])
                if batch.series and batch.series[-1]["signal"] == signal_id:
                    batch.series[-1]["run_at"] = run["run_at"]
                continue
            try:
                stamps, values = self._values(found, start_at, end_at, step)
            except ContractError as exc:
                batch.fail(signal_id, 422, str(exc))
                continue
            except _Abort as abort:
                batch.fail(signal_id, abort.status, str(abort.detail))
                continue
            batch.add(signal_id, self.kind(found), stamps, values)
            if payload.get("extremes") is True and step and self.kind(found) == "number":
                band = self._extremes(found, start_at, end_at, step, len(stamps))
                if band is not None and batch.series and batch.series[-1]["signal"] == signal_id:
                    batch.series[-1]["low"], batch.series[-1]["high"] = band
        return batch.payload()

    def _extremes(
        self, signal_id: str, start: datetime, end: datetime, step: float, cells: int
    ) -> tuple[list[Any], list[Any]] | None:
        """Each ``step`` cell's lowest and highest recorded value, as the Historian's
        ``extremes`` (None when the raw values do not fit one read)."""

        try:
            stamps, values = self._values(signal_id, start, end, None)
        except (ContractError, _Abort):
            return None
        numbers = pd.to_numeric(pd.Series(values, dtype=object), errors="coerce").to_numpy(float)
        at = pd.DatetimeIndex(pd.to_datetime(list(stamps), utc=True)).as_unit("ns").asi8 / 1e9
        index = np.floor((at - start.timestamp()) / step).astype(np.int64)
        keep = (index >= 0) & (index < cells) & ~np.isnan(numbers)
        low, high = np.full(cells, np.nan), np.full(cells, np.nan)
        np.fmin.at(low, index[keep], numbers[keep])
        np.fmax.at(high, index[keep], numbers[keep])

        def listed(found: np.ndarray) -> list[Any]:
            return [None if np.isnan(value) else float(value) for value in found]

        return listed(low), listed(high)

    def _route_put_series(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app's service token writes derived series.")
        app = subject[4:]
        items = _derived.parse_derived(request.json())
        for item in items:
            try:
                _derived.check_owner(app, item.signal)
            except _derived.DerivedError as error:
                raise _Abort(error.status, error.detail) from error
        written, errors = 0, []
        for index, item in enumerate(items):
            known = next((s for s in self.signals if s["id"] == item.signal), None)
            if known is not None and known.get("kind") not in (None, item.kind):
                detail = f"{item.signal} holds {known['kind']} values; write {known['kind']} values to it."
                errors.append(
                    {"index": index, "signal": item.signal, "status": 422, "detail": detail}
                )
                continue
            points = self.derived.setdefault(item.signal, {})
            points.update(zip(item.t, item.v, strict=True))
            row = _derived.derived_signal(
                item.signal,
                app=app,
                name=item.name if item.name is not None else (known or {}).get("name"),
                unit=item.unit if item.unit is not None else (known or {}).get("unit"),
                kind=item.kind or "number",
                subject=item.subject or (known or {}).get("subject"),
                result=item.result or (known or {}).get("result"),
                description=(
                    item.description
                    if item.description is not None
                    else (known or {}).get("description")
                ),
                managed_by=(
                    item.managed_by
                    if item.managed_by is not None
                    else (known or {}).get("managed_by", "")
                ),
                retention_days=(
                    item.retention_days
                    if item.retention_days is not None
                    else (known or {}).get("retention_days")
                ),
            )
            if known is None:
                self.signals.append(row)
            else:
                known.update(row)
            written += 1
            if item.kind in _TYPED_KINDS:
                continue
            ordered = sorted(points.items())
            self.series_data[item.signal] = pd.Series(
                [value for _, value in ordered],
                index=parse_times([stamp for stamp, _ in ordered]),
                dtype=object if item.kind == "text" else float,
            )
        return {"written": written, "errors": errors}

    def _runs(self, signal_id: str, query: Mapping[str, Any]) -> list[dict[str, Any]]:
        kept = self.derived_runs.get(signal_id, {})
        newest = sorted(kept, reverse=True)
        run = query.get("run")
        if run not in (None, "", "latest"):
            try:
                at = iso(parse_times([str(run)])[0])
            except (ValueError, TypeError) as error:
                raise ContractError("run is latest or an ISO 8601 run time.") from error
            newest = [stamp for stamp in newest if stamp == at]
        else:
            last = int(query.get("runs") or 1)
            if not 1 <= last <= 50:
                raise ContractError("runs is 1 to 50.")
            newest = newest[:last]
        return [{"run_at": stamp, **copy.deepcopy(kept[stamp])} for stamp in newest]

    def _route_run_list(self, request: "_Request", id: str) -> dict[str, Any]:
        self._reader(request)
        found = self._signal_or_404(id)["id"]
        if self.kind(found) != _derived.RUNS_KIND:
            raise ContractError(f"{id} is not a runs point.")
        limit = int(request.query.get("limit") or 50)
        if not 1 <= limit <= 200:
            raise ContractError("limit is 1 to 200.")
        kept = self.derived_runs.get(found, {})
        runs = [{"run_at": stamp, **kept[stamp]} for stamp in sorted(kept, reverse=True)[:limit]]
        return {
            "signal": id,
            "runs": [
                {
                    "run_at": run["run_at"],
                    "start": run["t"][0] if run["t"] else None,
                    "end": run["t"][-1] if run["t"] else None,
                    "n": len(run["t"]),
                }
                for run in runs
            ],
        }

    def _route_put_series_runs(self, request: "_Request") -> dict[str, Any]:
        app = self._app_caller(request, "Only an app's service token writes derived series.")
        items = _derived.parse_runs(request.json())
        for item in items:
            try:
                _derived.check_owner(app, item.signal)
            except _derived.DerivedError as error:
                raise _Abort(error.status, error.detail) from error
        written, errors = 0, []
        for index, item in enumerate(items):
            known = next((s for s in self.signals if s["id"] == item.signal), None)
            if known is not None and known.get("kind") != _derived.RUNS_KIND:
                detail = f"{item.signal} holds {known.get('kind')} values; write {known.get('kind')} values to it."
                errors.append(
                    {"index": index, "signal": item.signal, "status": 409, "detail": detail}
                )
                continue
            row = _derived.derived_signal(
                item.signal,
                app=app,
                name=item.name if item.name is not None else (known or {}).get("name"),
                unit=item.unit if item.unit is not None else (known or {}).get("unit"),
                kind=_derived.RUNS_KIND,
                subject=item.subject or (known or {}).get("subject"),
                result=item.result or (known or {}).get("result"),
                description=(
                    item.description
                    if item.description is not None
                    else (known or {}).get("description")
                ),
                managed_by=(
                    item.managed_by
                    if item.managed_by is not None
                    else (known or {}).get("managed_by", "")
                ),
            )
            if known is None:
                self.signals.append(row)
            else:
                known.update(row)
            kept = self.derived_runs.setdefault(item.signal, {})
            kept[item.run_at] = {"t": list(item.t), "v": list(item.v)}
            oldest = iso(self.now - timedelta(days=item.keep_days)) if item.keep_days else None
            for stamp in sorted(kept, reverse=True)[item.keep_runs :]:
                kept.pop(stamp)
            for stamp in [stamp for stamp in kept if oldest is not None and stamp < oldest]:
                kept.pop(stamp)
            written += 1
        return {"written": written, "errors": errors}

    def _route_retire_series(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app's service token retires derived series.")
        app = subject[4:]
        body = request.json() or {}
        signals = body.get("signals") if isinstance(body, dict) else None
        if not isinstance(signals, list) or not 1 <= len(signals) <= 500:
            raise ContractError("Send 1 to 500 signals to retire.")
        for signal in signals:
            try:
                _derived.check_owner(app, str(signal))
            except _derived.DerivedError as error:
                raise _Abort(error.status, error.detail) from error
        retired = []
        for signal in dict.fromkeys(str(item) for item in signals):
            known = next((s for s in self.signals if s["id"] == signal), None)
            if known is None:
                continue
            self.signals.remove(known)
            self.derived.pop(signal, None)
            self.derived_runs.pop(signal, None)
            self.series_data.pop(signal, None)
            retired.append(signal)
        return {"retired": retired, "errors": []}

    def _route_value(self, request: "_Request", id: str) -> dict[str, Any]:
        self._reader(request)
        found = self._signal_or_404(id)["id"]
        agg = request.query.get("agg", "last")
        window = request.query.get("window", "1h")
        span = parse_window(window)
        if agg not in AGGREGATIONS:
            raise ContractError(f"Invalid agg: use one of {', '.join(AGGREGATIONS)}.")
        kind = self.kind(found)
        if kind == _derived.RUNS_KIND:
            raise ContractError("A runs point has no value: read its runs.")
        if kind == "text" and agg != "last":
            raise ContractError("A text signal has only agg=last.")
        until = parse_time(request.query.get("end"), "end")
        end_at = min(self.data_end, until) if until else self.data_end
        if kind in _TYPED_KINDS:
            if agg != "last":
                raise ContractError(f"A {kind} point has only agg=last.")
            stamps, typed = self._values(found, end_at - span, end_at, None)
            return {
                "signal": id,
                "agg": agg,
                "window": window,
                "value": typed[-1] if typed else None,
                "at": stamps[-1] if stamps else iso(end_at),
            }
        # Long windows are summarized on a coarser grid, as a historian would.
        seconds = span.total_seconds()
        step = None if seconds / self.sample_seconds <= MAX_POINTS else seconds / 10_000
        given = self._given(self.series_data, found)
        if given is not None and len(given) <= MAX_POINTS:
            # A recorded series is read as recorded: the window's own samples, its last included.
            step = None
        stamps, values = self._values(found, end_at - span, end_at, step)
        frame = pd.Series(
            values,
            # Stamps with and without fractional seconds: one fixed format cannot read them.
            index=parse_times(stamps),
            dtype=object if kind == "text" else float,
        )
        result, at = aggregate(frame, agg, kind)
        return {
            "signal": id,
            "agg": agg,
            "window": window,
            "value": result,
            "at": iso(at if at is not None else end_at),
        }
