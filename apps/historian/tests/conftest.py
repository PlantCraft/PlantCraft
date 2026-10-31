"""Shared fixtures: a FakePlantCraft whose people may open Historian, and a Historian on it.

The suite runs on SQLite files by default. With ``HISTCRAFT_TEST_DATABASE_URL`` set to a
PostgreSQL database (``make test-postgres``, the CI ``postgres`` job), every test runs on
PostgreSQL instead, in a schema of its own that is dropped at the end of the session.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk.testing import BASE_URL, FakePlantCraft

from histcraft.api.app import create_app
from histcraft.api.runtime import Runtime
from histcraft.config import Settings
from histcraft.db import Database, close_pools

TEST_DATABASE_URL = os.environ.get("HISTCRAFT_TEST_DATABASE_URL", "").strip()
_SCHEMAS: set[str] = set()

USERS = {
    "admin": {"name": "Administrator", "level": "admin", "apps": {"histcraft": "editor"}},
    "engineer": {"name": "Process Engineer", "level": "editor", "apps": {"histcraft": "editor"}},
    "operator": {"name": "Operator", "level": "viewer", "apps": {"histcraft": "viewer"}},
    "outsider": {"name": "No Apps", "level": "viewer", "apps": {"cpmcraft": "editor"}},
}


def postgres_url(tmp_path: Path) -> str:
    """The test database, in a schema of this test's own (one per ``tmp_path``)."""

    import psycopg

    schema = "test_" + hashlib.sha1(str(tmp_path).encode()).hexdigest()[:16]
    if schema not in _SCHEMAS:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        _SCHEMAS.add(schema)
    join = "&" if "?" in TEST_DATABASE_URL else "?"
    return f"{TEST_DATABASE_URL}{join}options=-csearch_path%3D{schema}"


def database(tmp_path: Path, name: str = "archive") -> Database:
    """A test database: ``<name>.sqlite3`` in ``tmp_path``, or this test's PostgreSQL schema."""

    if TEST_DATABASE_URL:
        return Database(postgres_url(tmp_path))
    return Database(tmp_path / f"{name}.sqlite3")


postgres_only = pytest.mark.skipif(not TEST_DATABASE_URL, reason="needs a PostgreSQL database")
sqlite_only = pytest.mark.skipif(bool(TEST_DATABASE_URL), reason="SQLite files only")


@pytest.fixture(autouse=True)
def _close_pools():
    yield
    if TEST_DATABASE_URL:
        close_pools()


@pytest.fixture(scope="session", autouse=True)
def _drop_schemas():
    yield
    if TEST_DATABASE_URL and _SCHEMAS:
        import psycopg

        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            for schema in sorted(_SCHEMAS):
                connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture(autouse=True)
def _csv_folder(tmp_path, monkeypatch):
    """CSV sources read only inside HISTCRAFT_CSV_DIRS: the tests write their files in tmp_path."""

    monkeypatch.setenv("HISTCRAFT_CSV_DIRS", str(tmp_path))


@pytest.fixture(autouse=True)
def _restore_logging():
    """A test that runs ``histcraft.cli.main`` installs the suite's JSON logs on the root logger:
    put the root logger back, so later tests do not log every request as JSON."""

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def make_settings(tmp_path, **changes) -> Settings:
    values = {
        "processcraft_url": BASE_URL,
        "data_dir": tmp_path,
        "collector": "off",
        "flush_seconds": 0.3,
        "config_seconds": 0.2,
        "opcua_timeout": 3.0,
    }
    if TEST_DATABASE_URL:
        values["database_url"] = postgres_url(tmp_path)
    values.update(changes)
    return Settings(**values)


@pytest.fixture
def fake():
    return FakePlantCraft(users=USERS)


@pytest.fixture
def runtime(tmp_path, fake):
    rt = Runtime(
        make_settings(tmp_path), verifier=fake.verifier("histcraft"), http_client=fake.http_client()
    )
    yield rt
    rt.shutdown()


def client_for(runtime: Runtime, fake, username: str | None = "admin") -> TestClient:
    client = TestClient(create_app(runtime), raise_server_exceptions=False)
    if username:
        client.headers["Authorization"] = f"Bearer {fake.token(username)}"
    return client


@pytest.fixture
def client(runtime, fake):
    with client_for(runtime, fake) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    """The app's token used only what app.toml [permissions] declares (PlantCraft answers 403)."""

    from pathlib import Path

    from plantcraft_sdk import apptest

    problems = apptest.permission_problems(Path(__file__).resolve().parents[1], "histcraft")
    if problems and exitstatus == 0:
        print("\n" + "\n".join(problems))
        session.exitstatus = 1
