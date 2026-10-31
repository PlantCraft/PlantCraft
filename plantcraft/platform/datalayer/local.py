"""The local data layer: PlantCraft's own sources, signal catalog and history cache.

The behaviour API v1 always had: a signal is read from the source that owns its tag
(``SourceRegistry``), through the history cache. Derived series apps publish are kept in
``DerivedSeriesStore`` and read back here like any other signal.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from plantcraft.i18n import t
from plantcraft.industrial_data.registry import PRIMARY
from plantcraft.platform.datalayer import DataLayer, DataLayerError
from plantcraft_sdk.contract import (
    AGGREGATIONS,
    BatchBuilder,
    ContractError,
    aggregate,
    iso,
    parse_window,
    series_range,
    shape_values,
    unique_signals,
)
from plantcraft_sdk.derived import RUNS_KIND, matches

# Derived kinds read back as recorded values (no grid; only agg=last).
TYPED_KINDS = ("integer", "boolean", "instant", "structured")
MAX_RUNS_READ = 50


class LocalDataLayer(DataLayer):
    kind = "local"
    manages_sources = False

    def __init__(self, platform: Any):
        self.platform = platform

    # Catalog --------------------------------------------------------------------

    def _catalog(self) -> Any:
        return self.platform.signal_catalog()

    def _known(self, signal_id: str, catalog: Any) -> str:
        found, reason = catalog.lookup(signal_id)
        if found is None:
            raise DataLayerError(404, reason)
        return found

    def signals(
        self,
        q: str = "",
        *,
        app: str | None = None,
        subject: str | None = None,
        result: str | None = None,
    ) -> list[dict[str, Any]]:
        needle = q.strip().lower()
        filters = {"app": app, "subject": subject, "result": result}
        ordered = self._catalog().ordered()
        if not needle and not any(filters.values()):
            return list(ordered)
        return [
            item
            for item in ordered
            if (
                not needle or needle in f"{item['id']} {item['name']} {item['description']}".lower()
            )
            and matches(item, filters)
        ]

    def signal(self, signal_id: str) -> dict[str, Any]:
        catalog = self._catalog()
        return catalog.signals[self._known(signal_id, catalog)]

    def lookup(self, signal_id: str) -> tuple[str | None, str]:
        return self._catalog().lookup(signal_id)

    # Reads ----------------------------------------------------------------------

    def _timezone(self) -> str:
        return self.platform.scenario.source.timezone

    def _local(self, stamp: Any) -> pd.Timestamp:
        """A UTC instant as the naive local time the sources read in."""

        return pd.Timestamp(stamp).tz_convert(self._timezone()).tz_localize(None)

    def data_end(self) -> pd.Timestamp:
        """Now, or a recorded file's last sample, as a UTC instant."""

        stamp = pd.Timestamp(self.platform.data_end())
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize(self._timezone(), ambiguous="NaT", nonexistent="NaT")
        if pd.isna(stamp):
            stamp = pd.Timestamp.now(tz="UTC")
        return stamp.tz_convert("UTC")

    def _range(self, start: Any, end: Any, step: float | None) -> tuple[Any, Any, float | None]:
        try:
            return series_range(start, end, step, default_end=self.data_end().to_pydatetime())
        except ContractError as exc:
            raise DataLayerError(422, str(exc)) from exc

    @staticmethod
    def _derived(catalog: Any, found: str) -> bool:
        return "app" in catalog.signals[found]

    def _read_many(
        self, catalog: Any, wanted: dict[str, str], start: Any, end: Any, step: float | None
    ) -> dict[str, pd.Series]:
        """Recorded values of known signals (``{key: signal id}``) between two UTC instants,
        indexed in UTC: plant signals in one source read, derived ones from their table.

        A signal the source has nothing for gets an empty series. Read only.
        """

        found: dict[str, pd.Series] = {}
        tags: dict[str, str] = {}
        for key, signal_id in wanted.items():
            if self._derived(catalog, signal_id):
                found[key] = self.platform.derived.read(signal_id, start, end)
            else:
                tags[key] = catalog.tags[signal_id]
        if not tags:
            return found
        scenario = self.platform.scenario
        seconds = max(1, int(step)) if step else scenario.analysis.resample_seconds
        try:
            frame = self.platform.source.read_range(
                self._local(start),
                self._local(end),
                seconds,
                tags=list(dict.fromkeys(tags.values())),
                # A grid holds each signal's last value from ``start`` on (step-hold), so it
                # asks for the value before ``start`` too; recorded values stay inside.
                include_boundary=step is not None,
            )
        except Exception as exc:  # the source's message is shown to the caller
            raise DataLayerError(502, t("Failed to read history: {error}", error=exc)) from exc
        index = None
        for key, tag in tags.items():
            column = scenario.source.mapping.get(tag, tag)
            if column not in frame.columns:
                column = tag
            if frame.empty or column not in frame.columns:
                found[key] = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
                continue
            values = frame[column]
            if isinstance(values, pd.DataFrame):
                values = values.iloc[:, 0]
            if index is None:
                index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce"))
                if index.tz is None:
                    index = index.tz_localize(self._timezone(), ambiguous="NaT", nonexistent="NaT")
                index = index.tz_convert("UTC")
            series = pd.Series(values.to_numpy(), index=index)
            # The wide frame has NaN where another tag has a sample and this one has none.
            found[key] = series.loc[~series.index.isna()].dropna()
        return found

    def series(
        self,
        signal_id: str,
        start: str | None,
        end: str | None,
        step: float | None,
        *,
        run: str | None = None,
        runs: int | None = None,
    ) -> dict[str, Any]:
        catalog = self._catalog()
        found = self._known(signal_id, catalog)
        kind = catalog.signals[found]["kind"]
        if kind == RUNS_KIND:
            return {"signal": signal_id, "kind": kind, "runs": self._runs(found, run, runs)}
        start_at, end_at, step_s = self._range(start, end, step)
        if kind in TYPED_KINDS:
            stamps, typed = self.platform.derived.read_typed(found, kind, start_at, end_at)
            return {"signal": signal_id, "kind": kind, "t": stamps, "v": typed}
        values = self._read_many(catalog, {found: found}, start_at, end_at, step_s)[found]
        try:
            stamps, numbers = shape_values(values, start_at, end_at, step_s, kind, signal_id=found)
        except ContractError as exc:
            raise DataLayerError(422, str(exc)) from exc
        return {"signal": signal_id, "kind": kind, "t": stamps, "v": numbers}

    def _runs(self, found: str, run: str | None, runs: int | None) -> list[dict[str, Any]]:
        if run not in (None, "", "latest"):
            try:
                at = pd.Timestamp(str(run).replace("Z", "+00:00"))
            except ValueError as exc:
                raise DataLayerError(422, t("run is latest or an ISO 8601 run time.")) from exc
            return self.platform.derived.runs(found, at=at)
        last = 1 if runs is None else runs
        if not 1 <= last <= MAX_RUNS_READ:
            raise DataLayerError(422, t("runs is 1 to {count}.", count=MAX_RUNS_READ))
        return self.platform.derived.runs(found, last=last)

    def run_list(self, signal_id: str, limit: int = 50) -> dict[str, Any]:
        catalog = self._catalog()
        found = self._known(signal_id, catalog)
        if catalog.signals[found]["kind"] != RUNS_KIND:
            raise DataLayerError(422, t("{signal} is not a runs point.", signal=signal_id))
        return {"signal": signal_id, "runs": self.platform.derived.run_list(found, limit=limit)}

    def series_batch(
        self,
        signals: list[str],
        start: str | None,
        end: str | None,
        step: float | None,
        *,
        quality: bool = False,
    ) -> dict[str, Any]:
        start_at, end_at, step_s = self._range(start, end, step)
        catalog = self._catalog()
        batch = BatchBuilder()
        wanted = unique_signals(signals)
        # Each id as asked, and the signal it names (a bare tag names its one source's).
        named = {signal_id: catalog.lookup(signal_id) for signal_id in wanted}
        known = {signal_id: found for signal_id, (found, _) in named.items() if found}
        values: dict[str, pd.Series] = {}
        source_error: str | None = None
        if known:
            try:
                values = self._read_many(catalog, known, start_at, end_at, step_s)
            except DataLayerError as exc:
                source_error = exc.detail
        for signal_id in wanted:
            found, reason = named[signal_id]
            if found is None:
                batch.fail(signal_id, 404, reason)
                continue
            if source_error is not None:
                batch.fail(signal_id, 502, source_error)
                continue
            if batch.full:
                batch.postpone(signal_id)
                continue
            kind = catalog.signals[found]["kind"]
            if kind == RUNS_KIND:
                # A runs point answers its latest run, with the run's time.
                latest = self.platform.derived.runs(found, last=1)
                run = latest[0] if latest else {"run_at": None, "t": [], "v": []}
                batch.add(signal_id, kind, run["t"], run["v"])
                if batch.series and batch.series[-1]["signal"] == signal_id:
                    batch.series[-1]["run_at"] = run["run_at"]
                continue
            if kind in TYPED_KINDS:
                stamps, typed = self.platform.derived.read_typed(found, kind, start_at, end_at)
                batch.add(signal_id, kind, stamps, typed)
                continue
            try:
                stamps, numbers = shape_values(
                    values[signal_id], start_at, end_at, step_s, kind, signal_id=found
                )
            except ContractError as exc:
                batch.fail(signal_id, 422, str(exc))
                continue
            batch.add(signal_id, kind, stamps, numbers)
        return batch.payload()

    def value(self, signal_id: str, agg: str, window: str) -> dict[str, Any]:
        catalog = self._catalog()
        found = self._known(signal_id, catalog)
        kind = catalog.signals[found]["kind"]
        try:
            span = parse_window(window)
            if agg not in AGGREGATIONS:
                raise ContractError(
                    t("Invalid agg: use one of {aggs}.", aggs=", ".join(AGGREGATIONS))
                )
            if kind == RUNS_KIND:
                raise ContractError(t("A runs point has no value: read its runs."))
            if kind == "text" and agg != "last":
                raise ContractError(t("A text signal has only agg=last."))
            if kind in TYPED_KINDS and agg != "last":
                raise ContractError(t("A {kind} point has only agg=last.", kind=kind))
        except ContractError as exc:
            raise DataLayerError(422, str(exc)) from exc
        end_at = self.data_end()
        if self._derived(catalog, found):
            # A derived series ends where its app last wrote it (never past now).
            last = self.platform.derived.last_time(found)
            if last is not None and last > end_at:
                end_at = min(last, pd.Timestamp.now(tz="UTC"))
        if kind in TYPED_KINDS:
            stamps, typed = self.platform.derived.read_typed(found, kind, end_at - span, end_at)
            return {
                "signal": signal_id,
                "agg": agg,
                "window": window,
                "value": typed[-1] if typed else None,
                "at": stamps[-1] if stamps else iso(end_at),
            }
        values = self._read_many(catalog, {found: found}, end_at - span, end_at, None)[found]
        values = values.loc[(values.index >= end_at - span) & (values.index <= end_at)]
        result, at = aggregate(values, agg, kind)
        return {
            "signal": signal_id,
            "agg": agg,
            "window": window,
            "value": result,
            "at": iso(at if at is not None else end_at),
        }

    # Derived series --------------------------------------------------------------

    def put_derived(self, app: str, items: list[Any]) -> dict[str, Any]:
        store = self.platform.derived
        written, errors = 0, []
        for index, item in enumerate(items):
            stored = store.kind_of(item.signal)
            if stored is not None and stored != item.kind:
                errors.append(
                    {
                        "index": index,
                        "signal": item.signal,
                        "status": 422,
                        "detail": t(
                            "{signal} holds {kind} values; write {kind} values to it.",
                            signal=item.signal,
                            kind=stored,
                        ),
                    }
                )
                continue
            store.write(app, item.payload())
            written += 1
        return {"written": written, "errors": errors}

    def put_runs(self, app: str, items: list[Any]) -> dict[str, Any]:
        store = self.platform.derived
        written, errors = 0, []
        for index, item in enumerate(items):
            stored = store.kind_of(item.signal)
            if stored is not None and stored != RUNS_KIND:
                errors.append(
                    {
                        "index": index,
                        "signal": item.signal,
                        "status": 409,
                        "detail": t(
                            "{signal} holds {kind} values; write {kind} values to it.",
                            signal=item.signal,
                            kind=stored,
                        ),
                    }
                )
                continue
            store.write_run(app, item.payload())
            written += 1
        return {"written": written, "errors": errors}

    def retire_derived(self, app: str, signals: list[str]) -> dict[str, Any]:
        return {"retired": self.platform.derived.retire(app, signals), "errors": []}

    # The interface's own reads ---------------------------------------------------

    def history(
        self,
        tags: list[str],
        *,
        start: Any,
        end: Any,
        sample_seconds: int,
        max_points: int,
        source: str | None = None,
    ) -> dict[str, Any]:
        sources = self.platform.sources
        data = self.platform.data if not source or source == PRIMARY else sources.data(source)
        return data.history(
            tags, start=start, end=end, sample_seconds=sample_seconds, max_points=max_points
        )

    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        return self.platform.data.status(refresh=refresh)
