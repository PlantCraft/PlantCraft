"""Projects: a project is a set of Modelica files (``.mo``), edited in the browser.

A project organises one piece of work: its models, and the studies and simulations made with
them. **Block libraries** are kept in the same tables (``kind = 'library'``) but belong to no
project: their classes are the blocks every project may use, sorted into groups (equipment,
control...). Their files travel with every job beside the project's own.

The store owns three tables: ``projects``, their ``project_files`` and every saved version of
a file (``file_revisions``, the last ``KEEP_REVISIONS`` per file). A save names the version it
started from (``base_updated_at``), so two people editing the same file never overwrite each
other silently: the second save is a conflict the person resolves. A save may name the version
it makes and say what changed (``version_name``, ``version_note``, as Link's algorithms); the
name travels with the text into ``file_revisions`` when a later save replaces it.
"""

from __future__ import annotations

import uuid
from typing import Any

from plantcraft_sdk.server.store import Migration, Store, add_columns

from modelcraft.i18n import t
from modelcraft.projects.models import (
    KEEP_REVISIONS,
    KINDS,
    MAX_DESCRIPTION,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_GROUP,
    MAX_PROJECT_BYTES,
    MAX_VERSION_NAME,
    MAX_VERSION_NOTE,
    SYSTEM,
    Conflict,
    ProjectError,
    ReadOnly,
    check_name,
    check_path,
)


class ProjectStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        example INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS project_files (
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        content TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (project_id, path)
    );
    CREATE TABLE IF NOT EXISTS file_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        content TEXT NOT NULL,
        saved_by TEXT NOT NULL DEFAULT '',
        saved_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS file_revisions_file ON file_revisions (project_id, path, id);
    """
    # Columns added after the first release: (name, declaration), one migration step.
    ADDED = (
        ("kind", "TEXT NOT NULL DEFAULT 'project'"),
        ("block_group", "TEXT NOT NULL DEFAULT ''"),
    )
    # A version's name and what changed in it (round 9 M4 leftover).
    VERSION_COLUMNS = {
        "version_name": "TEXT NOT NULL DEFAULT ''",
        "version_note": "TEXT NOT NULL DEFAULT ''",
    }
    MIGRATIONS = (
        Migration("columns-before-0.5", add_columns("projects", dict(ADDED))),
        Migration("version-names-files", add_columns("project_files", VERSION_COLUMNS)),
        Migration("version-names-revisions", add_columns("file_revisions", VERSION_COLUMNS)),
    )

    # Projects --------------------------------------------------------------------------

    def list(self, kind: str = "project") -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.*, COUNT(f.path) AS files, COALESCE(SUM(LENGTH(f.content)), 0) AS bytes
                FROM projects p LEFT JOIN project_files f ON f.project_id = p.id
                WHERE p.kind = ?
                GROUP BY p.id ORDER BY p.example DESC, LOWER(p.name)
                """,
                (kind,),
            ).fetchall()
        return [self._project(row) for row in rows]

    def library_files(self) -> dict[str, str]:
        """Every block library's files (the first library to claim a package name wins)."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT p.id, f.path, f.content FROM project_files f "
                "JOIN projects p ON p.id = f.project_id "
                "WHERE p.kind = 'library' ORDER BY p.created_at, p.id, f.path"
            ).fetchall()
        owner: dict[str, str] = {}
        found: dict[str, str] = {}
        for row in rows:
            top = row["path"].split("/")[0].removesuffix(".mo")
            if owner.setdefault(top, row["id"]) == row["id"]:
                found[row["path"]] = row["content"]
        return found

    @staticmethod
    def _project(row) -> dict[str, Any]:
        item = dict(row)
        item["example"] = bool(item.get("example"))
        return item

    def get(self, project_id: str) -> dict[str, Any] | None:
        if not project_id or len(project_id) > 64:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                return None
            files = connection.execute(
                "SELECT path, LENGTH(content) AS bytes, updated_by, updated_at FROM project_files "
                "WHERE project_id = ? ORDER BY path",
                (project_id,),
            ).fetchall()
        return {**self._project(row), "files": [dict(f) for f in files]}

    def create(
        self,
        name: str,
        *,
        by: str,
        description: str = "",
        files: dict[str, str] | None = None,
        example: bool = False,
        kind: str = "project",
        group: str = "",
    ) -> dict[str, Any]:
        name = check_name(name)
        if kind not in KINDS:
            raise ProjectError(t("Unknown kind: {kind}", kind=kind))
        files = {check_path(path): text for path, text in (files or {}).items()}
        self._check_sizes(files)
        project_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO projects (id, name, description, example, created_by, created_at, "
                "updated_by, updated_at, kind, block_group) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    name,
                    (description or "")[:MAX_DESCRIPTION],
                    int(example),
                    by,
                    now,
                    by,
                    now,
                    kind,
                    " ".join(group.split())[:MAX_GROUP],
                ),
            )
            for path, text in files.items():
                connection.execute(
                    "INSERT INTO project_files (project_id, path, content, updated_by, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (project_id, path, text, by, now),
                )
        return self.get(project_id)  # type: ignore[return-value]

    def update(
        self,
        project_id: str,
        *,
        by: str,
        name: str | None = None,
        description: str | None = None,
        group: str | None = None,
    ) -> dict[str, Any]:
        project = self._writable(project_id, by)
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE projects SET name = ?, description = ?, block_group = ?, updated_by = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    check_name(name) if name is not None else project["name"],
                    (description if description is not None else project["description"])[
                        :MAX_DESCRIPTION
                    ],
                    " ".join(group.split())[:MAX_GROUP]
                    if group is not None
                    else project.get("block_group", ""),
                    by,
                    self._now(),
                    project_id,
                ),
            )
        return self.get(project_id)  # type: ignore[return-value]

    def delete(self, project_id: str, *, by: str = "") -> None:
        self._writable(project_id, by)
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def duplicate(self, project_id: str, name: str, *, by: str) -> dict[str, Any]:
        project = self._existing(project_id)
        return self.create(
            name,
            by=by,
            description=project["description"],
            files=self.files(project_id),
            kind=project.get("kind", "project"),
            group=project.get("block_group", ""),
        )

    def _existing(self, project_id: str) -> dict[str, Any]:
        project = self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        return project

    def _writable(self, project_id: str, by: str) -> dict[str, Any]:
        project = self._existing(project_id)
        if project["example"] and by != SYSTEM:
            what = "block library" if project.get("kind") == "library" else "example"
            raise ReadOnly(
                t(
                    "{name} is an {what} Models keeps as it ships it: duplicate it to change it.",
                    name=project["name"],
                    what=what,
                )
            )
        return project

    def examples(self, kind: str = "project") -> list[dict[str, Any]]:
        return [p for p in self.list(kind) if p["example"]]

    def replace_files(self, project_id: str, files: dict[str, str], *, by: str = SYSTEM) -> bool:
        """Make the project's files exactly ``files`` (an example brought to the version Models
        ships). True when anything changed."""

        self._writable(project_id, by)
        files = {check_path(path): text for path, text in files.items()}
        self._check_sizes(files)
        if self.files(project_id) == files:
            return False
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM project_files WHERE project_id = ?", (project_id,))
            for path, text in files.items():
                connection.execute(
                    "INSERT INTO project_files (project_id, path, content, updated_by, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (project_id, path, text, by, now),
                )
            connection.execute(
                "UPDATE projects SET updated_by = ?, updated_at = ? WHERE id = ?",
                (by, now, project_id),
            )
        return True

    # Files ---------------------------------------------------------------------------------

    def files(self, project_id: str) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT path, content FROM project_files WHERE project_id = ? ORDER BY path",
                (project_id,),
            ).fetchall()
        return {row["path"]: row["content"] for row in rows}

    def file(self, project_id: str, path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path, content, updated_by, updated_at, version_name, version_note "
                "FROM project_files WHERE project_id = ? AND path = ?",
                (project_id, path),
            ).fetchone()
        return dict(row) if row else None

    def _check_sizes(self, files: dict[str, str]) -> None:
        if len(files) > MAX_FILES:
            raise ProjectError(t("A project holds up to {n} files.", n=MAX_FILES))
        for path, text in files.items():
            if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FILE_BYTES:
                raise ProjectError(t("{path} is larger than 1 MB.", path=path))
            if "\x00" in text:
                raise ProjectError(t("{path} is not a text file.", path=path))
        if sum(len(text.encode("utf-8")) for text in files.values()) > MAX_PROJECT_BYTES:
            raise ProjectError(t("A project holds up to 8 MB of Modelica text."))

    def save_file(
        self,
        project_id: str,
        path: str,
        content: str,
        *,
        by: str,
        base_updated_at: str | None = None,
        create: bool = False,
        version_name: str = "",
        version_note: str = "",
    ) -> dict[str, Any]:
        """Write a file. ``base_updated_at`` is the version the person edited (None: a new file);
        ``version_name`` and ``version_note`` name the version the save makes."""

        self._writable(project_id, by)
        path = check_path(path)
        named = (
            " ".join(version_name.split())[:MAX_VERSION_NAME],
            version_note.strip()[:MAX_VERSION_NOTE],
        )
        files = self.files(project_id)
        files[path] = content
        self._check_sizes(files)
        now = self._now()
        with self._lock, self._connect() as connection:
            current = connection.execute(
                "SELECT content, updated_at, version_name, version_note FROM project_files "
                "WHERE project_id = ? AND path = ?",
                (project_id, path),
            ).fetchone()
            if current is None:
                if not create and base_updated_at:
                    raise Conflict(
                        t("{path} was deleted or renamed since you opened it.", path=path)
                    )
                connection.execute(
                    "INSERT INTO project_files (project_id, path, content, updated_by, updated_at, "
                    "version_name, version_note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (project_id, path, content, by, now, *named),
                )
            else:
                if create:
                    raise ProjectError(t("{path} already exists.", path=path))
                if base_updated_at is not None and base_updated_at != current["updated_at"]:
                    raise Conflict(
                        t("{path} was changed by someone else since you opened it.", path=path)
                    )
                if current["content"] != content:
                    connection.execute(
                        "INSERT INTO file_revisions (project_id, path, content, saved_by, saved_at, "
                        "version_name, version_note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            project_id,
                            path,
                            current["content"],
                            by,
                            now,
                            current["version_name"],
                            current["version_note"],
                        ),
                    )
                    connection.execute(
                        "DELETE FROM file_revisions WHERE project_id = ? AND path = ? AND id NOT IN "
                        "(SELECT id FROM file_revisions WHERE project_id = ? AND path = ? "
                        "ORDER BY id DESC LIMIT ?)",
                        (project_id, path, project_id, path, KEEP_REVISIONS),
                    )
                # The name stays with the text: a save that changes nothing keeps it, unless
                # it names the version anew.
                if current["content"] != content or any(named):
                    named_now = named
                else:
                    named_now = (current["version_name"], current["version_note"])
                connection.execute(
                    "UPDATE project_files SET content = ?, updated_by = ?, updated_at = ?, "
                    "version_name = ?, version_note = ? WHERE project_id = ? AND path = ?",
                    (content, by, now, *named_now, project_id, path),
                )
            connection.execute(
                "UPDATE projects SET updated_by = ?, updated_at = ? WHERE id = ?",
                (by, now, project_id),
            )
        return self.file(project_id, path)  # type: ignore[return-value]

    def rename_file(self, project_id: str, path: str, new_path: str, *, by: str) -> dict[str, Any]:
        self._writable(project_id, by)
        new_path = check_path(new_path)
        with self._lock, self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM project_files WHERE project_id = ? AND path = ?",
                (project_id, new_path),
            ).fetchone():
                raise ProjectError(t("{path} already exists.", path=new_path))
            changed = connection.execute(
                "UPDATE project_files SET path = ?, updated_by = ?, updated_at = ? WHERE project_id = ? AND path = ?",
                (new_path, by, self._now(), project_id, path),
            ).rowcount
            if not changed:
                raise KeyError(path)
            connection.execute(
                "UPDATE file_revisions SET path = ? WHERE project_id = ? AND path = ?",
                (new_path, project_id, path),
            )
        return self.file(project_id, new_path)  # type: ignore[return-value]

    def delete_file(self, project_id: str, path: str, *, by: str) -> None:
        self._writable(project_id, by)
        with self._lock, self._connect() as connection:
            current = connection.execute(
                "SELECT content, version_name, version_note FROM project_files "
                "WHERE project_id = ? AND path = ?",
                (project_id, path),
            ).fetchone()
            if current is None:
                raise KeyError(path)
            connection.execute(
                "INSERT INTO file_revisions (project_id, path, content, saved_by, saved_at, "
                "version_name, version_note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    path,
                    current["content"],
                    by,
                    self._now(),
                    current["version_name"],
                    current["version_note"],
                ),
            )
            connection.execute(
                "DELETE FROM project_files WHERE project_id = ? AND path = ?", (project_id, path)
            )
            connection.execute(
                "UPDATE projects SET updated_by = ?, updated_at = ? WHERE id = ?",
                (by, self._now(), project_id),
            )

    def revisions(
        self, project_id: str, path: str, *, limit: int = KEEP_REVISIONS
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, path, saved_by, saved_at, LENGTH(content) AS bytes, version_name, "
                "version_note FROM file_revisions WHERE project_id = ? AND path = ? "
                "ORDER BY id DESC LIMIT ?",
                (project_id, path, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def revision(self, project_id: str, revision_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, path, content, saved_by, saved_at, version_name, version_note "
                "FROM file_revisions WHERE project_id = ? AND id = ?",
                (project_id, revision_id),
            ).fetchone()
        return dict(row) if row else None
