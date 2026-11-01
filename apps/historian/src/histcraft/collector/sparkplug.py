"""A Sparkplug B source: the collector subscribes to an MQTT broker as a host that only listens.

The MQTT client (paho-mqtt) runs its own network thread; each message it receives is queued and
the collector's task (``Collector._listen``) turns it into values with ``histcraft.sparkplug``.

Read only (AGENTS.md): the client subscribes to births, data and deaths (``sparkplug.topics``)
and nothing else. It never publishes: no STATE, no NCMD or DCMD (so never a rebirth request),
and no will. tests/test_read_only.py checks this module calls no publishing method.
"""

from __future__ import annotations

import asyncio
import queue
import ssl
import threading
from typing import Any
from urllib.parse import urlsplit

import paho.mqtt.client as mqtt

from histcraft.collector.reading import now_ms
from histcraft.i18n import t
from histcraft.sparkplug import topics

# Messages held for the collector's task; past it the newest are dropped (and counted).
QUEUE_LIMIT = 100_000
SCHEMES = {"tcp": 1883, "mqtt": 1883, "ssl": 8883, "mqtts": 8883}


class SparkplugListener:
    """Subscribed while connected; ``messages()`` gives what arrived since the last call."""

    def __init__(self, source: dict[str, Any], *, password: str = "", timeout: float = 10.0):
        self.source = source
        self.options = source.get("options") or {}
        self.password = password
        self.timeout = timeout
        self._queue: queue.Queue[tuple[str, bytes, int]] = queue.Queue(QUEUE_LIMIT)
        self._connected = threading.Event()
        self._failed: str = ""
        self.dropped = 0
        self.client: Any = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set() and not self._failed

    @property
    def failure(self) -> str:
        return self._failed

    def _client(self) -> Any:
        address = urlsplit(self.source["endpoint"])
        scheme = address.scheme.lower()
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"plantcraft-historian-{self.source['id']}",
            clean_session=True,
            reconnect_on_failure=False,
        )
        if scheme in ("ssl", "mqtts"):
            client.tls_set_context(ssl.create_default_context())
        if self.source.get("username"):
            client.username_pw_set(self.source["username"], self.password or None)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client, address.hostname or "", address.port or SCHEMES.get(scheme, 1883)

    async def connect(self) -> None:
        self.client, host, port = self._client()
        await asyncio.to_thread(self.client.connect, host, port, 30)
        self.client.loop_start()
        connected = await asyncio.to_thread(self._connected.wait, self.timeout)
        if self._failed:
            raise ConnectionError(self._failed)
        if not connected:
            raise TimeoutError(t("No answer from the broker in time."))

    def _on_connect(self, client: Any, _userdata: Any, _flags: Any, reason: Any, _props: Any):
        if getattr(reason, "is_failure", False):
            self._failed = t("The broker refused the connection: {reason}.", reason=str(reason))
            self._connected.set()
            return
        qos = int(self.options.get("qos", 1))
        client.subscribe([(topic, qos) for topic in topics(self.options.get("group_id", ""))])
        self._connected.set()

    def _on_disconnect(self, _client: Any, _userdata: Any, _flags: Any, reason: Any, _p: Any):
        self._failed = self._failed or t(
            "The broker closed the connection: {reason}.", reason=str(reason)
        )

    def _on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        try:
            self._queue.put_nowait((message.topic, bytes(message.payload), now_ms()))
        except queue.Full:
            self.dropped += 1

    def messages(self) -> list[tuple[str, bytes, int]]:
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                return out

    async def close(self) -> None:
        client, self.client = self.client, None
        if client is None:
            return
        try:
            client.disconnect()
        finally:
            await asyncio.to_thread(client.loop_stop)
