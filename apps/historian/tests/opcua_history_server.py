"""A small OPC UA server with Historical Access for tests, in memory.

Runs in its own thread and event loop on a free port, like ``tests/opcua_server.py``,
and keeps history of every variable (asyncua's in-memory history storage). At start it
stores ``minutes`` of samples every ``sample_seconds`` up to now. Adapted from
PlantCraft's ``tests/opcua_plant.py``.

| Node id (ns of ``NAMESPACE``) | Type | History |
|---|---|---|
| ``s=FIC-101.PV`` | Double | 50 + 2 sin(t), every sample |
| ``s=FIC-101.SP`` | Double | 50.0 then 55.0 from the middle of the history |
| ``s=FIC-101.MODE`` | String | "AUTO", "MAN" in the middle third |
| ``s=TI-100.PV`` | Double | like FIC-101.PV, bad quality in the middle third |
| ``i=5001`` | Double | numeric node id (not browsed: tags are string ids) |
"""

from __future__ import annotations

import asyncio
import math
import socket
import threading
from datetime import datetime, timedelta, timezone

NAMESPACE = "urn:histcraft:test:history"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class HistoryServer:
    """An asyncua server in a background thread; use it as a context manager."""

    def __init__(self, *, minutes: float = 10, sample_seconds: float = 30):
        self.minutes = minutes
        self.sample_seconds = sample_seconds
        self.port = free_port()
        self.endpoint = f"opc.tcp://127.0.0.1:{self.port}/histcraft/history/"
        self.stamps: list[datetime] = []
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> HistoryServer:
        self._thread.start()
        if not self._ready.wait(30) or self._error is not None:
            raise RuntimeError(f"the test OPC UA history server did not start: {self._error}")
        return self

    def __exit__(self, *_: object) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=15)

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
        server.set_server_name("HistCraft test history")
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        ns = await server.register_namespace(NAMESPACE)
        objects = server.nodes.objects
        unit = await objects.add_object(ua.NodeId("Unit100", ns), "Unit100")
        fic = await unit.add_object(ua.NodeId("FIC-101", ns), "FIC-101")
        await fic.add_property(ns, "Name", "Feed flow")
        await fic.add_property(ns, "EngineeringUnit", "m3/h")
        ti = await unit.add_object(ua.NodeId("TI-100", ns), "TI-100")
        nodes = {
            "FIC-101.PV": await fic.add_variable(ua.NodeId("FIC-101.PV", ns), "PV", 0.0),
            "FIC-101.SP": await fic.add_variable(ua.NodeId("FIC-101.SP", ns), "SP", 0.0),
            "FIC-101.MODE": await fic.add_variable(
                ua.NodeId("FIC-101.MODE", ns), "MODE", "AUTO", ua.VariantType.String
            ),
            "TI-100.PV": await ti.add_variable(ua.NodeId("TI-100.PV", ns), "PV", 0.0),
            "N5001": await unit.add_variable(ua.NodeId(5001, ns), "N5001", 1.0),
        }
        manager = server.iserver.history_manager
        for node in nodes.values():
            await manager.historize_data_change(node, None, 0)
        storage = manager.storage
        now = datetime.now(timezone.utc).replace(microsecond=0)
        steps = int(self.minutes * 60 / self.sample_seconds)
        self.stamps = [
            now - timedelta(seconds=step * self.sample_seconds) for step in range(steps, -1, -1)
        ]
        total = len(self.stamps)
        for position, stamp in enumerate(self.stamps):
            third = 3 * position // total  # 0, 1, 2
            wave = 50.0 + 2 * math.sin(stamp.timestamp() / 120.0)
            values = {
                "FIC-101.PV": (wave, ua.VariantType.Double, True),
                "FIC-101.SP": (
                    50.0 if position < total // 2 else 55.0,
                    ua.VariantType.Double,
                    True,
                ),
                "FIC-101.MODE": ("MAN" if third == 1 else "AUTO", ua.VariantType.String, True),
                "TI-100.PV": (wave, ua.VariantType.Double, third != 1),
                "N5001": (1.0, ua.VariantType.Double, True),
            }
            for name, (value, variant, good) in values.items():
                status = ua.StatusCode(
                    ua.StatusCodes.Good if good else ua.StatusCodes.BadSensorFailure
                )
                data = ua.DataValue(
                    ua.Variant(value, variant),
                    StatusCode_=status,
                    SourceTimestamp=stamp,
                    ServerTimestamp=stamp,
                )
                await storage.save_node_value(nodes[name].nodeid, data)
        async with server:
            self._loop = asyncio.get_running_loop()
            self._stop = asyncio.Event()
            self._ready.set()
            await self._stop.wait()
