# The app's data

Each app keeps its own objects in its own SQLite database, in its data folder
(`STARTER_DATA_DIR`, `/data` in the image). Plant data is never stored here: the app keeps the
ids of assets and signals and reads the rest from PlantCraft.

## A store

A store is a class on `plantcraft_sdk.server.store.Store` with its `SCHEMA`:

```python
class NoteStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS notes (
        note_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        ...
    );
    CREATE INDEX IF NOT EXISTS notes_asset ON notes (asset_id, updated_at);
    """
```

Inside a method, `with self._lock, self._connect() as connection:` gives a connection that
commits at the end; rows come back as `sqlite3.Row` (`dict(row)` turns one into a dict).
`self._now()` is the time in UTC as ISO 8601: store UTC, show local time in the interface.
Always pass values as parameters (`?`), never in the SQL text.

The database is opened once, in `Runtime` (`Database(settings.database_path, version=...)`), and
every store of the app shares it. Name the file in `app.toml` `[backup] sqlite` so the suite's
backup copies it safely.

## Changing a table after a release

`SCHEMA` is the table as a **new** installation makes it. Once a version of your app is installed
somewhere, a database already exists there with the old table. A change is then a named step in
the store's `MIGRATIONS`, run once per database, in order, and recorded:

```python
from plantcraft_sdk.server.store import Migration, Store, add_columns


class NoteStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS notes (
        ...,
        pinned INTEGER NOT NULL DEFAULT 0      -- new installations get it here
    );
    """
    MIGRATIONS = (
        # existing installations get it here; the name never changes and the step stays forever
        Migration("0.2-pinned", add_columns("notes", {"pinned": "INTEGER NOT NULL DEFAULT 0"})),
    )
```

Rules:

- Steps only go forward and only add (columns, tables, indexes). Never rename or remove a step.
- Never write code that inspects the table at start to decide what to change.
- An index on a new column goes in a step too, not only in `SCHEMA`.
- A database written by a newer version is refused by an older one (the file is stamped with the
  app's version). Going back a version restores its backup.

Test it: `apptest.upgrade_problems(NoteStore, NoteStore, tmp_path)` opens the store on the older
table and fails if anything is missing.

## Backup

`app.toml` says what the suite's backup takes from the data folder:

```toml
[backup]
sqlite = ["starter.sqlite3"]   # online SQLite backup, then an integrity check
files = []                     # copied as they are; a folder ends in "/"
skip = ["logs/"]               # left out
```

Anything not named is copied as a file. Keep everything the app needs in its data folder: the
image's root file system is read-only.
