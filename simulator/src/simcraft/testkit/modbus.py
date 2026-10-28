"""A Modbus TCP device with the plant's last values in every register layout Historian lists.

``REGISTERS`` places each value as a data type and byte order (Telegraf's names: ABCD is big
endian, DCBA little endian, BADC bytes swapped in each word, CDAB words swapped; 64-bit values
name all eight bytes, ABCDEFGH ... GHEFCDAB), integers
scaled, plus coils (loop in AUTO) and discrete inputs (PV above SP). ``options()`` is the
Historian source's register list for the same map, ``expected()`` what it should archive.

Needs ``pymodbus`` (BSD), in the ``testkit`` extra.
"""

from __future__ import annotations

import struct
from typing import Any

from .plant import Series

SLAVE_ID = 3
# name, register type, address, tag, data type, byte order, scale (value = raw * scale)
REGISTERS: tuple[tuple[str, str, int, str, str, str, float], ...] = (
    ("FIC-101.PV", "holding_register", 0, "FIC-101.PV", "FLOAT32-IEEE", "ABCD", 1.0),
    ("FIC-101.SP", "holding_register", 2, "FIC-101.SP", "FLOAT32-IEEE", "CDAB", 1.0),
    ("FIC-101.OP", "holding_register", 4, "FIC-101.OP", "FLOAT32-IEEE", "BADC", 1.0),
    ("PIC-102.PV", "holding_register", 6, "PIC-102.PV", "FLOAT32-IEEE", "DCBA", 1.0),
    ("PIC-102.SP", "holding_register", 8, "PIC-102.SP", "FLOAT64-IEEE", "ABCDEFGH", 1.0),
    ("PIC-102.OP", "holding_register", 12, "PIC-102.OP", "FLOAT64-IEEE", "GHEFCDAB", 1.0),
    ("LIC-103.PV.x10", "holding_register", 16, "LIC-103.PV", "INT16", "AB", 0.1),
    ("LIC-103.SP.x10", "holding_register", 17, "LIC-103.SP", "UINT16", "BA", 0.1),
    ("FIC-101.PV.x100", "holding_register", 18, "FIC-101.PV", "INT32", "CDAB", 0.01),
    ("PIC-102.PV.x1000", "holding_register", 20, "PIC-102.PV", "UINT32", "ABCD", 0.001),
    ("LIC-103.OP.x1000", "holding_register", 22, "LIC-103.OP", "INT64", "HGFEDCBA", 0.001),
    ("LIC-103.PV.in", "input_register", 0, "LIC-103.PV", "FLOAT32-IEEE", "ABCD", 1.0),
)
FORMATS = {
    "INT16": ">h",
    "UINT16": ">H",
    "INT32": ">i",
    "UINT32": ">I",
    "INT64": ">q",
    "FLOAT32-IEEE": ">f",
    "FLOAT64-IEEE": ">d",
}
LOOPS = ("FIC-101", "PIC-102", "LIC-103")
WIDE = {"ABCDEFGH": "ABCD", "HGFEDCBA": "DCBA", "BADCFEHG": "BADC", "GHEFCDAB": "CDAB"}


def words(value: float, data_type: str, byte_order: str, scale: float) -> list[int]:
    """The registers holding ``value`` (big-endian bytes reordered as Telegraf reads them)."""

    raw = value / scale
    if "FLOAT" not in data_type:
        raw = round(raw)
    data = struct.pack(FORMATS[data_type], raw)
    pairs = [data[i : i + 2] for i in range(0, len(data), 2)]
    order = byte_order[:2] if len(pairs) == 1 else WIDE.get(byte_order, byte_order)
    if order in ("BA", "BADC"):
        pairs = [pair[::-1] for pair in pairs]
    elif order == "DCBA":
        pairs = [pair[::-1] for pair in reversed(pairs)]
    elif order == "CDAB":
        pairs = list(reversed(pairs))
    return [int.from_bytes(pair, "big") for pair in pairs]


def expected(series: dict[str, Series]) -> dict[str, float | int]:
    """What each register name reads back as, after the device's rounding and the scale."""

    found: dict[str, float | int] = {}
    for name, _kind, _address, tag, data_type, _order, scale in REGISTERS:
        value = float(series[tag].last)
        if data_type == "FLOAT32-IEEE":
            found[name] = struct.unpack(">f", struct.pack(">f", value))[0]
        elif "FLOAT" in data_type:
            found[name] = value
        else:
            found[name] = round(value / scale) * scale
    for loop in LOOPS:
        found[f"{loop}.AUTO"] = int(series[f"{loop}.MODE"].last == "AUTO")
        found[f"{loop}.HIGH"] = int(series[f"{loop}.PV"].last > series[f"{loop}.SP"].last)
    return found


def options() -> dict[str, Any]:
    """The Historian source's options for this device."""

    registers: list[dict[str, Any]] = [
        {"name": name, "type": kind, "address": address, "data_type": data_type}
        | {"byte_order": order, "scale": scale}
        for name, kind, address, _tag, data_type, order, scale in REGISTERS
    ]
    for number, loop in enumerate(LOOPS):
        registers.append({"name": f"{loop}.AUTO", "type": "coil", "address": number})
        registers.append({"name": f"{loop}.HIGH", "type": "discrete_input", "address": number})
    return {"slave_id": SLAVE_ID, "timeout_seconds": 5.0, "registers": registers}


class ModbusPlant:
    """The device on 127.0.0.1:``port``; ``await start()``, ``await stop()``."""

    def __init__(self, series: dict[str, Series], *, port: int):
        self.series, self.port = series, port
        self.url = f"tcp://127.0.0.1:{port}"
        self._server: Any = None

    async def start(self) -> None:
        import asyncio

        from pymodbus.datastore import (
            ModbusSequentialDataBlock,
            ModbusServerContext,
            ModbusSlaveContext,
        )
        from pymodbus.server import ModbusTcpServer

        device = ModbusSlaveContext(
            hr=ModbusSequentialDataBlock(0, [0] * 64),
            ir=ModbusSequentialDataBlock(0, [0] * 64),
            co=ModbusSequentialDataBlock(0, [False] * 64),
            di=ModbusSequentialDataBlock(0, [False] * 64),
        )
        functions = {"holding_register": 3, "input_register": 4}
        for _name, kind, address, tag, data_type, order, scale in REGISTERS:
            value = float(self.series[tag].last)
            device.setValues(functions[kind], address, words(value, data_type, order, scale))
        for number, loop in enumerate(LOOPS):
            device.setValues(1, number, [self.series[f"{loop}.MODE"].last == "AUTO"])
            high = self.series[f"{loop}.PV"].last > self.series[f"{loop}.SP"].last
            device.setValues(2, number, [high])
        context = ModbusServerContext(slaves={SLAVE_ID: device}, single=False)
        self._server = ModbusTcpServer(context, address=("127.0.0.1", self.port))
        asyncio.get_running_loop().create_task(self._server.serve_forever())
        await asyncio.sleep(0.3)

    async def stop(self) -> None:
        if self._server:
            await self._server.shutdown()
