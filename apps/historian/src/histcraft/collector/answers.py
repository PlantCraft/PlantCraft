"""``Collector``'s answers to the requests people make from the pages: browse a server, test a
connection, read a CSV or the source's history, and backfill the archive. Part of ``Collector``
(``collector.service``)."""

from __future__ import annotations

import asyncio
from typing import Any

from histcraft.archive.store import now_ms
from histcraft.catalog.models import GATEWAY_KINDS
from histcraft.collector.backfill import MAX_HOURS, backfill
from histcraft.collector.state import LOGGER, REQUEST_WINDOW_MS, _describe
from histcraft.i18n import t
from histcraft.sources.csv_watch import CsvWatcher


class Answers:
    """``Collector``'s answers to requests."""

    # Requests ---------------------------------------------------------------------------

    async def answer_requests(self) -> None:
        since = now_ms() - REQUEST_WINDOW_MS
        waiting = [r for r in self.catalog.requests(since) if r["id"] not in self._done_requests]
        if not waiting:
            return
        done = self.archive.done_requests([r["id"] for r in waiting])
        for request in waiting:
            if request["id"] in done:
                self._done_requests.add(request["id"])
                continue
            if request["kind"] == "backfill":
                if request["id"] not in self._backfills:
                    self._backfills[request["id"]] = asyncio.create_task(self._backfill(request))
                continue
            status, result = await self._answer(request)
            self.archive.finish_request(request["id"], status, result)
            self._done_requests.add(request["id"])

    async def _answer(self, request: dict[str, Any]) -> tuple[str, Any]:
        source = next((s for s in self.catalog.sources() if s["id"] == request["source_id"]), None)
        if source is None:
            return "error", {"detail": t("Source {id} not found.", id=request["source_id"])}
        if source["kind"] == "csv":
            return await asyncio.to_thread(self._answer_csv, source, request)
        if source["kind"] == "pi_web_api":
            return await asyncio.to_thread(self._answer_history, source, request)
        if source["kind"] in ("derived", "system", "lab"):
            return "error", {"detail": t("A derived source is written by its app.")}
        if source["kind"] in GATEWAY_KINDS:
            return self._answer_gateway(source, request)
        if source["kind"] == "sparkplug":
            return self._answer_sparkplug(source, request)
        try:
            reader = self._reader_for(source)
        except Exception as exc:  # noqa: BLE001 - e.g. direct OPC UA turned off
            return "error", {"detail": _describe(exc)}
        try:
            await asyncio.wait_for(reader.connect(), self.settings.opcua_timeout + 5)
            if request["kind"] == "browse":
                detail = request.get("detail") or {}
                result = await asyncio.wait_for(
                    reader.browse(detail.get("root") or None),
                    max(self.settings.opcua_timeout * 30, 120),
                )
            elif request["kind"] == "read":
                addresses = list((request.get("detail") or {}).get("addresses") or [])[:100]
                readings = await reader.read(addresses)
                result = {
                    "values": {
                        address: {
                            "at": r.at_ms,
                            "value": r.value,
                            "good": r.good,
                            "detail": r.detail,
                        }
                        for address, r in readings.items()
                    }
                }
            else:
                result = await reader.test()
            return "ok", result
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            answer = {"detail": str(exc) if hasattr(exc, "certificate") else _describe(exc)}
            # A secure source not trusted yet: the page shows the certificate to trust.
            if hasattr(exc, "certificate"):
                answer["certificate"] = exc.certificate
            return "error", answer
        finally:
            await reader.close()

    async def _backfill(self, request: dict[str, Any]) -> None:
        try:
            status, result = await asyncio.to_thread(self._run_backfill, request)
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            LOGGER.exception("Backfill of %s failed", request["source_id"])
            status, result = "error", {"detail": _describe(exc)}
        self.archive.finish_request(request["id"], status, result)
        self._done_requests.add(request["id"])
        self._backfills.pop(request["id"], None)

    def _run_backfill(self, request: dict[str, Any]) -> tuple[str, Any]:
        """The source's history of its archived signals into the archive (collector/backfill.py)."""

        from histcraft.sources.history import open_source

        source = next((s for s in self.catalog.sources() if s["id"] == request["source_id"]), None)
        if source is None:
            return "error", {"detail": t("Source {id} not found.", id=request["source_id"])}
        points = self.catalog.points(
            source_id=source["id"], enabled_only=True, modes=("archive", "both")
        )
        detail = request.get("detail") or {}
        if detail.get("points"):
            only = {int(item) for item in detail["points"]}
            points = [point for point in points if int(point["id"]) in only]
        if not points:
            return "error", {"detail": t("The source has no archived signals to backfill.")}
        try:
            hours = min(max(float(detail.get("hours") or 24), 0.0), MAX_HOURS)
        except (TypeError, ValueError):
            hours = 24.0
        until = int(request["created_ms"])
        history = open_source(source, self.password(source))
        LOGGER.info("Backfill of %s: %d signals, %g h", source["id"], len(points), hours)
        result = backfill(history, self.archive, points, until - int(hours * 3600_000), until)
        return ("ok" if result["signals"] or not result["failed"] else "error"), result

    def _answer_csv(self, source: dict[str, Any], request: dict[str, Any]) -> tuple[str, Any]:
        """Browse or test a CSV source: the tags of its newest files, or what it finds."""

        try:
            watcher = CsvWatcher(source)
            if request["kind"] == "browse":
                return "ok", watcher.browse()
            if request["kind"] == "test":
                return "ok", watcher.test()
            return "error", {"detail": t("A CSV source is read when its files change.")}
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            return "error", {"detail": _describe(exc)}

    def _answer_history(self, source: dict[str, Any], request: dict[str, Any]) -> tuple[str, Any]:
        """Browse or test a source read by its history interface (PI Web API, CSV)."""

        from histcraft.sources.history import open_source

        try:
            history = open_source(source, self.password(source))
            if request["kind"] == "browse":
                return "ok", history.browse((request.get("detail") or {}).get("root") or None)
            if request["kind"] == "test":
                return "ok", history.test()
            return "error", {"detail": t("This source is read by history, not by value.")}
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            return "error", {"detail": _describe(exc)}
