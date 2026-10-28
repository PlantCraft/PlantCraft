"""``simcraft testkit``: serve the plant over the protocols the kit has, until Ctrl+C.

Not listed in ``simcraft --help``: a tool for development and CI.

    simcraft testkit --serve mqtt,modbus,piwebapi,csv --csv-dir /tmp/kit
    simcraft testkit --serve sql --sql-dsn postgresql://user:pw@127.0.0.1/kit
"""

from __future__ import annotations

import argparse
import json
import threading
from contextlib import ExitStack
from pathlib import Path

from . import csv_files, modbus, mqtt, plant, sql
from .background import Background
from .piwebapi import USER, PiWebApi

KINDS = ("mqtt", "modbus", "sql", "piwebapi", "csv")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="simcraft testkit", description=__doc__)
    parser.add_argument("--serve", default="mqtt,modbus,piwebapi,csv", help=",".join(KINDS))
    parser.add_argument("--minutes", type=float, default=60.0, help="history to publish")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--modbus-port", type=int, default=5020)
    parser.add_argument("--pi-port", type=int, default=8090)
    parser.add_argument("--csv-dir", type=Path, default=Path("testkit-csv"))
    parser.add_argument("--sql-dsn", default="")
    args = parser.parse_args(argv)
    kinds = [kind.strip() for kind in args.serve.split(",") if kind.strip()]
    unknown = sorted(set(kinds) - set(KINDS))
    if unknown:
        parser.error(f"unknown --serve {', '.join(unknown)}; choose from {', '.join(KINDS)}")
    series = plant.history(minutes=args.minutes)
    served: dict[str, object] = {}
    with ExitStack() as stack:
        if "csv" in kinds:
            csv_files.write(args.csv_dir, series)
            served["csv"] = str(args.csv_dir.resolve())
        if "sql" in kinds:
            if not args.sql_dsn:
                parser.error("--serve sql needs --sql-dsn")
            sql.write(args.sql_dsn, series)
            served["sql"] = {name: item["query"] for name, item in sql.SOURCES.items()}
        if "piwebapi" in kinds:
            pi = stack.enter_context(PiWebApi(series, port=args.pi_port))
            served["piwebapi"] = {"url": pi.base_url, "user": USER[0], "password": USER[1]}
        if "mqtt" in kinds:
            broker = mqtt.MqttPlant(series, port=args.mqtt_port)
            stack.enter_context(Background(broker.start, broker.stop))
            served["mqtt"] = {"url": broker.url, "topics": ["plant/#"]}
        if "modbus" in kinds:
            device = modbus.ModbusPlant(series, port=args.modbus_port)
            stack.enter_context(Background(device.start, device.stop))
            served["modbus"] = {"url": device.url, "options": modbus.options()}
        print(json.dumps(served, indent=2), flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    return 0
