"""Container health check for either PlantCraft Simulator server (`serve` or `loops serve`).

Healthy means: the OPC UA server answers, the PlantCraft Simulator namespace is registered and a
representative value has a fresh source timestamp. The benchmark publishes a heartbeat node;
the loop portfolio has none, so its first loop's PV is read instead.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from asyncua import Client, ua
from asyncua.ua.uaerrors import BadNodeIdUnknown, UaError

from .contracts import NAMESPACE_URI
from .server import HEALTH_NODE_ID
from .settings import env

DEFAULT_HEALTH_ENDPOINT = "opc.tcp://127.0.0.1:4840/plantcraft/"
LOOPS_PROBE_NODE_ID = "CPM.Loops.FIC-1001.PV"


def _source_is_fresh(
    source_timestamp: datetime | None,
    *,
    now: datetime,
    maximum_age_seconds: float,
) -> bool:
    if source_timestamp is None or maximum_age_seconds <= 0:
        return False
    normalized_source = (
        source_timestamp.replace(tzinfo=UTC)
        if source_timestamp.tzinfo is None
        else source_timestamp.astimezone(UTC)
    )
    normalized_now = now.astimezone(UTC)
    age_seconds = (normalized_now - normalized_source).total_seconds()
    return -maximum_age_seconds <= age_seconds <= maximum_age_seconds


async def _representative_value(client: Client, namespace: int) -> ua.DataValue:
    for node_id in (HEALTH_NODE_ID, LOOPS_PROBE_NODE_ID):
        try:
            return await client.get_node(ua.NodeId(node_id, namespace)).read_data_value()
        except BadNodeIdUnknown:
            continue
    raise RuntimeError("no representative PlantCraft Simulator node is published")


async def _check() -> None:
    endpoint = env(
        "SIMCRAFT_HEALTH_ENDPOINT",
        DEFAULT_HEALTH_ENDPOINT,
    )
    namespace_uri = env("SIMCRAFT_NAMESPACE_URI", NAMESPACE_URI)
    maximum_age_seconds = float(
        env(
            "SIMCRAFT_MAX_SAMPLE_AGE_SECONDS",
            "60",
        )
    )
    async with Client(endpoint, timeout=3) as client:
        await client.nodes.server_state.read_value()
        namespace = await client.get_namespace_index(namespace_uri)
        value = await _representative_value(client, namespace)
        if not _source_is_fresh(
            value.SourceTimestamp,
            now=datetime.now(UTC),
            maximum_age_seconds=maximum_age_seconds,
        ):
            raise RuntimeError("representative simulator value is stale")


def main() -> int:
    try:
        asyncio.run(_check())
    except (OSError, RuntimeError, TimeoutError, UaError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
