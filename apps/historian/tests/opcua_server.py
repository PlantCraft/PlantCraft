"""A small OPC UA server for tests: a few variables that change on a known schedule.

Runs in its own thread and event loop on a free port. ``values`` is what the next
update writes; ``set`` changes a variable at once.

| Node id (ns=2) | Type | Behaviour |
|---|---|---|
| ``s=TI-100.PV`` | Double | ramps 0.1 per update, EURange 0..200 degC |
| ``s=FIC-101.PV`` | Double | constant 50.0 until set |
| ``s=FIC-101.MODE`` | String | "AUTO" until set |
| ``s=XV-102.OPEN`` | Boolean | False until set |
| ``i=5001`` | Double | numeric node id, constant 1.0 |
"""

from __future__ import annotations

import asyncio
import socket
import threading
from typing import Any

from asyncua import Server, ua

NAMESPACE = "urn:histcraft:test"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class PlantServer:
    def __init__(self, period: float = 0.1, secure_dir: Any = None):
        # A folder for the server's certificate: offers Sign and SignAndEncrypt too (G2).
        self.secure_dir = secure_dir
        self.port = free_port()
        self.endpoint = f"opc.tcp://127.0.0.1:{self.port}/histcraft/test/"
        self.period = period
        self.nodes: dict[str, Any] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self.writes = 0

    async def _main(self) -> None:
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        if self.secure_dir is None:
            server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        else:
            from pathlib import Path

            from asyncua.crypto.cert_gen import setup_self_signed_certificate
            from cryptography.x509.oid import ExtendedKeyUsageOID

            folder = Path(self.secure_dir)
            key, cert = folder / "server-key.pem", folder / "server-cert.der"
            await setup_self_signed_certificate(
                key,
                cert,
                "urn:histcraft:test:server",
                "127.0.0.1",
                [ExtendedKeyUsageOID.SERVER_AUTH],
                {"commonName": "Test plant"},
            )
            server.set_server_name("Test plant")
            await server.set_application_uri("urn:histcraft:test:server")
            await server.load_certificate(str(cert))
            await server.load_private_key(str(key))
            server.set_security_policy(
                [
                    ua.SecurityPolicyType.NoSecurity,
                    ua.SecurityPolicyType.Basic256Sha256_Sign,
                    ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                ]
            )
            self.certificate = cert.read_bytes()
        index = await server.register_namespace(NAMESPACE)
        objects = server.nodes.objects
        unit = await objects.add_object(
            ua.NodeId("Unit100", index), ua.QualifiedName("Unit100", index)
        )
        ti = await unit.add_object(ua.NodeId("TI-100", index), ua.QualifiedName("TI-100", index))
        pv = await ti.add_variable(
            ua.NodeId("TI-100.PV", index), ua.QualifiedName("PV", index), 0.0
        )
        eu = await pv.add_property(
            ua.NodeId("TI-100.PV.EURange", index),
            ua.QualifiedName("EURange", 0),
            ua.Range(Low=0.0, High=200.0),
        )
        await pv.add_property(
            ua.NodeId("TI-100.PV.EngineeringUnits", index),
            ua.QualifiedName("EngineeringUnits", 0),
            ua.EUInformation(DisplayName=ua.LocalizedText("degC")),
        )
        del eu
        fic = await unit.add_object(ua.NodeId("FIC-101", index), ua.QualifiedName("FIC-101", index))
        flow = await fic.add_variable(
            ua.NodeId("FIC-101.PV", index), ua.QualifiedName("PV", index), 50.0
        )
        mode = await fic.add_variable(
            ua.NodeId("FIC-101.MODE", index),
            ua.QualifiedName("MODE", index),
            "AUTO",
            ua.VariantType.String,
        )
        xv = await unit.add_variable(
            ua.NodeId("XV-102.OPEN", index), ua.QualifiedName("XV-102.OPEN", index), False
        )
        numeric = await unit.add_variable(
            ua.NodeId(5001, index), ua.QualifiedName("N5001", index), 1.0
        )
        self.nodes = {
            "TI-100.PV": pv,
            "FIC-101.PV": flow,
            "FIC-101.MODE": mode,
            "XV-102.OPEN": xv,
            "N5001": numeric,
        }
        self._stop = asyncio.Event()
        async with server:
            self._ready.set()
            value = 0.0
            while not self._stop.is_set():
                value = round(value + 0.1, 6)
                await pv.write_value(value)
                self.writes += 1
                try:
                    await asyncio.wait_for(self._stop.wait(), self.period)
                except TimeoutError:
                    pass

    def start(self) -> PlantServer:
        def run() -> None:
            self._loop = asyncio.new_event_loop()
            self._loop.run_until_complete(self._main())
            self._loop.close()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        if not self._ready.wait(15):
            raise RuntimeError("test OPC UA server did not start")
        return self

    def set(self, name: str, value: Any) -> None:
        assert self._loop is not None
        node = self.nodes[name]
        future = asyncio.run_coroutine_threadsafe(node.write_value(value), self._loop)
        future.result(5)

    def stop(self) -> None:
        if self._thread is None:
            return
        if self._loop is not None and self._stop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(15)
        self._thread = None
