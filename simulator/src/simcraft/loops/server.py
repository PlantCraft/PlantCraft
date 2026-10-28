"""OPC UA server for the 50-loop portfolio that the PlantCraft demo reads.

Tags are `CPM.Loops.<LOOP_ID>.<SIGNAL>` string NodeIds in the PlantCraft Simulator namespace
(`simcraft.contracts.NAMESPACE_URI`). Values are historized (OPC UA Historical Access) and the
dynamic state is kept in a second SQLite file, so a restart continues where it stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from asyncua import Server, ua

from ..contracts import NAMESPACE_URI
from ..settings import env
from .dynamics import (
    LOOP_DEFINITIONS,
    LoopState,
    initial_state,
    simulate_step,
)
from .storage import HISTORY_RETENTION, LoopHistorySQLite, SimulatorStateStore

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "opc.tcp://127.0.0.1:4840/plantcraft/"
APPLICATION_URI = "urn:processcraft:plantcraft:loops"
HISTORY_BACKFILL_BATCH_POINTS = 240


def _data_value(value: float | str, timestamp: datetime) -> ua.DataValue:
    # Asyncua's SQLite historian uses Python's built-in TIMESTAMP converter,
    # which expects naive UTC values. OPC UA transports these timestamps as UTC.
    history_timestamp = timestamp.astimezone(UTC).replace(tzinfo=None)
    variant_type = ua.VariantType.String if isinstance(value, str) else ua.VariantType.Double
    return ua.DataValue(
        ua.Variant(value, variant_type),
        StatusCode_=ua.StatusCode(ua.StatusCodes.Good),
        SourceTimestamp=history_timestamp,
        ServerTimestamp=history_timestamp,
    )


class LoopPortfolioServer:
    """OPC UA server lifecycle plus deterministic historical backfill."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        history_db: str | Path = "var/opcua-history.sqlite3",
        state_db: str | Path = "var/opcua-state.sqlite3",
        history_hours: float = 24.0,
        history_sample_seconds: float = 30.0,
        realtime_seconds: float = 1.0,
        historian_seconds: float = 5.0,
        reset: bool = False,
        namespace_uri: str = NAMESPACE_URI,
    ):
        self.endpoint = endpoint
        self.namespace_uri = namespace_uri
        self.history_db = Path(history_db).expanduser().resolve()
        self.state_db = Path(state_db).expanduser().resolve()
        self.history_hours = max(float(history_hours), 0.05)
        self.history_sample_seconds = max(float(history_sample_seconds), 1.0)
        self.realtime_seconds = max(float(realtime_seconds), 0.2)
        self.historian_seconds = max(float(historian_seconds), 0.2)
        self.reset = reset

        self.server: Server | None = None
        self.history: LoopHistorySQLite | None = None
        self.state_store: SimulatorStateStore | None = None
        self.namespace_index: int | None = None
        self.nodes: dict[str, Any] = {}
        self.states: dict[str, LoopState] = {}
        self.latest_values: dict[str, dict[str, float | str]] = {}
        self.simulated_at: datetime | None = None
        self._update_task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self.history_db.parent.mkdir(parents=True, exist_ok=True)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        if self.reset:
            self.history_db.unlink(missing_ok=True)
            self.state_db.unlink(missing_ok=True)

        history = LoopHistorySQLite(
            str(self.history_db),
            max_history_data_response_size=10_000,
            realtime_min_interval_seconds=self.historian_seconds,
        )
        server = Server()
        server.iserver.history_manager.set_storage(history)
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_server_name("PlantCraft Simulator control loop portfolio")
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        server.application_uri = APPLICATION_URI

        self.server = server
        self.history = history
        self.namespace_index = await server.register_namespace(self.namespace_uri)
        await self._create_address_space()
        await self._prepare_history()
        await server.historize_node_data_change(
            list(self.nodes.values()),
            period=HISTORY_RETENTION,
            count=0,
        )
        await server.start()
        self._started = True
        self._update_task = asyncio.create_task(
            self._realtime_loop(),
            name="simcraft-loops-realtime",
        )
        logger.info(
            "OPC UA server ready at %s (%s loops, data since %s)",
            self.endpoint,
            len(LOOP_DEFINITIONS),
            (self.simulated_at - timedelta(hours=self.history_hours) if self.simulated_at else "—"),
        )

    async def stop(self) -> None:
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
            self._update_task = None
        if self.state_store and self.simulated_at and self.states:
            self.state_store.save(self.simulated_at, self.states)
        if self.server and self._started:
            await self.server.stop()
        self._started = False

    async def _create_address_space(self) -> None:
        assert self.server is not None
        assert self.namespace_index is not None
        idx = self.namespace_index
        root = await self.server.nodes.objects.add_object(
            ua.NodeId("CPM", idx),
            "CPM",
        )
        loops_folder = await root.add_folder(
            ua.NodeId("CPM.Loops", idx),
            "Loops",
        )
        for definition in LOOP_DEFINITIONS:
            loop_node = await loops_folder.add_object(
                ua.NodeId(f"CPM.Loops.{definition.loop_id}", idx),
                definition.loop_id,
            )
            await loop_node.add_property(
                ua.NodeId(f"CPM.Loops.{definition.loop_id}.Name", idx),
                "Name",
                definition.name,
            )
            await loop_node.add_property(
                ua.NodeId(f"CPM.Loops.{definition.loop_id}.Behavior", idx),
                "Behavior",
                definition.behavior,
            )
            await loop_node.add_property(
                ua.NodeId(f"CPM.Loops.{definition.loop_id}.Description", idx),
                "Description",
                definition.service,
            )
            await loop_node.add_property(
                ua.NodeId(
                    f"CPM.Loops.{definition.loop_id}.EngineeringUnit",
                    idx,
                ),
                "EngineeringUnit",
                definition.pv_unit,
            )
            for signal_name in definition.signal_names:
                initial: float | str = (
                    "AUTO"
                    if signal_name == "MODE"
                    else definition.base_sp
                    if signal_name in {"PV", "SP"}
                    else 50.0
                )
                variant_type = (
                    ua.VariantType.String if signal_name == "MODE" else ua.VariantType.Double
                )
                node = await loop_node.add_variable(
                    ua.NodeId(definition.tag(signal_name), idx),
                    signal_name,
                    ua.Variant(initial, variant_type),
                )
                self.nodes[definition.tag(signal_name)] = node

    async def _prepare_history(self) -> None:
        assert self.history is not None
        assert self.state_db is not None
        for node in self.nodes.values():
            await self.history.new_historized_node(
                node.nodeid,
                HISTORY_RETENTION,
                0,
            )

        state_store = SimulatorStateStore(self.state_db)
        self.state_store = state_store
        stored_at, stored_states = state_store.load()
        counts = [await self.history.count_node_values(node.nodeid) for node in self.nodes.values()]
        complete_state = set(stored_states) == {
            definition.loop_id for definition in LOOP_DEFINITIONS
        }
        consistent = complete_state and stored_at is not None and all(count > 0 for count in counts)
        now = datetime.now(UTC).replace(microsecond=0)
        if stored_at and stored_at > now + timedelta(minutes=1):
            consistent = False

        if not consistent:
            for node in self.nodes.values():
                await self.history.clear_node_values(node.nodeid)
            state_store.clear()
            self.states = {
                definition.loop_id: initial_state(definition) for definition in LOOP_DEFINITIONS
            }
            start = now - timedelta(hours=self.history_hours)
            previous = start - timedelta(seconds=self.history_sample_seconds)
        else:
            self.states = stored_states
            previous = stored_at
            start = stored_at + timedelta(seconds=self.history_sample_seconds)

        history_values: dict[str, list[ua.DataValue]] = defaultdict(list)
        timestamp = start
        buffered_points = 0
        while timestamp <= now:
            dt = max(
                (timestamp - previous).total_seconds(),
                self.history_sample_seconds,
            )
            self._simulate_all(timestamp, dt, history_values)
            buffered_points += 1
            previous = timestamp
            timestamp += timedelta(seconds=self.history_sample_seconds)
            if buffered_points >= HISTORY_BACKFILL_BATCH_POINTS:
                await self._flush_history_values(history_values)
                buffered_points = 0
        if previous < now:
            self._simulate_all(
                now,
                (now - previous).total_seconds(),
                history_values,
            )
            previous = now

        await self._flush_history_values(history_values)
        self.simulated_at = previous
        state_store.save(previous, self.states)
        await self._write_latest_values(previous)

    async def _flush_history_values(
        self,
        history_values: dict[str, list[ua.DataValue]],
    ) -> None:
        """Persist one bounded backfill batch and immediately release it."""

        assert self.history is not None
        if not history_values:
            return
        for tag, values in history_values.items():
            await self.history.save_node_values(
                self.nodes[tag].nodeid,
                values,
                commit=False,
            )
        await self.history.commit_pending()
        history_values.clear()

    def _simulate_all(
        self,
        timestamp: datetime,
        step_seconds: float,
        history_values: dict[str, list[ua.DataValue]] | None = None,
    ) -> None:
        for definition in LOOP_DEFINITIONS:
            values = simulate_step(
                definition,
                self.states[definition.loop_id],
                timestamp,
                step_seconds,
            )
            self.latest_values[definition.loop_id] = values
            if history_values is not None:
                for signal_name, value in values.items():
                    history_values[definition.tag(signal_name)].append(
                        _data_value(value, timestamp)
                    )

    async def _write_latest_values(
        self,
        timestamp: datetime,
        *,
        previous_values: dict[str, dict[str, float | str]] | None = None,
    ) -> None:
        for definition in LOOP_DEFINITIONS:
            values = self.latest_values[definition.loop_id]
            prior = (previous_values or {}).get(definition.loop_id, {})
            for signal_name, value in values.items():
                # SP is written continuously so online trends always have a
                # current endpoint. MODE remains event-driven because it is a
                # discrete state and its last value is carried forward.
                if signal_name == "MODE" and prior.get(signal_name) == value:
                    continue
                await self.nodes[definition.tag(signal_name)].write_value(
                    _data_value(value, timestamp)
                )

    async def _realtime_loop(self) -> None:
        assert self.state_store is not None
        while True:
            started = asyncio.get_running_loop().time()
            timestamp = datetime.now(UTC)
            previous_time = self.simulated_at or timestamp
            previous_values = {
                loop_id: dict(values) for loop_id, values in self.latest_values.items()
            }
            self._simulate_all(
                timestamp,
                max((timestamp - previous_time).total_seconds(), 0.05),
            )
            await self._write_latest_values(
                timestamp,
                previous_values=previous_values,
            )
            self.simulated_at = timestamp
            self.state_store.save(timestamp, self.states)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.05, self.realtime_seconds - elapsed))


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    """Options of `simcraft loops serve`; each default comes from a SIMCRAFT_* variable."""

    parser = argparse.ArgumentParser(
        prog=prog,
        description="Serve the 50-loop portfolio (PlantCraft demo) through OPC UA.",
    )
    parser.add_argument(
        "--endpoint",
        default=env("SIMCRAFT_ENDPOINT", DEFAULT_ENDPOINT),
    )
    parser.add_argument(
        "--namespace-uri",
        default=env("SIMCRAFT_NAMESPACE_URI", NAMESPACE_URI),
        help="transition only: serve the tags under another namespace URI",
    )
    parser.add_argument(
        "--history-db",
        default=env("SIMCRAFT_HISTORY_DB", "var/opcua-history.sqlite3"),
    )
    parser.add_argument(
        "--state-db",
        default=env("SIMCRAFT_STATE_DB", "var/opcua-state.sqlite3"),
    )
    parser.add_argument(
        "--history-hours",
        type=float,
        default=float(env("SIMCRAFT_HISTORY_HOURS", "48")),
    )
    parser.add_argument(
        "--history-sample-seconds",
        type=float,
        default=float(
            env(
                "SIMCRAFT_HISTORY_SAMPLE_SECONDS",
                "30",
            )
        ),
    )
    parser.add_argument(
        "--realtime-seconds",
        type=float,
        default=float(env("SIMCRAFT_REALTIME_SECONDS", "1")),
    )
    parser.add_argument(
        "--historian-seconds",
        type=float,
        default=float(env("SIMCRAFT_HISTORIAN_SECONDS", "5")),
    )
    parser.add_argument("--reset", action="store_true")
    parser.add_argument(
        "--log-level",
        default=env("SIMCRAFT_LOG_LEVEL", "INFO"),
    )
    return parser


async def _run(args: argparse.Namespace) -> None:
    simulator = LoopPortfolioServer(
        endpoint=args.endpoint,
        history_db=args.history_db,
        state_db=args.state_db,
        history_hours=args.history_hours,
        history_sample_seconds=args.history_sample_seconds,
        realtime_seconds=args.realtime_seconds,
        historian_seconds=args.historian_seconds,
        reset=args.reset,
        namespace_uri=args.namespace_uri,
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:
            pass
    await simulator.start()
    try:
        await stop_event.wait()
    finally:
        await simulator.stop()


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    args = build_parser(prog).parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
