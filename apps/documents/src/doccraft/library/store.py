"""Folders, documents, revisions and passages in the app's own SQLite database.

| Table | Holds |
|---|---|
| ``folders`` | a folder of documents, who sees and who changes it (``user:<name>``, ``group:<id>``; empty: everyone, as View's folders) and whether the assistant may read it; documents outside every folder (``folder_id`` ``""``) are in General, everyone's |
| ``documents`` | a document: its number, title, description, kind, unit, language and folder; its revisions hold the files |
| ``revisions`` | one file of a document (``Rev. C``): its SHA-256 in ``files/``, format, pages and where its reading stands (queued, indexed, failed, superseded) |
| ``document_assets`` | the assets a document is about: given by a person, or suggested from the tags found in it and then confirmed |
| ``passages`` | the passages of each indexed revision: text, pages, headings, the assets of the tags in it, its vector |
| ``passages_fts`` | the FTS5 index of the passages (BM25), with diacritics folded so "válvula" finds "valvula" |

The original files are kept apart, under ``files/`` of the data folder, named by their SHA-256;
the database holds only text, metadata and vectors (about a tenth of the files' size).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from plantcraft_sdk.server.store import Migration, Store, add_columns

from doccraft.library.passages import Passage

DOC_ID = re.compile(r"^[a-f0-9]{12}$")
STATUSES = ("queued", "indexing", "indexed", "failed", "superseded")


class DocumentStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS folders (
        folder_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        viewers TEXT NOT NULL DEFAULT '[]',
        editors TEXT NOT NULL DEFAULT '[]',
        assistant INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS documents (
        doc_id TEXT PRIMARY KEY,
        folder_id TEXT NOT NULL DEFAULT '',
        number TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'Other',
        unit TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT '',
        assistant INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS documents_folder ON documents (folder_id);
    CREATE INDEX IF NOT EXISTS documents_number ON documents (number);
    CREATE TABLE IF NOT EXISTS revisions (
        rev_id TEXT PRIMARY KEY,
        doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
        revision TEXT NOT NULL DEFAULT '',
        issued TEXT NOT NULL DEFAULT '',
        filename TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size INTEGER NOT NULL,
        format TEXT NOT NULL DEFAULT '',
        pages INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued',
        error TEXT NOT NULL DEFAULT '',
        embedder TEXT NOT NULL DEFAULT '',
        uploaded_at TEXT NOT NULL,
        uploaded_by TEXT NOT NULL,
        indexed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS revisions_doc ON revisions (doc_id, uploaded_at);
    CREATE INDEX IF NOT EXISTS revisions_status ON revisions (status);
    CREATE TABLE IF NOT EXISTS document_assets (
        doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
        asset_id TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'manual',
        mentions INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (doc_id, asset_id)
    );
    CREATE INDEX IF NOT EXISTS document_assets_asset ON document_assets (asset_id);
    CREATE TABLE IF NOT EXISTS passages (
        passage_id INTEGER PRIMARY KEY AUTOINCREMENT,
        rev_id TEXT NOT NULL REFERENCES revisions(rev_id) ON DELETE CASCADE,
        doc_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        text TEXT NOT NULL,
        page_from INTEGER,
        page_to INTEGER,
        section TEXT NOT NULL DEFAULT '',
        assets TEXT NOT NULL DEFAULT '[]',
        vector BLOB
    );
    CREATE INDEX IF NOT EXISTS passages_rev ON passages (rev_id, seq);
    CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
        text, section, title,
        tokenize = 'unicode61 remove_diacritics 2'
    );
    """
    # Columns added after the first release (never in ``SCHEMA``): the final round, 2026-10-27,
    # gives a document a description of its own, beside its title.
    MIGRATIONS = (
        Migration(
            "2026-10-27-description",
            add_columns("documents", {"description": "TEXT NOT NULL DEFAULT ''"}),
        ),
    )

    def __init__(self, db: Any, files: Path):
        super().__init__(db)
        self.files = files
        self.files.mkdir(parents=True, exist_ok=True)
        self.version = 0  # bumped on every change of the passages (the vector cache follows it)

    # Folders

    def folders(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT f.*, (SELECT COUNT(*) FROM documents d WHERE d.folder_id = f.folder_id) "
                "AS documents FROM folders f ORDER BY f.name"
            ).fetchall()
        return [self._folder(row) for row in rows]

    def folder(self, folder_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT f.*, (SELECT COUNT(*) FROM documents d WHERE d.folder_id = f.folder_id) "
                "AS documents FROM folders f WHERE folder_id = ?",
                (folder_id,),
            ).fetchone()
        return self._folder(row) if row else None

    def save_folder(self, folder_id: str | None, fields: dict[str, Any], by: str) -> dict[str, Any]:
        folder_id = folder_id or uuid.uuid4().hex[:12]
        with self._lock, self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM folders WHERE folder_id = ?", (folder_id,)
            ).fetchone()
            values = (
                fields["name"],
                fields.get("description", ""),
                self._json(fields.get("viewers", [])),
                self._json(fields.get("editors", [])),
                1 if fields.get("assistant", True) else 0,
            )
            if exists:
                connection.execute(
                    "UPDATE folders SET name = ?, description = ?, viewers = ?, editors = ?, "
                    "assistant = ? WHERE folder_id = ?",
                    (*values, folder_id),
                )
            else:
                connection.execute(
                    "INSERT INTO folders (name, description, viewers, editors, assistant, "
                    "folder_id, created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (*values, folder_id, self._now(), by),
                )
        self.version += 1
        return self.folder(folder_id) or {}

    def delete_folder(self, folder_id: str) -> bool:
        with self._lock, self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM documents WHERE folder_id = ?", (folder_id,)
            ).fetchone():
                return False
            return (
                connection.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,)).rowcount
                > 0
            )

    def _folder(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["viewers"] = self._loads(item["viewers"], [])
        item["editors"] = self._loads(item["editors"], [])
        item["assistant"] = bool(item["assistant"])
        return item

    # Documents and revisions

    DOC_COLUMNS = (
        "folder_id",
        "number",
        "title",
        "description",
        "kind",
        "unit",
        "language",
        "assistant",
    )

    def documents(
        self,
        folders: set[str] | None = None,
        asset_ids: list[str] | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT d.*, r.rev_id, r.revision, r.issued, r.filename, r.format, r.pages, r.size, "
            "r.status, r.error, r.uploaded_at, r.uploaded_by FROM documents d "
            "LEFT JOIN revisions r ON r.rev_id = (SELECT rev_id FROM revisions "
            "WHERE doc_id = d.doc_id AND status != 'superseded' ORDER BY uploaded_at DESC LIMIT 1)"
        )
        where, params = [], []
        if folders is not None:
            where.append(f"d.folder_id IN ({','.join('?' * len(folders)) or 'NULL'})")
            params.extend(sorted(folders))
        if asset_ids:
            where.append(
                "d.doc_id IN (SELECT doc_id FROM document_assets WHERE source != 'suggested' "
                f"AND asset_id IN ({','.join('?' * len(asset_ids))}))"
            )
            params.extend(asset_ids)
        if kind:
            where.append("d.kind = ?")
            params.append(kind)
        if where:
            query += " WHERE " + " AND ".join(where)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query + " ORDER BY d.updated_at DESC", params).fetchall()
            assets = self._assets(connection, [row["doc_id"] for row in rows])
        return [self._document(row, assets) for row in rows]

    def document(self, doc_id: str) -> dict[str, Any] | None:
        if not DOC_ID.match(doc_id):
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()
            if not row:
                return None
            revisions = connection.execute(
                "SELECT * FROM revisions WHERE doc_id = ? ORDER BY uploaded_at DESC", (doc_id,)
            ).fetchall()
            assets = self._assets(connection, [doc_id])
        item = self._document(row, assets)
        item["revisions"] = [dict(rev) for rev in revisions]
        current = next((rev for rev in item["revisions"] if rev["status"] != "superseded"), None)
        item["current"] = current
        return item

    def by_number(self, number: str) -> dict[str, Any] | None:
        if not number:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT doc_id FROM documents WHERE number = ? ORDER BY created_at LIMIT 1",
                (number,),
            ).fetchone()
        return self.document(row["doc_id"]) if row else None

    def create(self, fields: dict[str, Any], by: str) -> dict[str, Any]:
        doc_id, now = uuid.uuid4().hex[:12], self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO documents (doc_id, folder_id, number, title, description, kind, unit, "
                "language, assistant, created_at, created_by, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    fields["folder_id"],
                    fields.get("number", ""),
                    fields["title"],
                    fields.get("description", ""),
                    fields.get("kind", "Other"),
                    fields.get("unit", ""),
                    fields.get("language", ""),
                    1 if fields.get("assistant", True) else 0,
                    now,
                    by,
                    now,
                ),
            )
        return self.document(doc_id) or {}

    def update(self, doc_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        sets = {key: value for key, value in fields.items() if key in self.DOC_COLUMNS}
        if "assistant" in sets:
            sets["assistant"] = 1 if sets["assistant"] else 0
        if not sets:
            return self.document(doc_id)
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                f"UPDATE documents SET {', '.join(f'{key} = ?' for key in sets)}, updated_at = ? "
                "WHERE doc_id = ?",
                (*sets.values(), self._now(), doc_id),
            ).rowcount
            if changed:
                self._refresh_fts(connection, doc_id)
        self.version += 1
        return self.document(doc_id) if changed else None

    def delete(self, doc_id: str) -> bool:
        with self._lock, self._connect() as connection:
            self._drop_passages(connection, doc_id=doc_id)
            connection.execute("DELETE FROM revisions WHERE doc_id = ?", (doc_id,))
            connection.execute("DELETE FROM document_assets WHERE doc_id = ?", (doc_id,))
            deleted = (
                connection.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,)).rowcount > 0
            )
        self.version += 1
        return deleted

    def keep_file(self, data: bytes) -> str:
        """Writes the file once under ``files/`` by its SHA-256 and gives the hash."""

        digest = hashlib.sha256(data).hexdigest()
        path = self.file_path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_suffix(".part")
            partial.write_bytes(data)
            partial.replace(path)
        return digest

    def file_path(self, digest: str) -> Path:
        return self.files / digest[:2] / digest

    def add_revision(
        self, doc_id: str, filename: str, data: bytes, revision: str, issued: str, by: str
    ) -> dict[str, Any]:
        digest = self.keep_file(data)
        rev_id, now = uuid.uuid4().hex[:12], self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO revisions (rev_id, doc_id, revision, issued, filename, sha256, size, "
                "status, uploaded_at, uploaded_by) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
                (rev_id, doc_id, revision, issued, filename, digest, len(data), now, by),
            )
            connection.execute(
                "UPDATE documents SET updated_at = ? WHERE doc_id = ?", (now, doc_id)
            )
        return self.revision(rev_id) or {}

    def revision(self, rev_id: str) -> dict[str, Any] | None:
        if not DOC_ID.match(rev_id):
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM revisions WHERE rev_id = ?", (rev_id,)
            ).fetchone()
        return dict(row) if row else None

    def queue(self, limit: int = 50, since: str | None = None) -> list[dict[str, Any]]:
        """The revisions waiting, being read or that could not be read; with ``since``, also
        those read since then (the suite's Queue keeps a finished item a day)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT r.*, d.title, d.number FROM revisions r JOIN documents d USING (doc_id) "
                "WHERE r.status IN ('queued', 'indexing', 'failed') "
                "OR (r.status = 'indexed' AND r.indexed_at >= ?) ORDER BY r.uploaded_at DESC LIMIT ?",
                (since or "9999", limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_status(self, rev_id: str, status: str, error: str = "") -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE revisions SET status = ?, error = ? WHERE rev_id = ?",
                (status, error[:500], rev_id),
            )

    def requeue_other_embedder(self, name: str) -> int:
        """Queues again the indexed revisions whose vectors another model made (the meaning model
        installed, changed or removed since), so search compares vectors of one model only."""

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE revisions SET status = 'queued', error = '' "
                "WHERE status = 'indexed' AND embedder != ?",
                (name,),
            )
            return cursor.rowcount

    def store_passages(
        self,
        rev_id: str,
        passages: list[Passage],
        assets: list[list[str]],
        vectors: np.ndarray,
        *,
        format: str,
        pages: int,
        embedder: str,
    ) -> None:
        """Keeps an indexed revision's passages and supersedes the document's older revisions."""

        rev = self.revision(rev_id)
        if rev is None:
            return
        doc = self.document(rev["doc_id"]) or {}
        with self._lock, self._connect() as connection:
            self._drop_passages(connection, rev_id=rev_id)
            for passage, tags, vector in zip(passages, assets, vectors):
                cursor = connection.execute(
                    "INSERT INTO passages (rev_id, doc_id, seq, text, page_from, page_to, section, "
                    "assets, vector) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rev_id,
                        rev["doc_id"],
                        passage.seq,
                        passage.text,
                        passage.page_from,
                        passage.page_to,
                        passage.section,
                        json.dumps(tags),
                        np.asarray(vector, dtype=np.float32).tobytes(),
                    ),
                )
                connection.execute(
                    "INSERT INTO passages_fts (rowid, text, section, title) VALUES (?, ?, ?, ?)",
                    (cursor.lastrowid, passage.text, passage.section, _title(doc)),
                )
            older = connection.execute(
                "SELECT rev_id FROM revisions WHERE doc_id = ? AND rev_id != ? "
                "AND status != 'superseded' AND uploaded_at <= ?",
                (rev["doc_id"], rev_id, rev["uploaded_at"]),
            ).fetchall()
            for row in older:
                self._drop_passages(connection, rev_id=row["rev_id"])
                connection.execute(
                    "UPDATE revisions SET status = 'superseded' WHERE rev_id = ?", (row["rev_id"],)
                )
            connection.execute(
                "UPDATE revisions SET status = 'indexed', error = '', format = ?, pages = ?, "
                "embedder = ?, indexed_at = ? WHERE rev_id = ?",
                (format, pages, embedder, self._now(), rev_id),
            )
            # The tags found become suggested assets of the document (a person confirms them).
            counts: dict[str, int] = {}
            for tags in assets:
                for asset in tags:
                    counts[asset] = counts.get(asset, 0) + 1
            connection.execute(
                "DELETE FROM document_assets WHERE doc_id = ? AND source = 'suggested'",
                (rev["doc_id"],),
            )
            for asset, mentions in counts.items():
                connection.execute(
                    "INSERT INTO document_assets (doc_id, asset_id, source, mentions) "
                    "VALUES (?, ?, 'suggested', ?) ON CONFLICT (doc_id, asset_id) "
                    "DO UPDATE SET mentions = excluded.mentions",
                    (rev["doc_id"], asset, mentions),
                )
        self.version += 1

    def _drop_passages(
        self, connection: Any, rev_id: str | None = None, doc_id: str | None = None
    ) -> None:
        column, value = ("rev_id", rev_id) if rev_id else ("doc_id", doc_id)
        connection.execute(
            f"DELETE FROM passages_fts WHERE rowid IN (SELECT passage_id FROM passages WHERE {column} = ?)",
            (value,),
        )
        connection.execute(f"DELETE FROM passages WHERE {column} = ?", (value,))

    def _refresh_fts(self, connection: Any, doc_id: str) -> None:
        doc = connection.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        rows = connection.execute(
            "SELECT passage_id, text, section FROM passages WHERE doc_id = ?", (doc_id,)
        ).fetchall()
        for row in rows:
            connection.execute("DELETE FROM passages_fts WHERE rowid = ?", (row["passage_id"],))
            connection.execute(
                "INSERT INTO passages_fts (rowid, text, section, title) VALUES (?, ?, ?, ?)",
                (row["passage_id"], row["text"], row["section"], _title(dict(doc))),
            )

    # Assets

    def set_assets(self, doc_id: str, assets: list[str]) -> None:
        """The assets a person gave or confirmed; suggestions they did not take stay suggestions."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM document_assets WHERE doc_id = ? AND source = 'manual'", (doc_id,)
            )
            for asset in assets:
                connection.execute(
                    "INSERT INTO document_assets (doc_id, asset_id, source) VALUES (?, ?, 'manual') "
                    "ON CONFLICT (doc_id, asset_id) DO UPDATE SET source = 'manual'",
                    (doc_id, asset),
                )
        self.version += 1

    def _assets(self, connection: Any, doc_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        found: dict[str, list[dict[str, Any]]] = {doc_id: [] for doc_id in doc_ids}
        if not doc_ids:
            return found
        rows = connection.execute(
            f"SELECT * FROM document_assets WHERE doc_id IN ({','.join('?' * len(doc_ids))}) "
            "ORDER BY source, mentions DESC, asset_id",
            doc_ids,
        ).fetchall()
        for row in rows:
            found[row["doc_id"]].append(
                {"asset_id": row["asset_id"], "source": row["source"], "mentions": row["mentions"]}
            )
        return found

    def _document(self, row: Any, assets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        item = dict(row)
        item["assistant"] = bool(item["assistant"])
        item["assets"] = assets.get(item["doc_id"], [])
        return item

    # Passages

    def passages(self, rev_id: str, page: int | None = None) -> list[dict[str, Any]]:
        query, params = "SELECT * FROM passages WHERE rev_id = ?", [rev_id]
        if page is not None:
            query += " AND page_from <= ? AND COALESCE(page_to, page_from) >= ?"
            params += [page, page]
        with self._lock, self._connect() as connection:
            rows = connection.execute(query + " ORDER BY seq", params).fetchall()
        return [self._passage(row) for row in rows]

    def passage_rows(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT p.*, d.title, d.number, d.kind, d.unit, d.folder_id, d.assistant, "
                f"r.revision, r.issued, r.filename FROM passages p "
                f"JOIN documents d ON d.doc_id = p.doc_id JOIN revisions r ON r.rev_id = p.rev_id "
                f"WHERE p.passage_id IN ({','.join('?' * len(ids))})",
                ids,
            ).fetchall()
        return [self._passage(row) for row in rows]

    def keyword(
        self, match: str, limit: int, folders: set[str] | None, assistant: bool
    ) -> list[int]:
        """The ids of the passages whose words match, best first (BM25: text, section, title)."""

        query = (
            "SELECT f.rowid FROM passages_fts f JOIN passages p ON p.passage_id = f.rowid "
            "JOIN documents d ON d.doc_id = p.doc_id LEFT JOIN folders o ON o.folder_id = d.folder_id "
            "WHERE passages_fts MATCH ?"
        )
        params: list[Any] = [match]
        if folders is not None:
            query += f" AND d.folder_id IN ({','.join('?' * len(folders)) or 'NULL'})"
            params.extend(sorted(folders))
        if assistant:
            query += " AND d.assistant = 1 AND COALESCE(o.assistant, 1) = 1"
        query += " ORDER BY bm25(passages_fts, 1.0, 0.6, 0.4) LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as connection:
            try:
                rows = connection.execute(query, params).fetchall()
            except Exception:  # a query FTS5 cannot parse finds nothing by words
                return []
        return [row[0] for row in rows]

    def allowed_ids(self, folders: set[str] | None, assistant: bool) -> np.ndarray | None:
        """The passages a search may return (``None``: all of them)."""

        if folders is None and not assistant:
            return None
        query = (
            "SELECT p.passage_id FROM passages p JOIN documents d ON d.doc_id = p.doc_id "
            "LEFT JOIN folders o ON o.folder_id = d.folder_id WHERE 1 = 1"
        )
        params: list[Any] = []
        if folders is not None:
            query += f" AND d.folder_id IN ({','.join('?' * len(folders)) or 'NULL'})"
            params.extend(sorted(folders))
        if assistant:
            query += " AND d.assistant = 1 AND COALESCE(o.assistant, 1) = 1"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return np.array([row[0] for row in rows], dtype=np.int64)

    def doc_assets(self, doc_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Each document's assets (``document_assets`` rows), by document id."""

        with self._lock, self._connect() as connection:
            return self._assets(connection, list(dict.fromkeys(doc_ids)))

    def linked_docs(self, asset_ids: list[str]) -> set[str]:
        if not asset_ids:
            return set()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT doc_id FROM document_assets WHERE asset_id IN "
                f"({','.join('?' * len(asset_ids))})",
                asset_ids,
            ).fetchall()
        return {row[0] for row in rows}

    def vectors(self) -> tuple[np.ndarray, np.ndarray]:
        """Every current passage's id and vector (the search keeps them in memory per version)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT passage_id, vector FROM passages WHERE vector IS NOT NULL"
            ).fetchall()
        if not rows:
            return np.zeros(0, dtype=np.int64), np.zeros((0, 0), dtype=np.float32)
        ids = np.array([row["passage_id"] for row in rows], dtype=np.int64)
        matrix = np.stack([np.frombuffer(row["vector"], dtype=np.float32) for row in rows])
        return ids, matrix

    def counts(self, folders: set[str] | None = None) -> dict[str, int]:
        """Documents, passages, revisions waiting or failed and bytes; with ``folders``, only
        those of documents in these folders (what a person may see: the reading widget showed
        every folder's counts to anyone, review S2 of 2026-10-27)."""

        docs, params = "SELECT doc_id FROM documents", []
        if folders is not None:
            docs += f" WHERE folder_id IN ({','.join('?' * len(folders)) or 'NULL'})"
            params = sorted(folders)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT (SELECT COUNT(*) FROM documents WHERE doc_id IN ({docs})) AS documents, "
                f"(SELECT COUNT(*) FROM passages WHERE doc_id IN ({docs})) AS passages, "
                "(SELECT COUNT(*) FROM revisions WHERE status IN ('queued', 'indexing') "
                f"AND doc_id IN ({docs})) AS queued, "
                f"(SELECT COUNT(*) FROM revisions WHERE status = 'failed' AND doc_id IN ({docs})) "
                "AS failed, "
                f"(SELECT COALESCE(SUM(size), 0) FROM revisions WHERE doc_id IN ({docs})) AS bytes",
                params * 5,
            ).fetchone()
        return dict(row)

    def _passage(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item.pop("vector", None)
        item["assets"] = self._loads(item.get("assets"), [])
        if "assistant" in item:
            item["assistant"] = bool(item["assistant"])
        return item


def _title(doc: dict[str, Any]) -> str:
    """What the search's ``title`` column holds: the number, the title and the description."""

    parts = (doc.get("number", ""), doc.get("title", ""), doc.get("description", ""))
    return " ".join(part for part in parts if part)
