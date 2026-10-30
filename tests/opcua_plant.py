"""A small stand-in for the Simulator's loop portfolio in tests: the nodes the demo scenario reads.

The Simulator (``simcraft loops serve``) is its own product and CI cannot install it, so tests
that need an OPC UA server use this one. It publishes the same address space shape as
The Simulator 0.4.0 (``Objects/CPM/Loops/<loop>/<signal>``, string NodeIds
``CPM.Loops.<loop>.<SIGNAL>``, namespace ``urn:processcraft:plantcraft``, loop properties
``Name`` and ``EngineeringUnit``) for the loops it is given, with a few minutes of synthetic,
historized values. It reproduces the interface, not the Simulator's dynamics.
``tests/test_opcua_demo.py`` also runs against the real server when the Simulator is installed.
"""

from __future__ import annotations

import asyncio
import math
import socket
import threading
from datetime import datetime, timedelta, timezone

from plantcraft.config import LoopConfig

NAMESPACE_URI = "urn:processcraft:plantcraft"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class FakePlantCraft:
    """An asyncua server in a background thread; use it as a context manager."""

    def __init__(
        self,
        loops: list[LoopConfig],
        *,
        minutes: float = 10,
        sample_seconds: float = 30,
        namespace_uri: str = NAMESPACE_URI,
    ):
        self.loops = loops
        self.minutes = minutes
        self.sample_seconds = sample_seconds
        self.namespace_uri = namespace_uri
        self.port = free_port()
        self.endpoint = f"opc.tcp://127.0.0.1:{self.port}/plantcraft/"
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._nodes: dict[str, object] = {}
        self._server = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def tags(self) -> list[str]:
        return list(self._nodes)

    def __enter__(self) -> "FakePlantCraft":
        self._thread.start()
        if not self._ready.wait(30) or self._error is not None:
            raise RuntimeError(f"the test OPC UA server did not start: {self._error}")
        return self

    def __exit__(self, *_: object) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=15)

    def advance(self) -> datetime:
        """Write and historize one new sample of every signal, stamped now."""

        assert self._loop is not None
        stamp = datetime.now(timezone.utc)
        asyncio.run_coroutine_threadsafe(self._write_all(stamp), self._loop).result(10)
        return stamp

    # Inside the server thread ---------------------------------------------------------------

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as exc:  # reported to __enter__
            self._error = exc
            self._ready.set()

    async def _serve(self) -> None:
        from asyncua import Server, ua

        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_server_name("PlantCraft test plant")
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        namespace = await server.register_namespace(self.namespace_uri)
        cpm = await server.nodes.objects.add_object(ua.NodeId("CPM", namespace), "CPM")
        folder = await cpm.add_object(ua.NodeId("CPM.Loops", namespace), "Loops")
        for loop in self.loops:
            parent = await folder.add_object(
                ua.NodeId(f"CPM.Loops.{loop.loop_id}", namespace), loop.loop_id
            )
            await parent.add_property(namespace, "Name", loop.name)
            await parent.add_property(namespace, "EngineeringUnit", "%")
            for role, tag in loop.signals.model_dump().items():
                if not tag:
                    continue
                name = tag.rsplit(".", 1)[-1]
                initial = "AUTO" if role == "mode" else 0.0
                node = await parent.add_variable(ua.NodeId(tag, namespace), name, initial)
                await server.iserver.history_manager.historize_data_change(node, None, 0)
                self._nodes[tag] = node
        self._server = server
        async with server:
            now = datetime.now(timezone.utc)
            steps = int(self.minutes * 60 / self.sample_seconds)
            for step in range(steps, -1, -1):
                await self._write_all(now - timedelta(seconds=step * self.sample_seconds))
            self._loop = asyncio.get_running_loop()
            self._stop = asyncio.Event()
            self._ready.set()
            await self._stop.wait()

    async def _write_all(self, stamp: datetime) -> None:
        from asyncua import ua

        storage = self._server.iserver.history_manager.storage
        phase = stamp.timestamp() / 120.0
        for index, (tag, node) in enumerate(self._nodes.items()):
            signal = tag.rsplit(".", 1)[-1]
            if signal == "MODE":
                variant = ua.Variant("AUTO", ua.VariantType.String)
            else:
                value = {"SP": 50.0, "OP": 45.0 + 5 * math.sin(phase + index)}.get(
                    signal, 50.0 + 2 * math.sin(phase + index)
                )
                variant = ua.Variant(value, ua.VariantType.Double)
            value = ua.DataValue(variant, SourceTimestamp=stamp, ServerTimestamp=stamp)
            await self._server.write_attribute_value(node.nodeid, value)
            await storage.save_node_value(node.nodeid, value)
