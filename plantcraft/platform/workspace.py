"""Every store of PlantCraft, sharing a single database.

Apps of the suite keep their own databases; nothing here knows any of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plantcraft.actions import ActionStore
from plantcraft.assets import AssetStore
from plantcraft.assets.imports import AssetImportStore
from plantcraft.assistant_access import AssistantAccessStore
from plantcraft.audit import AuditStore
from plantcraft.auth.app_keys import AppKeyStore
from plantcraft.auth.demo_visits import DemoVisits
from plantcraft.auth.throttle import LoginThrottle
from plantcraft.auth.usage import UsageStore
from plantcraft.auth.users import UserStore
from plantcraft.db import Database, Store, normalize_times
from plantcraft.events import EventStore
from plantcraft.groups import GroupStore
from plantcraft.installation import InstallationStore
from plantcraft.knowledge import KnowledgeStore
from plantcraft.messages import ConversationStore
from plantcraft.notebooks import NotebookStore
from plantcraft.preferences import PreferenceStore
from plantcraft.results import ResultStore

UTC_TIMES = "utc-times-2026-10-23"


class Workspace(Store):
    """The stores of one installation, and the one-time data migrations already done."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS workspace_migrations (
        name TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}'
    );
    """

    def __init__(self, path: str | Path | Database):
        db = path if isinstance(path, Database) else Database(path)
        super().__init__(db)
        self.users = UserStore(db)
        self.assets = AssetStore(db)
        self.asset_imports = AssetImportStore(db)
        self.events = EventStore(db)
        self.audit = AuditStore(db)
        self.app_keys = AppKeyStore(db)
        self.assistant_access = AssistantAccessStore(db)
        self.login_throttle = LoginThrottle(db)
        self.usage = UsageStore(db)
        self.demo_visits = DemoVisits(db)
        self.results = ResultStore(db)
        self.knowledge = KnowledgeStore(db)
        self.messages = ConversationStore(db, self.users)
        self.actions = ActionStore(db)
        self.preferences = PreferenceStore(db)
        self.installation = InstallationStore(db)
        self.notebooks = NotebookStore(db)
        self.groups = GroupStore(db, self.users)
        # A group's conversation follows its members (messages <-> groups, owner 2026-10-23).
        self.messages.groups = self.groups
        # Every stored time in UTC (owner, 2026-10-23): rows from before are rewritten once.
        if not self.migrated(UTC_TIMES):
            self.record_migration(UTC_TIMES, {"rewritten": normalize_times(db)})

    def counts(self) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            users = connection.execute(
                "SELECT COUNT(*) FROM workspace_users WHERE active = 1"
            ).fetchone()[0]
            assets = connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        return {"users": int(users), "assets": int(assets)}

    def migrated(self, name: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM workspace_migrations WHERE name = ?", (name,)
            ).fetchone()
        return row is not None

    def record_migration(self, name: str, detail: dict[str, Any]) -> None:
        """A one-time migration ran (it does not run again)."""

        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO workspace_migrations (name, applied_at, detail_json) "
                "VALUES (?, ?, ?)",
                (name, self._now(), self._json(detail)),
            )
