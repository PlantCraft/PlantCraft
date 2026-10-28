"""``make sources-public``: Historian's readers against public test servers, by hand only.

Never in CI (the servers are not ours and come and go). Run it now and then, at the end of a
Historian round, to catch what local servers do not: other vendors' stacks, real latency.
Prints one line per server; a failure is a finding to look at, not a broken build.
"""

from __future__ import annotations

import asyncio
import sys
import time

from histcraft.sources.history import open_source

# Public servers documented by their owners as open for testing (2026-10).
OPCUA = (
    ("Eclipse Milo demo", "opc.tcp://milo.digitalpetri.com:62541/milo"),
    ("node-opcua demo (Sterfive)", "opc.tcp://opcuademo.sterfive.com:26543"),
)
MQTT = (("Eclipse Mosquitto test broker", "test.mosquitto.org", 1883),)


def _opcua(name: str, endpoint: str) -> str:
    row = {
        "id": "public",
        "kind": "opcua",
        "endpoint": endpoint,
        "namespace_uri": "",
        "username": "",
        "options": {"timeout_seconds": 15},
    }
    source = open_source(row, "")
    answer = source.test()
    found = source.browse(limit=50)["variables"]
    return f"{len(found)} variables browsed; server {answer.get('server', answer)}"


async def _mqtt(host: str, port: int) -> str:
    from amqtt.client import MQTTClient

    client = MQTTClient(client_id=f"plantcraft-check-{int(time.time())}")
    await client.connect(f"mqtt://{host}:{port}")
    await client.subscribe([("$SYS/broker/uptime", 0)])
    message = await asyncio.wait_for(client.deliver_message(), 20)
    await client.disconnect()
    return f"message on {message.topic}: {message.data[:40]!r}"


def main() -> int:
    failed = 0
    checks = [(name, lambda e=endpoint, n=name: _opcua(n, e)) for name, endpoint in OPCUA]
    checks += [(name, lambda h=host, p=port: asyncio.run(_mqtt(h, p))) for name, host, port in MQTT]
    for name, check in checks:
        began = time.monotonic()
        try:
            detail = check()
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - every server is reported
            detail, status = f"{type(exc).__name__}: {exc}", "FAILED"
            failed += 1
        print(f"{status:6} {name} ({time.monotonic() - began:.1f} s): {detail}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
