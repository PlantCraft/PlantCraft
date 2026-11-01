"""A Sparkplug B edge node with the plant's values, on a real MQTT broker.

The broker is Eclipse Mosquitto when it is installed (``mosquitto`` on the PATH or in
/usr/sbin; set ``SIMCRAFT_MOSQUITTO`` to its path, or to ``off``), else amqtt's. One edge node (group
``plant``, node ``edge1``) with one device (``unit100``) publishes, as the specification says:

- ``birth()``: NBIRTH (bdSeq, Node Control/Rebirth, the node's uptime), then DBIRTH with every
  loop's PV, SP, OP and MODE as metrics ``<loop>/<role>`` with an alias, a unit (``engUnit``)
  and the value before the last;
- ``data()``: DDATA with the last values, by alias only;
- ``death()``: NDEATH with the birth's bdSeq (what the node's will says, sent here).

A spy subscribed to ``spBv1.0/#`` keeps every topic published, so a check can show that the
host under test published nothing (no STATE, no NCMD or DCMD).

Needs ``amqtt`` (MIT), in the ``testkit`` extra.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .plant import Series
from .sparkplug_payload import metric, payload

GROUP, NODE, DEVICE = "plant", "edge1", "unit100"
DOUBLE, BOOLEAN, UINT64, TEXT = 10, 11, 8, 12


def mosquitto() -> str | None:
    """The Mosquitto broker's path, when it is installed."""

    given = os.environ.get("SIMCRAFT_MOSQUITTO", "")
    if given == "off":
        return None  # amqtt's broker instead
    if given:
        return given
    found = shutil.which("mosquitto") or "/usr/sbin/mosquitto"
    return found if Path(found).exists() else None


def expected(series: dict[str, Series]) -> dict[str, Any]:
    """The last value of each metric, by the tag Historian gives it (dots for slashes)."""

    return {f"{GROUP}.{NODE}.{DEVICE}.{tag}": item.last for tag, item in series.items()}


class SparkplugPlant:
    """The broker on 127.0.0.1:``port``; ``await start()``, then ``birth``, ``data``, ``death``."""

    def __init__(self, series: dict[str, Series], *, port: int):
        self.series, self.port = series, port
        self.url = f"tcp://127.0.0.1:{port}"
        self.broker_name = ""
        self.published: list[str] = []
        self._process: subprocess.Popen[bytes] | None = None
        self._folder: tempfile.TemporaryDirectory[str] | None = None
        self._broker: Any = None
        self._node: Any = None
        self._spy: Any = None
        self._spy_task: asyncio.Task[None] | None = None
        self._seq = 0
        self._aliases = {tag: index + 1 for index, tag in enumerate(series)}

    async def start(self) -> None:
        from amqtt.client import MQTTClient

        found = mosquitto()
        if found:
            self._folder = tempfile.TemporaryDirectory()
            config = Path(self._folder.name) / "mosquitto.conf"
            config.write_text(f"listener {self.port} 127.0.0.1\nallow_anonymous true\n")
            self._process = subprocess.Popen(
                [found, "-c", str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self.broker_name = "Mosquitto"
        else:
            from amqtt.broker import Broker

            self._broker = Broker(
                {
                    "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"}},
                    "plugins": {
                        "amqtt.plugins.authentication.AnonymousAuthPlugin": {
                            "allow_anonymous": True
                        }
                    },
                }
            )
            await self._broker.start()
            self.broker_name = "amqtt"
        self._spy = MQTTClient(client_id="simcraft-sparkplug-spy")
        for _ in range(50):
            try:
                await self._spy.connect(f"mqtt://127.0.0.1:{self.port}")
                break
            except Exception:  # noqa: BLE001 - the broker is still starting
                await asyncio.sleep(0.1)
        await self._spy.subscribe([("spBv1.0/#", 1)])
        self._spy_task = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        while True:
            message = await self._spy.deliver_message()
            if message is not None:
                self.published.append(message.topic)

    def _next(self) -> int:
        seq, self._seq = self._seq, (self._seq + 1) % 256
        return seq

    async def birth(self) -> None:
        from amqtt.client import MQTTClient

        self._seq = 0
        # The will (NDEATH) is left out: amqtt takes text only; death() sends it instead.
        self._node = MQTTClient(client_id="simcraft-edge1")
        await self._node.connect(f"mqtt://127.0.0.1:{self.port}")
        node = [
            metric("bdSeq", 0, UINT64),
            metric("Node Control/Rebirth", False, BOOLEAN),
            metric("Uptime", 1.0, DOUBLE, props={"engUnit": "s"}),
        ]
        await self._publish("NBIRTH", node, NODE)
        device = []
        for tag, item in self.series.items():
            name = tag.replace(".", "/")
            value = item.values[-2] if len(item.values) > 1 else item.last
            kind = TEXT if item.kind == "text" else DOUBLE
            props = {"engUnit": item.unit} if item.unit else None
            device.append(metric(name, value, kind, alias=self._aliases[tag], props=props))
        await self._publish("DBIRTH", device, f"{NODE}/{DEVICE}", stamp=self._stamp(-2))

    async def data(self) -> None:
        changed = [
            metric(
                None, item.last, TEXT if item.kind == "text" else DOUBLE, alias=self._aliases[tag]
            )
            for tag, item in self.series.items()
        ]
        await self._publish("DDATA", changed, f"{NODE}/{DEVICE}", stamp=self._stamp(-1))

    async def death(self) -> None:
        await self._node.publish(
            f"spBv1.0/{GROUP}/NDEATH/{NODE}", payload([metric("bdSeq", 0, UINT64)]), qos=1
        )
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._node.disconnect(), 5)
        self._node = None

    def _stamp(self, index: int) -> int:
        item = next(iter(self.series.values()))
        return item.times[index] if len(item.times) >= -index else item.times[-1]

    async def _publish(
        self, kind: str, metrics: list[bytes], where: str, stamp: int | None = None
    ) -> None:
        data = payload(metrics, seq=self._next(), timestamp=stamp)
        await self._node.publish(f"spBv1.0/{GROUP}/{kind}/{where}", data, qos=1)

    async def stop(self) -> None:
        if self._spy_task:
            self._spy_task.cancel()
        for step in (
            self._node and self._node.disconnect,
            self._spy and self._spy.disconnect,
            self._broker and self._broker.shutdown,
        ):
            if step:
                with contextlib.suppress(Exception):  # stopping anyway
                    await asyncio.wait_for(step(), 5)
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        if self._folder is not None:
            self._folder.cleanup()
