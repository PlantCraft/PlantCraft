"""The loops LinkCraft monitors, in its own table.

A loop comes from one of two places (``origin``):

- ``processcraft``: a loop asset in PlantCraft, with its signals bound by role
  (pv, sp, op, mode, secondary) and its asset record (loop type, criticality...).
  ``sync_from_assets`` keeps name, area, signals and the record in step with
  PlantCraft. Algorithm and criticality start from the record's loop type and
  criticality (``catalog/loop_types.py``); once a person changes one here it is
  listed in ``set_here`` and a sync never touches it again (until it is reset).
- ``user``: a loop defined in LinkCraft that names PlantCraft signal ids.

Signal ids are opaque, as API v1 gives them (``<source id>:<tag>`` since D2). A ``user`` loop
saved before that names bare tags; ``signals_checked_at`` (NULL on those rows) marks the loops
whose ids were looked up in PlantCraft and stored by the id it answers (``rename_signals``,
``loops/sync.py``). A bare tag still reads until API v1 is frozen.

A loop asset without a signal for a required role is kept as an incomplete record:
listed, never analysed (``list_loops(enabled_only=True)`` leaves it out).
"""

from __future__ import annotations

from typing import Any

from linkcraft.blocks.convert import diagram_of, from_methods, methods_in, parameters_in
from linkcraft.blocks.stored import compute_placement
from linkcraft.catalog.loop_types import (
    DEFAULT_ALGORITHM,
    algorithm_id,
    type_parameters,
)
from linkcraft.catalog.presets import PresetStore
from linkcraft.config import LoopConfig
from linkcraft.db import Database, Migration, Store, add_columns
from linkcraft.loops.defaults import (
    OWNABLE,
    PRE_CATALOG_DEFAULTS,
    _setting,
    record_defaults,
)


class LoopStore(Store):
    """Loop configuration with its change history."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS workspace_loops (
        loop_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        origin TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS configuration_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT 'Engineering'
    );
    """

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns("workspace_loops", {"signals_checked_at": "TEXT"}),
        ),
    )

    def __init__(self, db: Database, presets: PresetStore):
        super().__init__(db)
        self.presets = presets
        # Parsed loops, reused while the table is unchanged (thousands of loops
        # are listed by every panel and selection rule).
        self._cache: tuple[tuple[Any, ...], list[LoopConfig]] | None = None

    def signature(self) -> tuple[Any, ...]:
        """Changes whenever a loop is added, removed or edited."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*), MAX(updated_at), TOTAL(LENGTH(payload_json)) FROM workspace_loops"
            ).fetchone()
        return tuple(row)

    def sync_from_assets(self, loops: list[LoopConfig], *, actor: str = "System") -> dict[str, int]:
        """Bring loops read from PlantCraft assets into the table.

        New loops are added; known PlantCraft loops get the name, place and
        signals from PlantCraft and keep their CPM settings. A PlantCraft
        loop whose asset disappeared is disabled (never deleted: its history
        stays). A loop someone defined here (origin ``user``) is never touched.
        """

        now = self._now()
        added = updated = disabled = 0
        seen = {loop.loop_id for loop in loops}
        with self._lock, self._connect() as connection:
            rows = {
                row["loop_id"]: row
                for row in connection.execute(
                    "SELECT loop_id, payload_json, origin FROM workspace_loops"
                ).fetchall()
            }
            for loop in loops:
                row = rows.get(loop.loop_id)
                if row is None:
                    payload = loop
                    added += 1
                elif row["origin"] != "processcraft":
                    continue
                else:
                    current = LoopConfig.model_validate_json(row["payload_json"])
                    set_here = list(current.set_here)
                    if current.asset_record is None:
                        # Synced before the asset catalog: an algorithm or criticality other
                        # than the old defaults was a person's choice.
                        set_here += [
                            key
                            for key, old_default in PRE_CATALOG_DEFAULTS.items()
                            if _setting(current, key) != old_default and key not in set_here
                        ]
                    metadata = {**current.metadata, **loop.metadata}
                    metadata.pop("asset_missing", None)
                    if "criticality" in set_here:
                        metadata["criticality"] = _setting(current, "criticality")
                    payload = current.model_copy(
                        update={
                            "name": loop.name,
                            "area": loop.area,
                            "service": loop.service,
                            "unit": loop.unit,
                            "signals": loop.signals,
                            "metadata": metadata,
                            "asset_record": loop.asset_record,
                            "set_here": set_here,
                            "profile_id": current.profile_id
                            if "profile_id" in set_here
                            else loop.profile_id,
                            "enabled": current.enabled
                            or bool(current.metadata.get("asset_missing")),
                        }
                    )
                    if payload == current:
                        continue
                    updated += 1
                self._write(connection, payload, "processcraft", now, actor, "synced")
            for loop_id, row in rows.items():
                if row["origin"] != "processcraft" or loop_id in seen:
                    continue
                current = LoopConfig.model_validate_json(row["payload_json"])
                if current.metadata.get("asset_missing"):
                    continue
                payload = current.model_copy(
                    update={
                        "enabled": False,
                        "metadata": {**current.metadata, "asset_missing": True},
                    }
                )
                self._write(connection, payload, "processcraft", now, actor, "asset_missing")
                disabled += 1
        return {"added": added, "updated": updated, "disabled": disabled}

    def _write(
        self, connection: Any, loop: LoopConfig, origin: str, now: str, actor: str, event: str
    ) -> None:
        payload = self._json(loop.model_dump(mode="json"))
        connection.execute(
            """
            INSERT INTO workspace_loops (loop_id, payload_json, origin, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(loop_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                origin = excluded.origin,
                updated_at = excluded.updated_at
            """,
            (loop.loop_id, payload, origin, now, now),
        )
        connection.execute(
            """
            INSERT INTO configuration_events
            (entity_type, entity_id, event_type, payload_json, created_at, created_by)
            VALUES ('loop', ?, ?, ?, ?, ?)
            """,
            (loop.loop_id, event, payload, now, actor),
        )

    def list_loops(self, *, enabled_only: bool = False) -> list[LoopConfig]:
        signature = self.signature()
        if self._cache is None or self._cache[0] != signature:
            with self._lock, self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload_json FROM workspace_loops ORDER BY loop_id"
                ).fetchall()
            self._cache = (
                signature,
                [LoopConfig.model_validate_json(row["payload_json"]) for row in rows],
            )
        loops = self._cache[1]
        if enabled_only:  # the loops a round analyses: enabled and complete
            return [loop for loop in loops if loop.enabled and not loop.incomplete]
        return list(loops)

    def get_loop(self, loop_id: str) -> LoopConfig | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workspace_loops WHERE loop_id = ?",
                (loop_id,),
            ).fetchone()
        return LoopConfig.model_validate_json(row["payload_json"]) if row else None

    def save_loop(
        self,
        loop: LoopConfig,
        *,
        actor: str = "Engineering",
        origin: str | None = None,
    ) -> None:
        """Create or update a loop; an existing loop keeps its origin unless one is given.

        An algorithm or criticality that differs from the stored one is a person's choice: it is
        added to ``set_here`` so a sync from PlantCraft keeps it.
        """

        now = self._now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT origin, payload_json FROM workspace_loops WHERE loop_id = ?",
                (loop.loop_id,),
            ).fetchone()
            if row is not None:
                stored = LoopConfig.model_validate_json(row["payload_json"])
                changed = [
                    key
                    for key in OWNABLE
                    if _setting(loop, key) != _setting(stored, key) and key not in loop.set_here
                ]
                if changed:
                    loop = loop.model_copy(update={"set_here": [*loop.set_here, *changed]})
            kept = origin or (row["origin"] if row else "user")
            self._write(connection, loop, kept, now, actor, "saved")

    def reset_settings(
        self, loop_id: str, keys: list[str], *, actor: str = "Engineering"
    ) -> LoopConfig | None:
        """Give ``keys`` back to the asset record: its derived value, no longer set here."""

        loop = self.get_loop(loop_id)
        if loop is None:
            return None
        defaults = record_defaults(loop)
        metadata = dict(loop.metadata)
        update: dict[str, Any] = {"set_here": [key for key in loop.set_here if key not in keys]}
        if "profile_id" in keys:
            update["profile_id"] = defaults["profile_id"]
        if "criticality" in keys:
            metadata["criticality"] = defaults["criticality"]
            update["metadata"] = metadata
        reset = loop.model_copy(update=update)
        now = self._now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT origin FROM workspace_loops WHERE loop_id = ?", (loop_id,)
            ).fetchone()
            self._write(connection, reset, row["origin"], now, actor, "reset")
        return reset

    def unchecked_signal_loops(self) -> list[LoopConfig]:
        """Loops defined here whose signal ids were never looked up in PlantCraft."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM workspace_loops
                WHERE origin = 'user' AND signals_checked_at IS NULL ORDER BY loop_id
                """
            ).fetchall()
        return [LoopConfig.model_validate_json(row["payload_json"]) for row in rows]

    def rename_signals(
        self, loop_id: str, renamed: dict[str, str], *, actor: str = "System"
    ) -> LoopConfig | None:
        """Store a loop's signals by the ids PlantCraft answered (``{role: id}``), once.

        The loop is marked checked; an empty ``renamed`` only marks it.
        """

        now = self._now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT origin, payload_json FROM workspace_loops WHERE loop_id = ?", (loop_id,)
            ).fetchone()
            if row is None:
                return None
            loop = LoopConfig.model_validate_json(row["payload_json"])
            if renamed:
                signals = loop.signals.model_copy(update=renamed)
                loop = loop.model_copy(update={"signals": signals})
                self._write(connection, loop, row["origin"], now, actor, "signal_ids_renamed")
            connection.execute(
                "UPDATE workspace_loops SET signals_checked_at = ? WHERE loop_id = ?",
                (now, loop_id),
            )
        return loop

    def origins(self) -> dict[str, str]:
        """Where each loop came from: ``processcraft`` (an asset) or ``user``."""

        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT loop_id, origin FROM workspace_loops").fetchall()
        return {row["loop_id"]: row["origin"] for row in rows}

    def delete_loop(self, loop_id: str, *, actor: str = "Engineering") -> None:
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM workspace_loops WHERE loop_id = ?", (loop_id,))
            connection.execute(
                """
                INSERT INTO configuration_events
                (entity_type, entity_id, event_type, payload_json, created_at, created_by)
                VALUES ('loop', ?, 'deleted', '{}', ?, ?)
                """,
                (loop_id, now, actor),
            )

    def effective_method_config(
        self,
        loop: LoopConfig,
        *,
        profile_id: str | None = None,
        method_ids: list[str] | None = None,
        parameters: dict[str, dict[str, Any]] | None = None,
        cache: dict[Any, Any] | None = None,
    ) -> dict[str, Any]:
        """The loop's algorithm and its method parameters, layer by layer.

        ``defaults`` (the site's method defaults, then the loop type's) sit under the
        diagram's own parameters; ``overrides`` (what a person set on the loop, then a run's
        own) sit over them. ``parameters`` is the whole merge, as people read it.
        ``cache`` (a dict kept for one round) saves re-reading algorithms and defaults per loop.
        """

        cache = {} if cache is None else cache
        chosen = algorithm_id(profile_id or loop.profile_id)
        key = ("profile", chosen)
        if key not in cache:
            cache[key] = self.presets.get_profile(chosen) or self.presets.get_profile(
                DEFAULT_ALGORITHM
            )
        if "defaults" not in cache:
            cache["defaults"] = self.presets.list_method_defaults()
        profile = cache[key] or {}
        config = profile.get("method_config") or {}
        explicit = method_ids or loop.enabled_methods
        diagram = from_methods(explicit) if explicit else diagram_of(config)
        resolved_ids = methods_in(diagram)
        defaults: dict[str, dict[str, Any]] = {
            method_id: dict(values)
            for method_id, values in cache["defaults"].items()
            if method_id in resolved_ids
        }
        # The loop type's parameters (how fast the process is) sit under the algorithm's.
        record = loop.asset_record
        for method_id, values in type_parameters(record.loop_type if record else None).items():
            defaults.setdefault(method_id, {}).update(values)
        overrides: dict[str, dict[str, Any]] = {}
        for layer in (loop.method_parameters, parameters or {}):
            for method_id, values in layer.items():
                overrides.setdefault(method_id, {}).update(values)
        merged: dict[str, dict[str, Any]] = {}
        for layer in (defaults, parameters_in(diagram), overrides):
            for method_id, values in layer.items():
                merged.setdefault(method_id, {}).update(values)
        return {
            "profile_id": str(profile.get("profile_id") or chosen),
            "method_ids": resolved_ids,
            "parameters": merged,
            "defaults": defaults,
            "overrides": overrides,
            "diagram": diagram,
            # The algorithm version this diagram is (none when the loop picked its own methods).
            "version": None if explicit else int(profile.get("version") or 1),
            # Where its analysis runs on the suite's compute workers.
            "compute": compute_placement(None if explicit else config.get("compute")),
        }
