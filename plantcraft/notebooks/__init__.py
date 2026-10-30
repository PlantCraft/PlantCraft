"""Notebooks: Python in the browser, with the plant's data a call away (docs/en/notebooks.md).

PlantCraft serves JupyterLite (Jupyter running in the browser on Pyodide, built into the image,
nothing downloaded at run time) at ``/notebooks/lite/``. The code runs on the person's own
computer, inside the browser, as that person: it reads the plant through API v1 with their own
access, so a notebook never sees more than its owner may.

This store keeps the switch (off by default, ``PLANTCRAFT_NOTEBOOKS=off`` keeps it off for good)
and the notebooks PlantCraft wrote for each person ("Open in a notebook" from a signal, an
export or an asset). Those appear in the person's ``My notebooks`` folder; what the person edits is
kept by their browser, and File › Download saves an ``.ipynb``. The same notebooks run on the
person's own computer with the Notebooks kit (``notebooks.kits``), whose download is a second
switch.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft.config import env_flag
from plantcraft.db import Database, Migration, Store, add_columns

# Notebooks PlantCraft keeps for one person; the oldest go first past it.
MAX_PER_PERSON = 200
# How long the code of "Connect this computer" may be traded for a token.
PAIR_SECONDS = 120
# The folders of JupyterLite's file browser: the examples, read from here,
# and the person's notebooks. ``PlantCraft`` was the person's folder until then: notebooks opened
# from it before still open.
FOLDER = "My notebooks"
EXAMPLES_FOLDER = "Examples"
OLD_FOLDER = "PlantCraft"


def notebooks_allowed() -> bool:
    """False when the installation turned notebooks off for good."""

    return env_flag("PLANTCRAFT_NOTEBOOKS", True)


def file_name(title: str) -> str:
    """A safe ``.ipynb`` name from a title: letters, digits, spaces, dots, dashes."""

    cleaned = re.sub(r"[^\w .-]+", " ", title, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")[:80] or "Notebook"
    return f"{cleaned}.ipynb"


def _pair_digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _drop_example_copies(connection: Any) -> None:
    """PlantCraft keeps no edits (they stay in the person's browser), so every stored copy of an
    example is the example as it was written: the Examples folder has it already."""

    from plantcraft.notebooks.templates import OLD_EXAMPLE_TITLES

    names = {file_name(f"Example - {title}")[: -len(".ipynb")] for title in OLD_EXAMPLE_TITLES}
    rows = connection.execute("SELECT notebook_id, name FROM notebooks").fetchall()
    for notebook_id, name in rows:
        if re.sub(r" \d+$", "", str(name)[: -len(".ipynb")]) in names:
            connection.execute("DELETE FROM notebooks WHERE notebook_id = ?", (notebook_id,))


class NotebookStore(Store):
    """The switch (one row) and each person's notebooks written by PlantCraft."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS notebook_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        enabled INTEGER NOT NULL DEFAULT 0,
        updated_by TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS notebooks (
        notebook_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        name TEXT NOT NULL,
        content_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (username, name)
    );

    CREATE INDEX IF NOT EXISTS idx_notebooks_user ON notebooks(username, created_at);

    -- "Connect this computer": a code the person's computer trades, once and
    -- within PAIR_SECONDS, for the kit's token. Only its digest is kept.
    CREATE TABLE IF NOT EXISTS notebook_pairings (
        code_digest TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    """

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "notebook_settings",
                {
                    # Notebooks kits (2026-10-25): their download, off until an administrator turns it on.
                    "kit_enabled": "INTEGER NOT NULL DEFAULT 0",
                },
            ),
        ),
        # One switch (D3): with Notebooks on, the kit is offered whenever the
        # installation has one; an administrator may still take it away in Setup › Notebooks.
        Migration("kit-with-notebooks-2026-10-26", "UPDATE notebook_settings SET kit_enabled = 1"),
        # The example cards of before 2026-10-25 wrote a copy into My notebooks at each click
        # ("Example - Read a signal and plot it 2", "... 3"), beside the Examples folder.
        Migration("example-copies-2026-10-26", lambda connection: _drop_example_copies(connection)),
    )

    def __init__(self, db: Database):
        super().__init__(db)

    # Settings -------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM notebook_settings WHERE id = 1").fetchone()
        allowed = notebooks_allowed()
        stored = dict(row) if row else {"enabled": 0, "kit_enabled": 1}
        return {
            "allowed": allowed,
            "enabled": allowed and bool(stored["enabled"]),
            "kit_enabled": bool(stored.get("kit_enabled")),
            "updated_by": stored.get("updated_by"),
            "updated_at": stored.get("updated_at"),
        }

    def save_settings(
        self, *, actor: str, enabled: bool | None = None, kit_enabled: bool | None = None
    ) -> dict[str, Any]:
        """Changes what is given (the switch, the kits' download) and keeps the rest."""

        current = self.settings()
        enabled = current["enabled"] if enabled is None else enabled
        kit_enabled = current["kit_enabled"] if kit_enabled is None else kit_enabled
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO notebook_settings (id, enabled, kit_enabled, updated_by, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled,
                    kit_enabled = excluded.kit_enabled,
                    updated_by = excluded.updated_by, updated_at = excluded.updated_at
                """,
                (int(bool(enabled)), int(bool(kit_enabled)), actor, self._now()),
            )
        return self.settings()

    def enabled(self) -> bool:
        return self.settings()["enabled"]

    # Connecting a computer -------------------------------------------------------------

    def pairing_code(self, username: str) -> tuple[str, str]:
        """A new one-time code for ``username``'s computer and when it ends."""

        code = secrets.token_urlsafe(24)
        now = datetime.now(UTC)
        expires = (now + timedelta(seconds=PAIR_SECONDS)).isoformat(timespec="seconds")
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM notebook_pairings WHERE expires_at < ?",
                (now.isoformat(timespec="seconds"),),
            )
            connection.execute(
                "INSERT INTO notebook_pairings (code_digest, username, expires_at) VALUES (?, ?, ?)",
                (_pair_digest(code), username, expires),
            )
        return code, expires

    def redeem(self, code: str) -> str | None:
        """The person a code was given to, once, while it lasts; None otherwise."""

        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._write() as connection:
            row = connection.execute(
                "DELETE FROM notebook_pairings WHERE code_digest = ? RETURNING username, expires_at",
                (_pair_digest(code),),
            ).fetchone()
        if row is None or str(row["expires_at"]) < now:
            return None
        return str(row["username"])

    # Notebooks ------------------------------------------------------------------------

    @staticmethod
    def _public(row: Any, *, content: bool = False) -> dict[str, Any]:
        item = dict(row)
        text = item.pop("content_json")
        item["path"] = f"{FOLDER}/{item['name']}"
        item["size"] = len(text.encode("utf-8"))
        if content:
            item["content"] = json.loads(text)
        return item

    def create(self, username: str, title: str, notebook: dict[str, Any]) -> dict[str, Any]:
        """Keep ``notebook`` for ``username`` under a name from ``title`` (``... 2`` if taken)."""

        base = file_name(title)[: -len(".ipynb")]
        text = json.dumps(notebook, ensure_ascii=False)
        notebook_id = secrets.token_hex(6)
        with self._lock, self._write() as connection:
            taken = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM notebooks WHERE username = ?", (username,)
                )
            }
            name, number = f"{base}.ipynb", 1
            while name in taken:
                number += 1
                name = f"{base} {number}.ipynb"
            connection.execute(
                """
                INSERT INTO notebooks (notebook_id, username, name, content_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (notebook_id, username, name, text, self._now()),
            )
            connection.execute(
                """
                DELETE FROM notebooks WHERE username = ? AND notebook_id NOT IN (
                    SELECT notebook_id FROM notebooks WHERE username = ?
                    ORDER BY created_at DESC, rowid DESC LIMIT ?)
                """,
                (username, username, MAX_PER_PERSON),
            )
        return self.get(username, name) or {}

    def get(self, username: str, name: str, *, content: bool = False) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM notebooks WHERE username = ? AND name = ?", (username, name)
            ).fetchone()
        return self._public(row, content=content) if row else None

    def list(self, username: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notebooks WHERE username = ? ORDER BY created_at DESC, rowid DESC",
                (username,),
            ).fetchall()
        return [self._public(row) for row in rows]

    def delete(self, username: str, notebook_id: str) -> bool:
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "DELETE FROM notebooks WHERE username = ? AND notebook_id = ?",
                (username, notebook_id),
            )
        return cursor.rowcount > 0
