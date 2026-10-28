"""OPC UA Data Access and Historical Access surface for all 500 signals."""

from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from asyncua import Server, ua

from .catalog import SignalDefinition, load_catalog
from .contracts import BENCHMARK_VERSION, NAMESPACE_URI
from .engine import Observation, PlantSimulator, SimulationFrame
from .storage import BulkHistorySQLite

LOGGER = logging.getLogger(__name__)
DEFAULT_ENDPOINT = "opc.tcp://127.0.0.1:4840/plantcraft/"
HEALTH_NODE_ID = "Plant.SimulatorHeartbeat"
CHECKPOINT_SCHEMA = "process-plant-opcua/server-checkpoint/v1"
_CHECKPOINT_KEYS = {
    "benchmark_version",
    "catalog_digest",
    "elapsed_seconds",
    "integration_step_seconds",
    "namespace_uri",
    "sample_seconds",
    "scenario_cycle_seconds",
    "schema",
    "seed",
    "start_at",
}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _variant_type(signal: SignalDefinition) -> ua.VariantType:
    return {
        "number": ua.VariantType.Double,
        "string": ua.VariantType.String,
        "boolean": ua.VariantType.Boolean,
    }[signal.data_type]


def _status_code(quality: str) -> ua.StatusCode:
    return {
        "GOOD": ua.StatusCode(ua.StatusCodes.Good),
        "UNCERTAIN": ua.StatusCode(ua.StatusCodes.Uncertain),
        "BAD": ua.StatusCode(ua.StatusCodes.Bad),
        "BAD_NO_COMMUNICATION": ua.StatusCode(ua.StatusCodes.BadNoCommunication),
    }[quality]


def _data_value(
    observation: Observation,
    signal: SignalDefinition,
    server_timestamp: datetime | None = None,
) -> ua.DataValue:
    source_stamp = observation.timestamp.astimezone(UTC).replace(tzinfo=None)
    server_stamp = (server_timestamp or observation.timestamp).astimezone(UTC).replace(tzinfo=None)
    return ua.DataValue(
        ua.Variant(observation.value, _variant_type(signal)),
        StatusCode_=_status_code(observation.quality),
        SourceTimestamp=source_stamp,
        ServerTimestamp=server_stamp,
    )


class OpcUaPlantServer:
    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        history_db: str | Path = "var/history.sqlite3",
        history_hours: float = 1.0,
        sample_seconds: float = 10.0,
        integration_step_seconds: float = 1.0,
        scenario_cycle_seconds: float = 21_600.0,
        max_history_values_per_node: int = 10_000,
        seed: int = 20260903,
        reset: bool = False,
        wall_clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.endpoint = endpoint
        self.history_db = Path(history_db).expanduser().resolve()
        self.history_hours = float(history_hours)
        self.sample_seconds = float(sample_seconds)
        self.integration_step_seconds = float(integration_step_seconds)
        self.scenario_cycle_seconds = float(scenario_cycle_seconds)
        self.max_history_values_per_node = max_history_values_per_node
        if not math.isfinite(self.history_hours) or self.history_hours < 0:
            raise ValueError("history_hours must be finite and non-negative")
        if not math.isfinite(self.sample_seconds) or self.sample_seconds <= 0:
            raise ValueError("sample_seconds must be finite and positive")
        if not math.isfinite(self.integration_step_seconds) or self.integration_step_seconds <= 0:
            raise ValueError("integration_step_seconds must be finite and positive")
        if self.sample_seconds < self.integration_step_seconds or not math.isclose(
            self.sample_seconds / self.integration_step_seconds,
            round(self.sample_seconds / self.integration_step_seconds),
            abs_tol=1e-9,
        ):
            raise ValueError("sample_seconds must be an integer multiple of integration step")
        if not math.isfinite(self.scenario_cycle_seconds) or self.scenario_cycle_seconds < 600:
            raise ValueError("scenario_cycle_seconds must be finite and at least 600")
        if (
            isinstance(self.max_history_values_per_node, bool)
            or not isinstance(self.max_history_values_per_node, int)
            or self.max_history_values_per_node <= 0
        ):
            raise ValueError("max_history_values_per_node must be a positive integer")
        self.seed = int(seed)
        self.reset = reset
        self.wall_clock = wall_clock
        self.catalog = load_catalog()
        self.signal_by_id = {item.signal_id: item for item in self.catalog.signals}
        self.server: Server | None = None
        self.history: BulkHistorySQLite | None = None
        self.nodes: dict[str, Any] = {}
        self.heartbeat_node: Any | None = None
        self.simulator: PlantSimulator | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.history_db.parent.mkdir(parents=True, exist_ok=True)
        if self.reset:
            self.history_db.unlink(missing_ok=True)
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_server_name("Integrated Process Plant Scientific Benchmark")
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        namespace = await server.register_namespace(NAMESPACE_URI)
        history = BulkHistorySQLite(
            self.history_db,
            max_history_data_response_size=self.max_history_values_per_node,
            retention_seconds=(self.history_hours * 3600.0 if self.history_hours > 0 else None),
        )
        await history.init()
        server.iserver.history_manager.set_storage(history)
        self.server = server
        self.history = history
        try:
            checkpoint = await history.load_checkpoint()
            if checkpoint is None and await history.has_historical_values():
                raise ValueError(
                    "historian contains values without a complete simulator checkpoint; "
                    "restart with --reset"
                )
            if checkpoint is None:
                now = self._wall_time()
                start = now - timedelta(hours=self.history_hours)
                elapsed = 0.0
            else:
                start, elapsed = self._validate_checkpoint(checkpoint)
        except Exception:
            await history.stop()
            self.history = None
            self.server = None
            raise
        await self._create_address_space(namespace)
        self.simulator = PlantSimulator(
            seed=self.seed,
            start_at=start,
            integration_step_seconds=self.integration_step_seconds,
            scenario_cycle_seconds=self.scenario_cycle_seconds,
        )
        if elapsed:
            self.simulator.advance(elapsed)
        resumed_after_gap = False
        if checkpoint is not None:
            wall_elapsed = max(
                (self._wall_time() - self.simulator.start_at).total_seconds(),
                0.0,
            )
            wall_sample = math.floor(wall_elapsed / self.sample_seconds) * self.sample_seconds
            checkpoint_sample = (
                math.ceil(self.simulator.elapsed_seconds / self.sample_seconds)
                * self.sample_seconds
            )
            resume_elapsed = max(wall_sample, checkpoint_sample)
            missing_seconds = resume_elapsed - self.simulator.elapsed_seconds
            if missing_seconds > 0:
                self.simulator.advance(missing_seconds)
                resumed_after_gap = True
        await self._prepare_history(
            resume=checkpoint is not None,
            resumed_after_gap=resumed_after_gap,
        )
        await server.start()
        self._task = asyncio.create_task(self._realtime_loop())
        LOGGER.info("OPC UA server ready at %s with %d signals", self.endpoint, len(self.nodes))

    def _wall_time(self) -> datetime:
        value = self.wall_clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("wall clock must include a UTC offset")
        return value.astimezone(UTC).replace(microsecond=0)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self.server:
            await self.server.stop()
        if self.history:
            await self.history.stop()

    async def _create_address_space(self, namespace: int) -> None:
        assert self.server is not None
        root = await self.server.nodes.objects.add_object(namespace, "Plant")
        self.heartbeat_node = await root.add_variable(
            ua.NodeId(HEALTH_NODE_ID, namespace),
            "SimulatorHeartbeat",
            ua.Variant(0.0, ua.VariantType.Double),
        )
        areas = await root.add_object(namespace, "Areas")
        loops = await root.add_object(namespace, "ControlLoops")
        area_nodes: dict[str, Any] = {}
        equipment_nodes: dict[tuple[str, str], Any] = {}
        loop_nodes: dict[str, Any] = {}
        for signal in self.catalog.signals:
            if signal.scope == "control_loop":
                parent = loop_nodes.get(signal.equipment_id)
                if parent is None:
                    parent = await loops.add_object(namespace, signal.equipment_id)
                    loop_nodes[signal.equipment_id] = parent
            else:
                area_parent = area_nodes.get(signal.area_code)
                if area_parent is None:
                    area_parent = await areas.add_object(namespace, signal.area_code)
                    area_nodes[signal.area_code] = area_parent
                key = (signal.area_code, signal.equipment_id)
                parent = equipment_nodes.get(key)
                if parent is None:
                    parent = await area_parent.add_object(namespace, signal.equipment_id)
                    equipment_nodes[key] = parent
            initial: float | str | bool = 0.0
            if signal.data_type == "string":
                initial = "NORMAL"
            elif signal.data_type == "boolean":
                initial = True
            node = await parent.add_variable(
                ua.NodeId(signal.node_identifier, namespace),
                signal.node_identifier.rsplit(".", 1)[-1],
                ua.Variant(initial, _variant_type(signal)),
            )
            await node.add_property(namespace, "SignalId", signal.signal_id)
            await node.add_property(namespace, "EngineeringUnit", signal.engineering_unit)
            await node.add_property(namespace, "DescriptionPtBr", signal.description)
            self.nodes[signal.signal_id] = node

    def _checkpoint(self) -> dict[str, object]:
        assert self.simulator is not None
        return {
            "schema": CHECKPOINT_SCHEMA,
            "benchmark_version": BENCHMARK_VERSION,
            "namespace_uri": NAMESPACE_URI,
            "catalog_digest": f"sha256:{self.catalog.digest}",
            "seed": self.seed,
            "start_at": self.simulator.start_at.isoformat(),
            "elapsed_seconds": self.simulator.elapsed_seconds,
            "integration_step_seconds": self.integration_step_seconds,
            "sample_seconds": self.sample_seconds,
            "scenario_cycle_seconds": self.scenario_cycle_seconds,
        }

    def _validate_checkpoint(self, value: object) -> tuple[datetime, float]:
        if not isinstance(value, dict) or set(value) != _CHECKPOINT_KEYS:
            raise ValueError("historian simulator checkpoint has an invalid shape")
        expected = {
            "schema": CHECKPOINT_SCHEMA,
            "benchmark_version": BENCHMARK_VERSION,
            "namespace_uri": NAMESPACE_URI,
            "catalog_digest": f"sha256:{self.catalog.digest}",
            "seed": self.seed,
            "integration_step_seconds": self.integration_step_seconds,
            "sample_seconds": self.sample_seconds,
            "scenario_cycle_seconds": self.scenario_cycle_seconds,
        }
        for field, required in expected.items():
            if value[field] != required:
                raise ValueError(f"historian simulator checkpoint mismatch: {field}")
        try:
            start = datetime.fromisoformat(str(value["start_at"]))
            elapsed = float(value["elapsed_seconds"])
        except (TypeError, ValueError) as error:
            raise ValueError("historian simulator checkpoint has invalid time") from error
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("historian simulator checkpoint start_at must include UTC offset")
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("historian simulator checkpoint elapsed time is invalid")
        return start.astimezone(UTC), elapsed

    async def _prepare_history(self, *, resume: bool, resumed_after_gap: bool = False) -> None:
        assert self.history is not None
        assert self.simulator is not None
        for node in self.nodes.values():
            await self.history.new_historized_node(node.nodeid, period=None, count=0)
        if resume:
            await self._write_frame(
                self.simulator.snapshot(),
                history=resumed_after_gap,
            )
            return
        if self.history_hours <= 0:
            await self._write_frame(self.simulator.snapshot(), history=False)
            await self.history.save_checkpoint(self._checkpoint())
            return
        frames = int(self.history_hours * 3600 / self.sample_seconds)
        pending: dict[str, list[ua.DataValue]] = defaultdict(list)
        for _ in range(frames):
            frame = self.simulator.advance(self.sample_seconds)
            for observation in frame.observations:
                signal = self.signal_by_id[observation.signal_id]
                pending[observation.signal_id].append(
                    _data_value(observation, signal, frame.timestamp)
                )
            if sum(map(len, pending.values())) >= 100_000:
                await self._flush(pending, enforce_retention=False)
        await self._flush(pending, enforce_retention=False)
        await self._write_frame(self.simulator.snapshot(), history=False)
        await self.history.save_checkpoint(self._checkpoint())

    async def _flush(
        self,
        pending: dict[str, list[ua.DataValue]],
        *,
        enforce_retention: bool,
    ) -> None:
        assert self.history is not None
        try:
            for signal_id, values in pending.items():
                await self.history.save_node_values(
                    self.nodes[signal_id].nodeid,
                    values,
                    commit=False,
                    enforce_retention=enforce_retention,
                )
            await self.history.commit_pending()
        except Exception:
            await self.history.rollback_pending()
            raise
        pending.clear()

    async def _write_frame(self, frame: SimulationFrame, *, history: bool) -> None:
        assert self.history is not None
        assert self.heartbeat_node is not None
        assert self.simulator is not None
        try:
            await self.heartbeat_node.write_value(
                ua.DataValue(
                    ua.Variant(self.simulator.elapsed_seconds, ua.VariantType.Double),
                    StatusCode_=ua.StatusCode(ua.StatusCodes.Good),
                    SourceTimestamp=frame.timestamp,
                    ServerTimestamp=frame.timestamp,
                )
            )
            for observation in frame.observations:
                signal = self.signal_by_id[observation.signal_id]
                value = _data_value(observation, signal, frame.timestamp)
                await self.nodes[observation.signal_id].write_value(value)
                if history:
                    await self.history.save_node_values(
                        self.nodes[observation.signal_id].nodeid,
                        (value,),
                        commit=False,
                    )
            if history:
                await self.history.save_checkpoint(self._checkpoint(), commit=False)
                await self.history.commit_pending()
        except Exception:
            if history:
                await self.history.rollback_pending()
            raise

    async def _realtime_loop(self) -> None:
        assert self.simulator is not None
        try:
            while True:
                started = asyncio.get_running_loop().time()
                await self._write_frame(
                    self.simulator.advance(self.sample_seconds),
                    history=True,
                )
                elapsed = asyncio.get_running_loop().time() - started
                await asyncio.sleep(max(self.sample_seconds - elapsed, 0.05))
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("real-time simulation loop stopped unexpectedly")
            raise
