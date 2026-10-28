"""An MQTT broker with the plant's last values, in the message formats Historian reads.

Every ``period`` seconds, retained, at the QoS given:

- ``plant/value/<loop>/<role>``: the number alone (Historian's format ``value``);
- ``plant/json/<loop>``: ``{"PV": ..., "SP": ..., "OP": ...}`` (format ``json``);
- ``plant/nested/<loop>``: ``{"loop": {"PV": ...}}``, which Telegraf flattens to ``loop_PV``.

Needs ``amqtt`` (MIT), in the ``testkit`` extra.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from .plant import Series, numbers


def messages(series: dict[str, Series]) -> dict[str, bytes]:
    """Topic -> payload of the plant's last values."""

    found: dict[str, bytes] = {}
    loops: dict[str, dict[str, float]] = {}
    for tag, item in numbers(series).items():
        loop, role = tag.rsplit(".", 1)
        found[f"plant/value/{loop}/{role}"] = repr(item.last).encode()
        loops.setdefault(loop, {})[role] = item.last
    for loop, roles in loops.items():
        found[f"plant/json/{loop}"] = json.dumps(roles).encode()
        found[f"plant/nested/{loop}"] = json.dumps({"loop": roles}).encode()
    return found


def expected(series: dict[str, Series]) -> dict[str, float]:
    """What Historian archives, by the tag Browse suggests (topic with dots, then the field)."""

    found: dict[str, float] = {}
    for tag, item in numbers(series).items():
        loop, role = tag.rsplit(".", 1)
        found[f"plant.value.{loop}.{role}"] = item.last
        found[f"plant.json.{loop}.{role}"] = item.last
        found[f"plant.nested.{loop}.loop_{role}"] = item.last
    return found


class MqttPlant:
    """The broker on 127.0.0.1:``port`` and a publisher; ``await start()``, ``await stop()``."""

    def __init__(self, series: dict[str, Series], *, port: int, qos: int = 1, period: float = 1.0):
        self.series, self.port, self.qos, self.period = series, port, qos, period
        self.url = f"tcp://127.0.0.1:{port}"
        self._broker: Any = None
        self._client: Any = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        from amqtt.broker import Broker
        from amqtt.client import MQTTClient

        self._broker = Broker(
            {
                "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"}},
                "plugins": {
                    "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}
                },
            }
        )
        await self._broker.start()
        self._client = MQTTClient(client_id="simcraft-testkit")
        await self._client.connect(f"mqtt://127.0.0.1:{self.port}")
        self._task = asyncio.create_task(self._publish())

    async def _publish(self) -> None:
        payloads = messages(self.series)
        while True:
            for topic, payload in payloads.items():
                await self._client.publish(topic, payload, qos=self.qos, retain=True)
            await asyncio.sleep(self.period)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        # A subscriber still connected (the gateway) must not hold the shutdown.
        for step in (
            self._client and self._client.disconnect,
            self._broker and self._broker.shutdown,
        ):
            if step:
                with contextlib.suppress(Exception):  # stopping anyway
                    await asyncio.wait_for(step(), 5)
