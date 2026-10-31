"""The configuration database: sources, signals, settings and requests to the collector.

Only the server writes these tables (docs/boundary.md); the collector rereads them
every few seconds (``version`` changes on every write) and never writes them.

- A **source** is a plant system HistCraft reads (PI Web API, OPC UA, MQTT, Modbus, SQL, CSV
  files another application keeps writing), an **import** (``import-<n>``, a CSV file loaded
  once from Import & export, its values written as they were and kept until it is deleted) or
  an app's **derived** source, ``app-<app id>``, which only that app writes (through
  PlantCraft). Derived signals carry the ``subject`` they describe (a ref such as
  ``asset:fic-101``) and the ``result`` kind they hold (``loop_health``). The reserved
  source ``system`` ("System", kind ``system``) holds the suite's own health (each service
  up, latency, CPU, memory, errors; the disk; the backups), written by PlantCraft only
  and kept 90 days (docs/data-layer.md).
- A **point** is one signal of a source: its tag (unique in its source), its address
  on the server, how it is read and how it is compressed. Its signal id, the one
  PlantCraft and every app use, is ``<source id>:<tag>`` (API v1).
- A point's **mode** says where its history comes from (docs/data-layer.md): read
  from the source on each request (``source``), collected and archived here
  (``archive``), or both. Empty means the source's mode, and an empty source mode
  means the kind's default (``DEFAULT_MODES``).
- **Settings** come in three levels and the most specific wins (app standard, D8): the
  general ones (``DEFAULT_SETTINGS``, the Settings page), a source's overrides for its points
  (``SOURCE_SETTINGS``, empty = general), and a point's own values (``POINT_SETTINGS``).
  A point's ``retention_days`` is empty when it inherits; its ``inherits`` column lists which
  of ``scan_seconds``, ``deviation`` and ``max_seconds`` it takes from its source or the
  general settings (their stored value is then only the one resolved when it was added).
  A retention of 0 days keeps the values forever. A derived point an app sets up itself
  carries ``managed_by`` (e.g. ``link:<schedule>``): its retention and compression are then
  changed only by that app (a 409 for people).
  Points read from the store carry the effective values and ``origins`` (``point``,
  ``source`` or ``general``) for each. A number point that inherits its deviation and has no
  known range (an OPC UA server without ``EURange``, most of them) takes the share of its value
  instead: ``deviation_percent`` is then set and the compressor applies it to each archived
  value (``deviation`` stays 0); else ``deviation_percent`` is None.
- A **request** asks the collector for something it does from the plant network
  (browse a server, test a connection); its answer comes back in the archive tables.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from typing import Any

from histcraft.catalog.expressions import FormulaError, parse
from histcraft.catalog.models import (
    _COLUMN,
    _THUMBPRINT,
    ARCHIVE_ONLY_KINDS,
    CALC_SOURCE,
    COLLECTED,
    DEFAULT_MODES,
    DEFAULT_SETTINGS,
    DROPPED_APPS,
    INHERITABLE,
    INTEGRATION_FIELDS,
    LAB_SOURCE,
    LIVE_KINDS,
    MANAGED,
    NOT_COLLECTED,
    ONLY_ARCHIVED,
    POINT_SETTINGS,
    PROFILES,
    QUALITY_KINDS,
    RETIRED_APPS,
    RETIRED_DAYS,
    SOURCE_SETTINGS,
    SYSTEM_RETENTION_DAYS,
    SYSTEM_SOURCE,
    WRITTEN_KINDS,
    ZERO_SETTINGS,
    CatalogError,
    PointIn,
    PointPatch,
    SourceIn,
    derived_source,
    secret_follows,
    split_signal,
)
from histcraft.db import Database, Store
from histcraft.i18n import t
from histcraft.kinds import on_change

# How long a source's history is kept (``source_events``).
SOURCE_EVENT_DAYS = 90


class CatalogStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS sources (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        namespace_uri TEXT NOT NULL DEFAULT '',
        username TEXT NOT NULL DEFAULT '',
        password_env TEXT NOT NULL DEFAULT '',
        secret TEXT NOT NULL DEFAULT '',
        mode TEXT NOT NULL DEFAULT '',
        options TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        created TEXT NOT NULL,
        updated TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL REFERENCES sources(id),
        tag TEXT NOT NULL,
        address TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'number',
        step INTEGER NOT NULL DEFAULT 0,
        low REAL,
        high REAL,
        scan_seconds REAL NOT NULL,
        deviation REAL NOT NULL,
        max_seconds REAL NOT NULL,
        retention_days INTEGER,
        mode TEXT NOT NULL DEFAULT '',
        subject TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        created TEXT NOT NULL,
        updated TEXT NOT NULL,
        UNIQUE(source_id, tag),
        UNIQUE(source_id, address)
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        source_id TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '{}',
        created_ms INTEGER NOT NULL,
        created_by TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS retired_points (
        id INTEGER PRIMARY KEY,
        signal TEXT NOT NULL,
        point TEXT NOT NULL,
        retired_ms INTEGER NOT NULL,
        retired_by TEXT NOT NULL DEFAULT ''
    );

    -- Each source's history (H13): when the collector found it connected, disconnected again.
    CREATE TABLE IF NOT EXISTS source_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL,
        at_ms INTEGER NOT NULL,
        status TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_source_events ON source_events(source_id, at_ms);

    CREATE TABLE IF NOT EXISTS catalog_version (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        version INTEGER NOT NULL
    );
    INSERT INTO catalog_version VALUES (1, 0) ON CONFLICT DO NOTHING;
    """
    COLUMNS = (
        # A source's overrides of the general settings (2026-10-20, D8); NULL: general.
        ("sources", "retention_days", "INTEGER"),
        ("sources", "default_scan_seconds", "REAL"),
        ("sources", "default_deviation_percent", "REAL"),
        ("sources", "default_max_seconds", "REAL"),
        # Which of scan_seconds, deviation, max_seconds a point inherits (comma separated);
        # empty for points added before: they keep the values they were given.
        ("points", "inherits", "TEXT NOT NULL DEFAULT ''"),
        # What sets a derived point's retention and compression (e.g. ``link:<schedule>``,
        # 2026-10-25, H1); empty: people set them here.
        ("points", "managed_by", "TEXT NOT NULL DEFAULT ''"),
        # The runs a ``runs`` point keeps (H2); NULL for other points.
        ("points", "keep_runs", "INTEGER"),
        # Its compression profile ('' standard, fine, none) and own exception (NULL: the
        # profile's), round 8 D1.
        ("points", "profile", "TEXT NOT NULL DEFAULT ''"),
        ("points", "exception", "REAL"),
        # Lines only: the least time between archived values (NULL or 0: none; PI's CompMin).
        ("points", "min_seconds", "REAL"),
        # Where its range comes from: source, edited, suggested, or '' (none yet), D2.
        ("points", "range_origin", "TEXT NOT NULL DEFAULT ''"),
        # The integration around a source (H13, ``INTEGRATION_FIELDS``).
        ("sources", "owners", "TEXT NOT NULL DEFAULT '[]'"),
        ("sources", "contact", "TEXT NOT NULL DEFAULT ''"),
        ("sources", "heartbeat_seconds", "INTEGER NOT NULL DEFAULT 0"),
    )

    TIMES = (("sources", "id", ("created", "updated")), ("points", "id", ("created", "updated")))

    def __init__(self, db: Database):
        super().__init__(db)

    # Version ------------------------------------------------------------------------

    def version(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT version FROM catalog_version").fetchone()[0])

    @staticmethod
    def _bump(connection: Any) -> None:
        connection.execute("UPDATE catalog_version SET version = version + 1")

    # Settings -----------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        stored = {row["key"]: self._loads(row["value"], None) for row in rows}
        return {key: stored.get(key, default) for key, default in DEFAULT_SETTINGS.items()}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        unknown = set(changes) - set(DEFAULT_SETTINGS)
        if unknown:
            raise CatalogError(t("Unknown setting: {name}.", name=sorted(unknown)[0]), 422)
        checked: dict[str, float] = {}
        for key, value in changes.items():
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise CatalogError(t("{name} must be a number.", name=key), 422) from exc
            if number < 0 or (number == 0 and key not in ZERO_SETTINGS) or number > 36500 * 86400:
                raise CatalogError(t("{name} must be a positive number.", name=key), 422)
            checked[key] = int(number) if key == "retention_days" else number
        with self._lock, self._connect() as connection:
            for key, value in checked.items():
                connection.execute(
                    "INSERT INTO settings VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, self._json(value)),
                )
            self._bump(connection)
        return self.settings()

    # Sources --------------------------------------------------------------------------

    def sources(self) -> list[dict[str, Any]]:
        """Every source, with its effective mode and its point count (never its password)."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.*, (SELECT COUNT(*) FROM points p WHERE p.source_id = s.id) AS points
                FROM sources s ORDER BY s.name
                """
            ).fetchall()
        return [_source(row) for row in rows]

    def source(self, source_id: str) -> dict[str, Any]:
        found = next((item for item in self.sources() if item["id"] == source_id), None)
        if found is None:
            raise CatalogError(t("Source {id} not found.", id=source_id), 404)
        return found

    def secret(self, source_id: str) -> str:
        """The stored (encrypted) password of a source, for the readers; never for pages."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT secret FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        return str(row["secret"]) if row else ""

    def save_source(
        self, data: SourceIn, *, create: bool, secret: str | None = None
    ) -> dict[str, Any]:
        """Add or change a source; ``secret`` is the encrypted password (``None`` keeps it)."""

        now = self._now()
        # On an update only the overrides the caller sent change (null clears one).
        overrides = {
            key: getattr(data, key)
            for key in SOURCE_SETTINGS
            if create or key in data.model_fields_set
        }
        integration = {
            key: self._json(data.owners) if key == "owners" else getattr(data, key)
            for key in INTEGRATION_FIELDS
            if create or key in data.model_fields_set
        }
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT kind, secret, endpoint, username FROM sources WHERE id = ?", (data.id,)
            ).fetchone()
            if create and row:
                raise CatalogError(t("A source with id {id} already exists.", id=data.id))
            if not create and not row:
                raise CatalogError(t("Source {id} not found.", id=data.id), 404)
            if row and row["kind"] != data.kind:
                raise CatalogError(t("The kind of a source cannot change."), 422)
            if secret is None and row and row["secret"] and not data.password_env:
                secret_follows(dict(row), data)
            stored = secret if secret is not None else (str(row["secret"]) if row else "")
            connection.execute(
                """
                INSERT INTO sources (id, name, kind, endpoint, namespace_uri, username,
                                     password_env, secret, mode, options, enabled, created,
                                     updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name, endpoint = excluded.endpoint,
                    namespace_uri = excluded.namespace_uri, username = excluded.username,
                    password_env = excluded.password_env, secret = excluded.secret,
                    mode = excluded.mode, options = excluded.options,
                    enabled = excluded.enabled, updated = excluded.updated
                """,
                (
                    data.id,
                    data.name.strip(),
                    data.kind,
                    data.endpoint,
                    data.namespace_uri.strip(),
                    data.username.strip(),
                    data.password_env,
                    stored,
                    data.mode,
                    self._json(data.options),
                    int(data.enabled),
                    now,
                    now,
                ),
            )
            changes = {**overrides, **integration}
            if changes:
                assignments = ", ".join(f"{key} = ?" for key in changes)
                connection.execute(
                    f"UPDATE sources SET {assignments} WHERE id = ?",
                    (*changes.values(), data.id),
                )
            self._bump(connection)
        return self.source(data.id)

    def delete_source(self, source_id: str, *, with_points: bool = False) -> int:
        """Remove a source; ``with_points`` takes its points along (their archive goes too).

        Returns the points removed. Without ``with_points`` a source that has points is refused.
        """

        with self._lock, self._connect() as connection:
            used = connection.execute(
                "SELECT COUNT(*) FROM points WHERE source_id = ?", (source_id,)
            ).fetchone()[0]
            if used and not with_points:
                raise CatalogError(
                    t("Remove the {count} signals of this source first.", count=used)
                )
            if used:
                connection.execute("DELETE FROM points WHERE source_id = ?", (source_id,))
            if not connection.execute("DELETE FROM sources WHERE id = ?", (source_id,)).rowcount:
                raise CatalogError(t("Source {id} not found.", id=source_id), 404)
            connection.execute("DELETE FROM source_events WHERE source_id = ?", (source_id,))
            self._bump(connection)
        return int(used)

    # A source's history (H13) -----------------------------------------------------------

    def add_source_events(self, events: Iterable[tuple[str, int, str, str]]) -> None:
        """Keep each ``(source_id, at_ms, status, detail)`` the collector saw change; older
        than ``SOURCE_EVENT_DAYS`` days go."""

        rows = [(sid, int(at), status, str(detail)[:500]) for sid, at, status, detail in events]
        if not rows:
            return
        cutoff = int(time.time() * 1000) - SOURCE_EVENT_DAYS * 86_400_000
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO source_events (source_id, at_ms, status, detail) VALUES (?, ?, ?, ?)",
                rows,
            )
            connection.execute("DELETE FROM source_events WHERE at_ms < ?", (cutoff,))

    def source_events(self, source_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """A source's changes of state, the newest first."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT at_ms, status, detail FROM source_events WHERE source_id = ?"
                " ORDER BY at_ms DESC, id DESC LIMIT ?",
                (source_id, max(1, min(int(limit), 1000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def last_source_statuses(self) -> dict[str, str]:
        """Each source's last recorded state (where the collector takes up after a restart)."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.source_id, e.status FROM source_events e
                JOIN (SELECT source_id, MAX(id) AS id FROM source_events GROUP BY source_id) last
                  ON last.id = e.id
                """
            ).fetchall()
        return {str(row["source_id"]): str(row["status"]) for row in rows}

    def trust_server(self, source_id: str, thumbprint: str) -> dict[str, Any]:
        """Pin the SHA-256 of an OPC UA source's server certificate (G2); the source."""

        pinned = thumbprint.strip().upper()
        if pinned and not _THUMBPRINT.match(pinned):
            raise CatalogError(t("server_thumbprint is a SHA-256 in AB:CD:... form."), 422)
        source = self.source(source_id)
        if source["kind"] != "opcua":
            raise CatalogError(t("Only an OPC UA source has a server certificate."), 422)
        options = {**source["options"], "server_thumbprint": pinned}
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE sources SET options = ?, updated = ? WHERE id = ?",
                (self._json(options), self._now(), source_id),
            )
            self._bump(connection)
        return self.source(source_id)

    def set_options(self, source_id: str, options: dict[str, Any]) -> dict[str, Any]:
        """Replace a source's options as they are (the server's own bookkeeping, such as an
        import's files); the source."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE sources SET options = ?, updated = ? WHERE id = ?",
                (self._json(options), self._now(), source_id),
            )
            self._bump(connection)
        return self.source(source_id)

    def drop_retired(self, apps: Iterable[str] = DROPPED_APPS) -> list[str]:
        """Remove the derived sources of apps dropped from the suite, with their points; the ids."""

        dropped: list[str] = []
        for app in apps:
            source_id = derived_source(app)
            with self._connect() as connection:
                found = connection.execute(
                    "SELECT 1 FROM sources WHERE id = ? AND kind = 'derived'", (source_id,)
                ).fetchone()
            if found:
                self.delete_source(source_id, with_points=True)
                dropped.append(source_id)
        return dropped

    # Points -----------------------------------------------------------------------------

    _POINTS = """
        SELECT p.*, s.kind AS source_kind, s.mode AS source_mode, s.enabled AS source_enabled,
            s.retention_days AS source_retention_days,
            s.default_scan_seconds AS source_default_scan_seconds,
            s.default_deviation_percent AS source_default_deviation_percent,
            s.default_max_seconds AS source_default_max_seconds
        FROM points p JOIN sources s ON s.id = p.source_id
    """

    def points(
        self,
        *,
        q: str = "",
        source_id: str | None = None,
        enabled_only: bool = False,
        modes: tuple[str, ...] | None = None,
        app: str | None = None,
        subject: str | None = None,
        result: str | None = None,
    ) -> list[dict[str, Any]]:
        """Points with their ``signal`` id and effective ``mode``; ``modes`` keeps only those.

        ``app``, ``subject`` and ``result`` find derived signals (an app's, about an asset...).
        """

        clauses, args = [], []
        if app:
            clauses.append("p.source_id = ?")
            args.append(derived_source(app))
        if subject:
            clauses.append("p.subject = ?")
            args.append(subject)
        if result:
            clauses.append("p.result = ?")
            args.append(result)
        if q:
            clauses.append("(p.tag LIKE ? OR p.name LIKE ? OR p.description LIKE ?)")
            like = f"%{q}%"
            args += [like, like, like]
        if source_id:
            clauses.append("p.source_id = ?")
            args.append(source_id)
        if enabled_only:
            clauses.append("p.enabled = 1 AND s.enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        general = self.settings()
        with self._connect() as connection:
            rows = connection.execute(
                f"{self._POINTS} {where} ORDER BY p.source_id, p.tag", args
            ).fetchall()
        items = [_point(row, general) for row in rows]
        return [item for item in items if modes is None or item["mode"] in modes]

    def find(self, signal_id: str) -> dict[str, Any] | None:
        """The point of a signal id (``<source id>:<tag>``), or ``None``.

        A bare tag (no known source before ``:``) finds the one point with that tag; ``None``
        when no source or several have it (PlantCraft's asset pages may send bare tags).
        """

        source_id, tag = split_signal(signal_id)
        general = self.settings()
        with self._connect() as connection:
            if source_id:
                row = connection.execute(
                    f"{self._POINTS} WHERE p.source_id = ? AND p.tag = ?", (source_id, tag)
                ).fetchone()
                if row:
                    return _point(row, general)
            rows = connection.execute(
                f"{self._POINTS} WHERE p.tag = ? LIMIT 2", (signal_id,)
            ).fetchall()
        return _point(rows[0], general) if len(rows) == 1 else None

    def find_many(self, signal_ids: Iterable[str]) -> dict[str, dict[str, Any] | None]:
        """``find`` of many signal ids: one query per source named, the settings read once.

        Ids not found that way (a bare tag, a tag with ``:`` in it) go through ``find``.
        """

        wanted = list(dict.fromkeys(signal_ids))
        by_source: dict[str, list[str]] = {}
        for signal_id in wanted:
            source_id, tag = split_signal(signal_id)
            if source_id:
                by_source.setdefault(source_id, []).append(tag)
        general = self.settings()
        found: dict[str, dict[str, Any] | None] = {}
        with self._connect() as connection:
            for source_id, tags in by_source.items():
                for offset in range(0, len(tags), 500):
                    part = tags[offset : offset + 500]
                    marks = ",".join("?" for _ in part)
                    rows = connection.execute(
                        f"{self._POINTS} WHERE p.source_id = ? AND p.tag IN ({marks})",
                        (source_id, *part),
                    ).fetchall()
                    for row in rows:
                        item = _point(row, general)
                        found[item["signal"]] = item
        for signal_id in wanted:
            if signal_id not in found:
                found[signal_id] = self.find(signal_id)
        return {signal_id: found[signal_id] for signal_id in wanted}

    def point(self, signal_id: str) -> dict[str, Any]:
        found = self.find(signal_id)
        if found is None:
            raise CatalogError(t("Signal {id} not found.", id=signal_id), 404)
        return found

    @staticmethod
    def signal_limit() -> int | None:
        """The most points the installation lets the Historian record (``MAX_SIGNALS`` of the
        installation file, ``PLANTCRAFT_MAX_SIGNALS``); None: no limit. Points the apps write
        (results) do not count."""

        raw = (os.environ.get("PLANTCRAFT_MAX_SIGNALS") or "").strip()
        return int(raw) if raw.isdigit() and int(raw) > 0 else None

    def add_points(self, items: list[PointIn], *, range_origin: str = "source") -> dict[str, Any]:
        """Add points; a tag or address its source already has is skipped and reported.

        A point given a range gets ``range_origin`` (``source``: the server's; a points CSV
        passes ``edited``)."""

        general = self.settings()
        now = self._now()
        added, skipped = [], []
        # Calculated points: each formula checked first, against the points it reads.
        refused = self._check_formulas(items)
        with self._lock, self._connect() as connection:
            if any(item.source_id == CALC_SOURCE for item in items):
                connection.execute(
                    "INSERT INTO sources (id, name, kind, endpoint, mode, options, enabled,"
                    " created, updated) VALUES (?, 'Calculated', 'calc', '', 'archive', '{}', 1,"
                    " ?, ?) ON CONFLICT DO NOTHING",
                    (CALC_SOURCE, now, now),
                )
            rows = connection.execute(
                "SELECT id, kind, retention_days, default_scan_seconds,"
                " default_deviation_percent, default_max_seconds FROM sources"
            ).fetchall()
            kinds = {row["id"]: row["kind"] for row in rows}
            limit = self.signal_limit()
            room = None
            if limit is not None:
                written = [row["id"] for row in rows if row["kind"] in WRITTEN_KINDS] or [""]
                marks = ",".join("?" for _ in written)
                found = connection.execute(
                    f"SELECT COUNT(*) AS n FROM points WHERE source_id NOT IN ({marks})", written
                ).fetchone()
                room = max(0, limit - int(found["n"]))
            # The defaults of each source's new points: its overrides, else the general ones.
            defaults = {row["id"]: _source_defaults(row, general) for row in rows}
            for item in items:
                signal = f"{item.source_id}:{item.tag}"
                kind = kinds.get(item.source_id)
                if kind is None:
                    skipped.append(
                        {"signal": signal, "tag": item.tag, "reason": t("unknown source")}
                    )
                    continue
                if kind in WRITTEN_KINDS:
                    skipped.append(
                        {"signal": signal, "tag": item.tag, "reason": t("written by its app only")}
                    )
                    continue
                if kind not in LIVE_KINDS and item.mode in COLLECTED:
                    skipped.append({"signal": signal, "tag": item.tag, "reason": NOT_COLLECTED})
                    continue
                if kind in ARCHIVE_ONLY_KINDS and item.mode not in ("", "archive"):
                    skipped.append({"signal": signal, "tag": item.tag, "reason": t(ONLY_ARCHIVED)})
                    continue
                if signal in refused:
                    skipped.append({"signal": signal, "tag": item.tag, "reason": refused[signal]})
                    continue
                if room is not None and room <= 0:
                    skipped.append(
                        {
                            "signal": signal,
                            "tag": item.tag,
                            "reason": t(
                                "the installation's limit of {count} signals",
                                count=limit,
                            ),
                        }
                    )
                    continue
                values = _with_defaults(item, defaults[item.source_id])
                inherits = ",".join(key for key in INHERITABLE if getattr(item, key) is None)
                # A taken tag or address skips the point (an error would end a PostgreSQL
                # transaction, so the conflict is a no-op instead).
                inserted = connection.execute(
                    """
                    INSERT INTO points (source_id, tag, address, name, description, unit,
                        kind, step, low, high, scan_seconds, deviation, max_seconds,
                        retention_days, mode, enabled, created, updated, inherits, profile,
                        exception, range_origin, min_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        item.source_id,
                        item.tag,
                        item.address or item.tag,
                        item.name.strip(),
                        item.description.strip(),
                        item.unit.strip(),
                        item.kind,
                        int(item.step or on_change(item.kind)),
                        item.low,
                        item.high,
                        values["scan_seconds"],
                        values["deviation"],
                        values["max_seconds"],
                        item.retention_days,
                        item.mode,
                        int(item.enabled),
                        now,
                        now,
                        inherits,
                        item.profile or "",
                        item.exception,
                        range_origin if _has_span(item.low, item.high) else "",
                        item.min_seconds,
                    ),
                )
                if inserted.rowcount:
                    added.append(signal)
                    if room is not None:
                        room -= 1
                else:
                    skipped.append(
                        {
                            "signal": signal,
                            "tag": item.tag,
                            "reason": t("tag or address already exists"),
                        }
                    )
            if added:
                self._bump(connection)
        return {"added": added, "skipped": skipped}

    def _check_formulas(self, items: list[PointIn]) -> dict[str, str]:
        """Why each calculated point of ``items`` cannot be added, by signal (none: all fine).

        A formula reads numbers the collector archives: points of OPC UA sources in mode
        archive or both, or other calculated points (one scan later). PI and CSV points are
        read on request only, so a formula cannot follow them live.
        """

        formulas = {}
        refused: dict[str, str] = {}
        for item in items:
            if item.source_id != CALC_SOURCE:
                continue
            signal = f"{item.source_id}:{item.tag}"
            try:
                formulas[signal] = parse(item.address)
                item.address = formulas[signal].text
            except FormulaError as exc:
                refused[signal] = str(exc)
        wanted = {name for formula in formulas.values() for name in formula.signals}
        found = self.find_many(wanted - set(formulas)) if wanted else {}
        for signal, formula in formulas.items():
            for name in formula.signals:
                problem = _not_an_input(name, found.get(name), name in formulas, signal)
                if problem:
                    refused[signal] = problem
                    break
        if formulas:
            # A formula may read another calculated point, but never, through others, itself.
            graph = {
                point["signal"]: _reads(point["address"])
                for point in self.points(source_id=CALC_SOURCE)
            }
            graph.update({signal: formula.signals for signal, formula in formulas.items()})
            for signal in formulas:
                if signal not in refused and _loops(graph, signal):
                    refused[signal] = t("The formula reads itself through other signals.")
        return refused

    def update_point(self, signal_id: str, patch: PointPatch) -> dict[str, Any]:
        changes = patch.model_dump(exclude_unset=True)
        current = self.point(signal_id)
        if not changes:
            return current
        locked = sorted(set(changes) & set(MANAGED))
        if current.get("managed_by") and locked:
            raise CatalogError(
                t(
                    "{name} is set in {managed_by}.",
                    name=locked[0],
                    managed_by=current["managed_by"],
                ),
                409,
            )
        if current["source_kind"] not in LIVE_KINDS and changes.get("mode") in COLLECTED:
            raise CatalogError(NOT_COLLECTED, 422)
        archive_only = current["source_kind"] in ARCHIVE_ONLY_KINDS
        if archive_only and changes.get("mode") not in (None, "", "archive"):
            raise CatalogError(t(ONLY_ARCHIVED), 422)
        if "address" in changes:
            if current["source_kind"] != "calc":
                raise CatalogError(t("Only a calculated signal's formula can change."), 422)
            probe = PointIn(source_id=CALC_SOURCE, tag=current["tag"], address=changes["address"])
            problem = self._check_formulas([probe]).get(signal_id)
            if problem:
                raise CatalogError(problem, 422)
            changes["address"] = probe.address
        columns = {
            key: (int(value) if isinstance(value, bool) else value)
            for key, value in changes.items()
        }
        if "mode" in columns:
            columns["mode"] = columns["mode"] or ""
        if "profile" in columns:
            columns["profile"] = columns["profile"] or ""
        if "low" in columns or "high" in columns:
            # A range a person saves, a confirmed suggestion too, is theirs from then on.
            low, high = columns.get("low", current["low"]), columns.get("high", current["high"])
            columns["range_origin"] = "edited" if _has_span(low, high) else ""
        # A value sets the point's own; null makes it inherit again (the stored value stays
        # as a fallback, the column being NOT NULL). retention_days is NULL when inherited.
        inherits = {key for key in INHERITABLE if current["origins"][key] != "point"}
        for key in INHERITABLE:
            if key not in columns:
                continue
            if columns[key] is None:
                columns.pop(key)
                inherits.add(key)
            else:
                inherits.discard(key)
        columns["inherits"] = ",".join(key for key in INHERITABLE if key in inherits)
        columns["updated"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in columns)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE points SET {assignments} WHERE id = ?", (*columns.values(), current["id"])
            )
            self._bump(connection)
        return self.point(signal_id)

    def suggest_ranges(self, found: dict[int, tuple[float, float]]) -> int:
        """Put the ranges suggested from their first day on points that still have none
        (``ranges.suggest``, the collector's housekeeping): how many were set."""

        if not found:
            return 0
        now = self._now()
        count = 0
        with self._lock, self._connect() as connection:
            for point_id, (low, high) in found.items():
                count += connection.execute(
                    "UPDATE points SET low = ?, high = ?, range_origin = 'suggested', updated = ?"
                    " WHERE id = ? AND kind = 'number' AND range_origin = ''"
                    " AND (low IS NULL OR high IS NULL OR high <= low)",
                    (low, high, now, point_id),
                ).rowcount
            if count:
                self._bump(connection)
        return count

    def make_text(self, point_ids: list[int]) -> None:
        """Turn number points that read text (a MODE added while its source could not describe
        it) into text steps; the collector notices and archives their labels from then on."""

        if not point_ids:
            return
        marks = ",".join("?" for _ in point_ids)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE points SET kind = 'text', step = 1, updated = ? WHERE id IN ({marks})",
                (self._now(), *point_ids),
            )
            self._bump(connection)

    def retire_points(self, signal_ids: list[str], *, by: str = "") -> list[int]:
        """Take points out of the configuration and keep their archive: the ids retired.

        A retired point is no longer collected nor listed, and no app reads it; its row waits in
        ``retired_points`` with its archived values for ``RETIRED_DAYS``, restorable
        (:meth:`restore_points`), then the collector's housekeeping deletes it for good
        (:meth:`purge_retired`, also earlier by an admin who types the count).
        """

        retired: list[int] = []
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            for signal_id in signal_ids:
                source_id, tag = split_signal(signal_id)
                row = connection.execute(
                    "SELECT * FROM points WHERE source_id = ? AND tag = ?", (source_id, tag)
                ).fetchone()
                if row is None:
                    continue
                stored = json.dumps(dict(row))
                connection.execute(
                    "INSERT INTO retired_points (id, signal, point, retired_ms, retired_by)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (row["id"], f"{source_id}:{tag}", stored, now, by[:200]),
                )
                connection.execute("DELETE FROM points WHERE id = ?", (row["id"],))
                retired.append(int(row["id"]))
            if retired:
                self._bump(connection)
        return retired

    def retired(self) -> list[dict[str, Any]]:
        """The retired points, newest first, with when each is deleted for good (``purge_ms``)."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM retired_points ORDER BY retired_ms DESC, id"
            ).fetchall()
        found = []
        for row in rows:
            point = self._loads(row["point"], {}) or {}
            found.append(
                {
                    "id": int(row["id"]),
                    "signal": row["signal"],
                    "source_id": point.get("source_id", ""),
                    "tag": point.get("tag", ""),
                    "name": point.get("name", ""),
                    "unit": point.get("unit", ""),
                    "kind": point.get("kind", "number"),
                    "retired_ms": int(row["retired_ms"]),
                    "retired_by": row["retired_by"],
                    "purge_ms": int(row["retired_ms"]) + RETIRED_DAYS * 86_400_000,
                }
            )
        return found

    def retired_ids(self) -> set[int]:
        with self._connect() as connection:
            return {int(row["id"]) for row in connection.execute("SELECT id FROM retired_points")}

    def restore_points(self, ids: list[int]) -> dict[str, Any]:
        """Put retired points back as they were, archive included; what could not come back."""

        restored: list[str] = []
        refused: list[dict[str, Any]] = []
        with self._lock, self._connect() as connection:
            for point_id in ids:
                row = connection.execute(
                    "SELECT * FROM retired_points WHERE id = ?", (int(point_id),)
                ).fetchone()
                if row is None:
                    refused.append({"id": point_id, "reason": t("Not a retired signal.")})
                    continue
                point = self._loads(row["point"], {}) or {}
                reason = self._restore_conflict(connection, point)
                if reason:
                    refused.append({"id": point_id, "signal": row["signal"], "reason": reason})
                    continue
                columns = [key for key in point if _COLUMN.match(key)]
                connection.execute(
                    f"INSERT INTO points ({', '.join(columns)})"
                    f" VALUES ({', '.join('?' for _ in columns)})",
                    [point[key] for key in columns],
                )
                connection.execute("DELETE FROM retired_points WHERE id = ?", (int(point_id),))
                restored.append(row["signal"])
            if restored:
                self._bump(connection)
        return {"restored": restored, "refused": refused}

    @staticmethod
    def _restore_conflict(connection: Any, point: dict[str, Any]) -> str:
        source = point.get("source_id")
        if not connection.execute("SELECT 1 FROM sources WHERE id = ?", (source,)).fetchone():
            return t("Its source {id} was removed.", id=source)
        taken = connection.execute(
            "SELECT tag FROM points WHERE source_id = ? AND (tag = ? OR address = ?)",
            (source, point.get("tag"), point.get("address")),
        ).fetchone()
        if taken:
            return t("Another signal now has its tag or address ({tag}).", tag=taken["tag"])
        return ""

    def purge_retired(
        self, ids: list[int] | None = None, *, older_than_ms: int | None = None
    ) -> list[int]:
        """Delete retired points for good (the collector then deletes their archive)."""

        clauses, args = [], []
        if ids is not None:
            if not ids:
                return []
            clauses.append(f"id IN ({', '.join('?' for _ in ids)})")
            args += [int(item) for item in ids]
        if older_than_ms is not None:
            clauses.append("retired_ms < ?")
            args.append(int(older_than_ms))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(f"SELECT id FROM retired_points{where}", args).fetchall()
            purged = [int(row["id"]) for row in rows]
            if purged:
                marks = ", ".join("?" for _ in purged)
                connection.execute(f"DELETE FROM retired_points WHERE id IN ({marks})", purged)
                self._bump(connection)
        return purged

    def derived(self, app: str, series: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """The points of an app's derived signals, created or updated as the app describes them.

        The app's source (``app-<app id>``, kind ``derived``) is created on its first write.
        ``series`` items carry ``signal`` (``app-<app>:<name>``) and optionally ``name``,
        ``unit``, ``description``, ``low``, ``high``, ``kind``, ``subject``, ``result``.
        Returns the points by signal id.
        """

        return self._written(derived_source(app), "derived", app, series)

    def lab(self, series: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """The points of laboratory analyses (``laboratory:<analysis>``), as :meth:`derived`."""

        return self._written(LAB_SOURCE, "lab", "Laboratory", series)

    def system(self, series: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """The points of the suite's health signals (``system:<name>``), as :meth:`derived`.

        The source ``system`` ("System", kind ``system``, 90 days) is created on the first
        write; a plant source named ``system`` from before it was reserved is refused (403).
        """

        return self._written(
            SYSTEM_SOURCE, "system", "System", series, retention_days=SYSTEM_RETENTION_DAYS
        )

    def _written(
        self,
        source_id: str,
        kind: str,
        name: str,
        series: list[dict[str, Any]],
        *,
        retention_days: int | None = None,
    ) -> dict[str, dict[str, Any]]:
        now = self._now()
        out: dict[str, dict[str, Any]] = {}
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT kind FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO sources (id, name, kind, endpoint, mode, options, enabled,"
                    " retention_days, created, updated)"
                    " VALUES (?, ?, ?, '', 'archive', '{}', 1, ?, ?, ?)",
                    (source_id, name, kind, retention_days, now, now),
                )
            elif row["kind"] != kind:
                raise CatalogError(
                    t("Source {id} is a plant source, not {app}'s.", id=source_id, app=name), 403
                )
            for item in series:
                _, tag = split_signal(item["signal"])
                fields = {
                    key: item[key]
                    for key in (
                        "name",
                        "unit",
                        "description",
                        "low",
                        "high",
                        "subject",
                        "result",
                        "retention_days",
                        "managed_by",
                        "keep_runs",
                    )
                    if item.get(key) is not None
                }
                connection.execute(
                    """
                    INSERT INTO points (source_id, tag, address, name, description, unit, kind,
                        step, low, high, scan_seconds, deviation, max_seconds, mode, subject,
                        result, enabled, created, updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'archive', ?, ?, 1, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        source_id,
                        tag,
                        tag,
                        str(fields.get("name", "")),
                        str(fields.get("description", "")),
                        str(fields.get("unit", "")),
                        item.get("kind") or "number",
                        int(on_change(item.get("kind") or "number")),
                        fields.get("low"),
                        fields.get("high"),
                        str(fields.get("subject", "")),
                        str(fields.get("result", "")),
                        now,
                        now,
                    ),
                )
                if fields:
                    assignments = ", ".join(f"{key} = ?" for key in fields)
                    connection.execute(
                        f"UPDATE points SET {assignments}, updated = ? "
                        "WHERE source_id = ? AND tag = ?",
                        (*fields.values(), now, source_id, tag),
                    )
            self._bump(connection)
            rows = connection.execute(
                f"{self._POINTS} WHERE p.source_id = ?", (source_id,)
            ).fetchall()
        general = self.settings()
        for row in rows:
            point = _point(row, general)
            out[point["signal"]] = point
        return out

    # Requests to the collector -----------------------------------------------------------

    def add_request(self, kind: str, source_id: str, user: str, detail: Any = None) -> int:
        with self._lock, self._connect() as connection:
            request_id = connection.execute(
                "INSERT INTO requests (kind, source_id, detail, created_ms, created_by) "
                "VALUES (?, ?, ?, ?, ?) RETURNING id",
                (kind, source_id, self._json(detail or {}), int(time.time() * 1000), user),
            ).fetchone()[0]
            # Old requests are dropped (their answers are read within minutes).
            connection.execute(
                "DELETE FROM requests WHERE created_ms < ?", (int(time.time() * 1000) - 86400000,)
            )
            return int(request_id)

    def requests(self, since_ms: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM requests WHERE created_ms >= ? ORDER BY id", (since_ms,)
            ).fetchall()
        return [self._row_with_json(row, {"detail": ("detail", {})}) for row in rows]

    def request(self, request_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM requests WHERE id = ?", (request_id,)
            ).fetchone()
        return self._row_with_json(row, {"detail": ("detail", {})}) if row else None


def _source(row: Any) -> dict[str, Any]:
    item = dict(row)
    item.pop("secret", None)
    item["enabled"] = bool(item["enabled"])
    item["has_password"] = bool(row["secret"]) or bool(item["password_env"])
    try:
        item["options"] = json.loads(item["options"] or "{}")
    except json.JSONDecodeError:
        item["options"] = {}
    try:
        item["owners"] = list(json.loads(item.get("owners") or "[]"))
    except json.JSONDecodeError:
        item["owners"] = []
    item["contact"] = item.get("contact") or ""
    item["heartbeat_seconds"] = int(item.get("heartbeat_seconds") or 0)
    item["default_mode"] = DEFAULT_MODES.get(item["kind"], "archive")
    item["mode"] = item["mode"] or item["default_mode"]
    # Whether the source tells the quality of its values (else every value counts as good).
    item["quality_reported"] = item["kind"] in QUALITY_KINDS
    app = item["id"][4:] if item["kind"] == "derived" and item["id"].startswith("app-") else ""
    # The app that took over a retired app's work (shown on the Sources page), else None.
    item["retired_into"] = RETIRED_APPS.get(app)
    return item


def _point(row: Any, general: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    _resolve_settings(item, general)
    item["enabled"] = bool(item["enabled"])
    item["step"] = bool(item["step"])
    item["source_enabled"] = bool(item.pop("source_enabled", True))
    source_mode = item.pop("source_mode", "") or DEFAULT_MODES.get(item["source_kind"], "archive")
    item["own_mode"] = item["mode"]
    item["mode"] = item["mode"] or source_mode
    if item["source_kind"] in ARCHIVE_ONLY_KINDS:
        item["mode"] = "archive"
    item["signal"] = f"{item['source_id']}:{item['tag']}"
    item["quality_reported"] = item["source_kind"] in QUALITY_KINDS
    return item


def _source_defaults(row: Any, general: dict[str, Any]) -> dict[str, Any]:
    """The general settings with a source's overrides on top."""

    return {key: general[key] if row[key] is None else row[key] for key in SOURCE_SETTINGS}


def _has_span(low: Any, high: Any) -> bool:
    return low is not None and high is not None and high > low


def _deviation(kind: str, low: Any, high: Any, percent: float) -> float:
    """The deviation a share of the span gives; 0 for text or no known span (a number point
    then takes the share of its value, ``_value_percent``)."""

    if kind != "number" or not _has_span(low, high):
        return 0.0
    return (float(high) - float(low)) * float(percent) / 100.0


def _value_percent(item: dict[str, Any], percent: float) -> float | None:
    """The share of the value a point without a known range is compressed to, else None."""

    if item["kind"] != "number" or item.get("step") or _has_span(item.get("low"), item.get("high")):
        return None
    return float(percent) if percent > 0 else None


def _resolve_settings(item: dict[str, Any], general: dict[str, Any]) -> None:
    """Put the effective settings on a point row, with where each comes from.

    ``own`` keeps the point's own values (None where it inherits), ``origins`` says
    ``point``, ``source`` or ``general`` for each, and the setting fields hold the values
    in effect. The source's overrides arrive as ``source_<setting>`` columns.
    """

    source = {key: item.pop(f"source_{key}", None) for key in SOURCE_SETTINGS}
    # Points added before ranges had an origin (D2): a range they have came with them.
    item["range_origin"] = item.get("range_origin") or (
        "source" if _has_span(item.get("low"), item.get("high")) else ""
    )
    inherited = {key for key in (item.pop("inherits", "") or "").split(",") if key}
    own: dict[str, Any] = {}
    origins: dict[str, str] = {}
    item["deviation_percent"] = None
    for key, fallback in POINT_SETTINGS.items():
        value = item.get(key)
        if key == "retention_days" and value is not None:
            own[key], origins[key] = int(value), "point"
            continue
        if key != "retention_days" and key not in inherited:
            own[key], origins[key] = value, "point"
            continue
        own[key] = None
        if source.get(fallback) is not None:
            setting, origins[key] = source[fallback], "source"
        else:
            setting, origins[key] = general[fallback], "general"
        if key == "deviation":
            item[key] = _deviation(item["kind"], item.get("low"), item.get("high"), setting)
            item["deviation_percent"] = _value_percent(item, float(setting))
        elif key == "retention_days":
            item[key] = int(setting)
        else:
            item[key] = float(setting)
    _apply_profile(item, general, own, origins)
    item["own"] = own
    item["origins"] = origins


def _apply_profile(
    item: dict[str, Any], general: dict[str, Any], own: dict[str, Any], origins: dict[str, str]
) -> None:
    """The compression profile on top of the settings in effect (D1): ``fine`` and ``none`` set
    the deviation; the exception is the point's own, else its profile's, else the general one.
    ``exception_percent`` is set, like ``deviation_percent``, when no range is known."""

    profile = item.get("profile") or ""
    item["profile"] = profile
    exception_percent = float(general["default_exception_percent"])
    if profile in PROFILES:
        exception_percent, deviation_percent = PROFILES[profile]
        item["deviation"] = _deviation(
            item["kind"], item.get("low"), item.get("high"), deviation_percent
        )
        item["deviation_percent"] = _value_percent(item, deviation_percent)
        origins["deviation"] = "profile"
    own_exception = item.get("exception")
    own["exception"] = None if own_exception is None else float(own_exception)
    if own_exception is not None:
        item["exception"], item["exception_percent"] = float(own_exception), None
        origins["exception"] = "point"
    else:
        item["exception"] = _deviation(
            item["kind"], item.get("low"), item.get("high"), exception_percent
        )
        item["exception_percent"] = _value_percent(item, exception_percent)
        origins["exception"] = "profile" if profile in PROFILES else "general"


def _not_an_input(
    name: str, point: dict[str, Any] | None, calculated: bool, signal: str
) -> str | None:
    """Why a formula cannot read ``name`` (None: it can)."""

    if name == signal:
        return t("A formula cannot read its own signal.")
    if calculated:
        return None
    if point is None or point["signal"] != name:
        return t("{signal} is not a signal of the Historian.", signal=name)
    if point["kind"] != "number":
        return t("{signal} is text: a formula reads numbers.", signal=name)
    if point["source_kind"] not in LIVE_KINDS or point["mode"] not in COLLECTED:
        return t(
            "{signal} is not archived here: a formula reads signals the collector archives"
            " (OPC UA in mode archive or both, or other calculated points).",
            signal=name,
        )
    return None


def _reads(formula: str) -> list[str]:
    try:
        return parse(formula).signals
    except FormulaError:
        return []


def _loops(graph: dict[str, list[str]], start: str) -> bool:
    """True when following what ``start``'s formula reads comes back to ``start``."""

    seen: set[str] = set()
    todo = list(graph.get(start, []))
    while todo:
        name = todo.pop()
        if name == start:
            return True
        if name not in seen:
            seen.add(name)
            todo.extend(graph.get(name, []))
    return False


def _with_defaults(item: PointIn, defaults: dict[str, Any]) -> dict[str, float]:
    """The values stored for a new point: its own, else its source's or the general defaults
    (kept as the fallback of the NOT NULL columns; reads resolve them again)."""

    if item.deviation is not None:
        deviation = item.deviation
    else:
        # No span known: archive every change; set a deviation once the range is known.
        deviation = _deviation(
            item.kind, item.low, item.high, float(defaults["default_deviation_percent"])
        )
    return {
        "scan_seconds": item.scan_seconds or float(defaults["default_scan_seconds"]),
        "deviation": deviation,
        "max_seconds": item.max_seconds or float(defaults["default_max_seconds"]),
    }
