"""Values pushed by the gateway (Telegraf) into the collector, in InfluxDB line protocol.

The collector listens on ``HISTCRAFT_INGEST_PORT`` (off when 0) for ``POST /api/v2/write``,
the request Telegraf's ``outputs.influxdb_v2`` makes, with ``Authorization: Token <token>``
(the token in ``<data>/gateway/token``, written by the collector, read by the gateway's
configuration). Every metric carries the tag ``histcraft_source``, the id of the Historian
source its input belongs to (``collector.gateway`` writes it in each input). Each field becomes
a value at the point whose address is its series and field (``collector.line_protocol``); the
others are kept as "seen", so Browse lists what the gateway sends.

It only receives: nothing here reaches a plant system.
"""

from __future__ import annotations

import hmac
import logging
import zlib
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from histcraft.collector import line_protocol

if TYPE_CHECKING:
    from histcraft.collector.service import Collector

LOGGER = logging.getLogger(__name__)
SOURCE_TAG = "histcraft_source"
# The gateway's own health (``inputs.internal``): its heartbeat, never archived.
GATEWAY_SOURCE = "gateway"
MAX_BODY = 16 * 1024 * 1024
MAX_INFLATED = 64 * 1024 * 1024


def ingest_app(collector: Collector, token: str) -> Starlette:
    """The small web app the collector serves to the gateway."""

    async def write(request: Request) -> Response:
        given = request.headers.get("authorization", "")
        scheme, _, secret = given.partition(" ")
        if scheme.lower() not in ("token", "bearer") or not hmac.compare_digest(
            secret.strip().encode(), token.encode()
        ):
            return JSONResponse({"code": "unauthorized", "message": "bad token"}, 401)
        body = await request.body()
        if len(body) > MAX_BODY:
            return JSONResponse({"code": "too large", "message": "body over 16 MB"}, 413)
        if request.headers.get("content-encoding", "").lower() == "gzip":
            try:
                body = _inflate(body)
            except (OSError, zlib.error, ValueError) as exc:
                return JSONResponse({"code": "invalid", "message": str(exc)}, 400)
        precision = request.query_params.get("precision", "ns")
        try:
            metrics, errors = line_protocol.parse(body.decode("utf-8", "replace"), precision)
        except line_protocol.LineError as exc:
            return JSONResponse({"code": "invalid", "message": str(exc)}, 400)
        collector.ingest(metrics)
        if errors:
            LOGGER.warning("Gateway sent %d unreadable lines, e.g. %s", len(errors), errors[0])
            if not metrics:
                return JSONResponse({"code": "invalid", "message": errors[0]}, 400)
        return Response(status_code=204)

    async def health(_request: Request) -> Response:
        return Response(status_code=204)

    return Starlette(
        routes=[
            Route("/api/v2/write", write, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
            Route("/ping", health, methods=["GET", "HEAD"]),
        ]
    )


def _inflate(body: bytes) -> bytes:
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = decompressor.decompress(body, MAX_INFLATED)
    if decompressor.unconsumed_tail:
        raise ValueError("body over 64 MB once inflated")
    return out


def split(metric: line_protocol.Metric) -> tuple[str, dict[str, tuple[Any, dict[str, Any]]]]:
    """A metric's source id and, by address, each field's value and where it comes from
    (measurement, tags, field), the source tag left out."""

    tags = dict(metric.tags)
    source = tags.pop(SOURCE_TAG, "")
    series = line_protocol.Metric(metric.measurement, tags, {}, None).series()
    return source, {
        f"{series} {line_protocol.escape_key(field)}": (
            value,
            {"measurement": metric.measurement, "tags": tags, "field": field},
        )
        for field, value in metric.fields.items()
    }
