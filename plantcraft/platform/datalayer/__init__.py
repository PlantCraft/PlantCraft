"""The data layer: where PlantCraft reads signals and series, and where derived series go.

Two implementations behind one interface (``DataLayer``):

- ``local`` (``local.py``): PlantCraft's own sources, signal catalog and history cache, as
  before; derived series in the ``derived_series`` table. Used when ``HISTCRAFT_URL`` is unset
  (tests, installs without HistCraft).
- ``histcraft`` (``histcraft.py``): HistCraft is the suite's data layer and the only component
  that reaches plant data sources; PlantCraft forwards every read, derived write and source
  change to ``{HISTCRAFT_URL}/api/v1/data/...`` with a token it issues to itself.

API v1 checks the caller, then asks the data layer; the interface's own pages (asset values,
history, sources) do the same, so with HistCraft configured nothing here reads the plant.
Failures are ``DataLayerError`` with the HTTP status to answer (404, 422, 502, 504...).
"""

from __future__ import annotations

import os
from typing import Any

from plantcraft.i18n import t

HISTCRAFT_URL_ENV = "HISTCRAFT_URL"


class DataLayerError(Exception):
    """A read or write the data layer could not do; ``status`` is the HTTP status to answer."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class DataLayer:
    """What every implementation offers; shapes are API v1's (``docs/api-v1.md``)."""

    kind = "base"
    # True when sources are configured in the data layer (HistCraft), not in PlantCraft.
    manages_sources = False

    # API v1 reads ---------------------------------------------------------------

    def signals(
        self,
        q: str = "",
        *,
        app: str | None = None,
        subject: str | None = None,
        result: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def signal(self, signal_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def lookup(self, signal_id: str) -> tuple[str | None, str]:
        """``(id, "")`` of a known signal (a bare tag of one source included), else
        ``(None, reason)``."""

        raise NotImplementedError

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
        """``{signal, kind, t, v}``; a runs point answers ``{signal, kind: "runs", runs:
        [{run_at, t, v}]}``, newest first: the run at ``run`` (``latest`` by default) or the
        ``runs`` newest."""

        raise NotImplementedError

    def run_list(self, signal_id: str, limit: int = 50) -> dict[str, Any]:
        """``{signal, runs: [{run_at, start, end, n}]}`` of a runs point, newest first."""

        raise NotImplementedError

    def series_batch(
        self,
        signals: list[str],
        start: str | None,
        end: str | None,
        step: float | None,
        *,
        quality: bool = False,
        extremes: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def value(
        self, signal_id: str, agg: str, window: str, end: str | None = None
    ) -> dict[str, Any]:
        """One aggregate over ``window`` ending at ``end`` (ISO 8601; the newest data when
        None, and never later)."""

        raise NotImplementedError

    # Derived series --------------------------------------------------------------

    def put_derived(self, app: str, items: list[Any]) -> dict[str, Any]:
        """Write validated items (``plantcraft_sdk.derived.DerivedIn``): ``{written, errors}``."""

        raise NotImplementedError

    def put_runs(self, app: str, items: list[Any]) -> dict[str, Any]:
        """Write validated runs (``plantcraft_sdk.derived.RunIn``): ``{written, errors}``."""

        raise NotImplementedError

    def retire_derived(self, app: str, signals: list[str]) -> dict[str, Any]:
        """Retire ``app``'s own derived signals (owner already checked): ``{retired, errors}``."""

        raise NotImplementedError

    # The suite's own health ------------------------------------------------------

    # Only a data layer that keeps history (the Historian) takes the ``system`` signals.
    keeps_system = False

    def put_system(self, series: list[dict[str, Any]]) -> dict[str, Any]:
        """Write the suite's health (``system:<name>`` series, docs/operations.md section 4):
        ``{written, errors}``."""

        raise NotImplementedError

    def certificates(self) -> list[dict[str, Any]]:
        """The data layer's certificates (the Historian's OPC UA ones): ``[{id, name, use,
        source_id?, not_after, fingerprint_sha256}]``; none for a local data layer."""

        return []

    def renew_certificate(self, certificate_id: str, token: str) -> dict[str, Any]:
        raise DataLayerError(404, t("Certificate not found."))

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
        """Samples of a few signals for a chart: ``{start, end, series: {tag: [[iso, v]...]},
        failed_tags, elapsed_ms, from_cache}`` (``start`` and ``end`` naive local times)."""

        raise NotImplementedError

    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        """``{ok, message, latency_ms, checked_at}`` of the data layer's connection."""

        raise NotImplementedError

    def close(self) -> None:
        return None


def build_datalayer(platform: Any, issuer: Any = None) -> DataLayer:
    """HistCraft when ``HISTCRAFT_URL`` is set (and a token issuer is given), else local."""

    url = os.environ.get(HISTCRAFT_URL_ENV, "").strip()
    if url and issuer is not None:
        from plantcraft.platform.datalayer.histcraft import HistCraftDataLayer

        return HistCraftDataLayer(url, issuer, timezone=platform.scenario.source.timezone)
    from plantcraft.platform.datalayer.local import LocalDataLayer

    return LocalDataLayer(platform)


__all__ = ["HISTCRAFT_URL_ENV", "DataLayer", "DataLayerError", "build_datalayer"]
