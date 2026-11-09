"""``Collector``'s gateway: the ingest server the gateway writes to, laboratory values, a stale
gateway, and its configuration. Part of ``Collector`` (``collector.service``)."""

from __future__ import annotations

from typing import Any

from histcraft.archive.store import now_ms
from histcraft.catalog.models import GATEWAY_KINDS
from histcraft.collector.reading import FUTURE_MS, Reading
from histcraft.collector.state import GATEWAY_STALE_SECONDS, LOGGER, SEEN_LIMIT, _pushed_value
from histcraft.i18n import t


class GatewayIntake:
    """``Collector``'s gateway sources."""

    # The gateway --------------------------------------------------------------------------

    def _ingest_server(self) -> Any:
        """The web server the gateway writes to (``collector.ingest``); None when it is off."""

        if not self.settings.ingest_port:
            return None
        import uvicorn

        from histcraft.collector.gateway import gateway_token
        from histcraft.collector.ingest import ingest_app

        app = ingest_app(self, gateway_token(self.settings.data_dir))
        config = uvicorn.Config(
            app,
            host="0.0.0.0",  # noqa: S104 - the collector's own container network
            port=self.settings.ingest_port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # the collector handles its signals
        return server

    def ingest(self, metrics: list[Any]) -> int:
        """Values the gateway pushed: archived at their points, kept as seen; the count taken."""

        from histcraft.collector.ingest import GATEWAY_SOURCE, split

        now = now_ms()
        taken = 0
        results: dict[str, list[Any]] = {}
        with self._lock:
            for metric in metrics:
                source_id, values = split(metric)
                if source_id == GATEWAY_SOURCE:
                    self.gateway_heartbeat = now
                    continue
                source = self.sources.get(source_id)
                if source is None or source["kind"] not in GATEWAY_KINDS:
                    continue
                at = metric.at_ms if metric.at_ms is not None else now
                if at > now + FUTURE_MS:
                    at = now
                self._gateway_last[source_id] = now
                if (source.get("options") or {}).get("laboratory"):
                    # A LIMS: each row is a laboratory result (histcraft.lab), not a value.
                    results.setdefault(source_id, []).append(metric)
                    continue
                seen = self.seen.setdefault(source_id, {})
                for address, (value, series) in values.items():
                    if address in seen or len(seen) < SEEN_LIMIT:
                        seen[address] = {"at": at, "value": value, **series}
                    for state in self._pushed.get((source_id, address), []):
                        if state.last is not None and at <= state.last[0]:
                            continue  # the archive only moves forward
                        state.take(Reading(at, _pushed_value(value, state.point["kind"]), True))
                        taken += 1
        for source_id, rows in results.items():
            taken += self._laboratory(self.sources[source_id], rows, now)
        return taken

    def _laboratory(self, source: dict[str, Any], metrics: list[Any], now: int) -> int:
        """A LIMS source's rows as laboratory results: ``laboratory:<analysis>`` at the
        sampling time, with status and times; a row read again unchanged is not rewritten."""

        from histcraft import lab

        column = ((source.get("options") or {}).get("tag_columns") or [""])[0]
        samples, refused = [], 0
        for metric in metrics:
            fields, analysis = metric.fields, str(metric.tags.get(column) or "").strip()
            try:
                samples.append(
                    lab.checked(
                        f"laboratory:{analysis}",
                        metric.at_ms if metric.at_ms is not None else now,
                        fields.get("value"),
                        now,
                        received=lab.stamp_ms(fields.get("received_at"), "received_at"),
                        approved=lab.stamp_ms(fields.get("approved_at"), "approved_at"),
                        status=str(fields.get("status") or "").strip().lower() or None,
                    )
                )
            except ValueError:
                refused += 1
        if refused:
            LOGGER.warning("Laboratory source %s: %d rows refused", source["id"], refused)
        if not samples:
            return 0
        try:
            written, errors = lab.write(
                self.catalog, self.archive, samples, f"source:{source['id']}", now,
                only_changed=True,
            )  # fmt: skip
        except Exception:
            LOGGER.exception("Laboratory source %s: the results were not written", source["id"])
            return 0
        if errors:
            LOGGER.warning("Laboratory source %s: %s", source["id"], errors[0]["detail"])
        return written

    def check_gateway(self) -> None:
        """Each gateway source connected while values arrive; a silence is a gap."""

        now = now_ms()
        with self._lock:
            for source_id, source in self.sources.items():
                if source["kind"] not in GATEWAY_KINDS:
                    continue
                last = self._gateway_last.get(source_id)
                interval = float(source.get("default_scan_seconds") or 0)
                stale = max(GATEWAY_STALE_SECONDS, 3 * interval) * 1000
                current = self.source_status.get(source_id) or {}
                if last is not None and now - last < stale:
                    if current.get("status") != "connected":
                        self.source_status[source_id] = {
                            "status": "connected",
                            "detail": "",
                            "since": now,
                        }
                    continue
                detail = (
                    t("No values from the gateway for {seconds} s.", seconds=int(stale / 1000))
                    if last is not None
                    else t("Waiting for the gateway's first values.")
                )
                if current.get("status") == "connected" or not current:
                    self.source_status[source_id] = {
                        "status": "disconnected",
                        "detail": detail,
                        "since": now,
                    }
                    for state in self._source_points(source_id):
                        if state.status not in ("waiting", "disconnected"):
                            state.lost(now, detail)

    def _write_gateway_config(self) -> None:
        if not self.settings.ingest_port:
            return
        from histcraft.collector.gateway import write_config

        try:
            self._gateway_config = write_config(
                self.settings, self.catalog.sources(), self.password, self._gateway_config
            )
        except Exception:  # noqa: BLE001 - one bad source must not stop collection
            LOGGER.exception("The gateway's configuration could not be written")

    def _answer_gateway(self, source: dict[str, Any], request: dict[str, Any]) -> tuple[str, Any]:
        """Browse or test a gateway source: what it has sent so far."""

        with self._lock:
            seen = dict(self.seen.get(source["id"], {}))
            last = self._gateway_last.get(source["id"])
        if not self.settings.ingest_port:
            return "error", {"detail": t("The gateway is not set up (HISTCRAFT_INGEST_PORT).")}
        if not seen:
            return "error", {
                "detail": t(
                    "No values received from the gateway yet. It sends every interval: check"
                    " the address, the credentials and that the histcraft-gateway service runs."
                )
            }
        if request["kind"] == "test":
            return "ok", {"series": len(seen), "last": last}
        from histcraft.collector.gateway import variable

        variables = [variable(source["kind"], address, item) for address, item in seen.items()]
        variables.sort(key=lambda item: item["tag"])
        return "ok", {
            "variables": variables,
            "truncated": len(seen) >= SEEN_LIMIT,
            "limit": SEEN_LIMIT,
        }
