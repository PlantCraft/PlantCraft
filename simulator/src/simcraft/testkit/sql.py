"""The plant's history as tables of a PostgreSQL database, for Historian's SQL sources.

- ``plant_wide``: ``time`` (timestamptz), then one column per tag, on the grid every tag shares;
- ``plant_long``: ``time``, ``tag``, ``value``, every sample;
- ``plant_naive``: as ``plant_long`` with ``timestamp without time zone`` holding UTC, which
  the PostgreSQL driver reads as UTC.

``SOURCES`` holds the query, measurement and columns of each, as a Historian source takes them.
Needs ``psycopg`` (LGPL, dynamically linked), in the ``testkit`` extra.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .plant import Series, numbers

SOURCES: dict[str, dict[str, Any]] = {
    "plant_wide": {
        "query": "SELECT * FROM plant_wide ORDER BY time",
        "measurement": "plant_wide",
        "time_column": "time",
        "tag_columns": [],
    },
    "plant_long": {
        "query": "SELECT time, tag, value FROM plant_long ORDER BY time, tag",
        "measurement": "plant_long",
        "time_column": "time",
        "tag_columns": ["tag"],
    },
    "plant_naive": {
        "query": "SELECT time, tag, value FROM plant_naive ORDER BY time, tag",
        "measurement": "plant_naive",
        "time_column": "time",
        "tag_columns": ["tag"],
    },
}


def column(tag: str) -> str:
    return tag.lower().replace("-", "_").replace(".", "_")


def wide_rows(series: dict[str, Series]) -> tuple[list[str], list[tuple[int, list[float]]]]:
    """The tags and the rows (time ms, values) where every number tag has a value."""

    tags = list(numbers(series))
    cells = {tag: dict(zip(series[tag].times, series[tag].values, strict=True)) for tag in tags}
    shared = sorted(set.intersection(*(set(cells[tag]) for tag in tags)))
    return tags, [(stamp, [float(cells[tag][stamp]) for tag in tags]) for stamp in shared]


def expected(series: dict[str, Series]) -> dict[str, dict[str, list[tuple[int, float]]]]:
    """By source: Browse's tag -> the (time ms, value) Historian archives."""

    tags, rows = wide_rows(series)
    wide = {
        column(tag): [(stamp, values[i]) for stamp, values in rows] for i, tag in enumerate(tags)
    }
    long = {
        f"{tag}.value": [(t, float(v)) for t, v in zip(item.times, item.values, strict=True)]
        for tag, item in numbers(series).items()
    }
    return {"plant_wide": wide, "plant_long": long, "plant_naive": long}


def write(dsn: str, series: dict[str, Series]) -> None:
    """Create (again) the three tables in the database at ``dsn``."""

    import psycopg

    def at(ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000, UTC)

    tags, rows = wide_rows(series)
    long = [
        (at(t), tag, float(v))
        for tag, item in numbers(series).items()
        for t, v in zip(item.times, item.values, strict=True)
    ]
    with psycopg.connect(dsn, autocommit=True) as connection:
        for table in SOURCES:
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        columns = ", ".join(f"{column(tag)} double precision" for tag in tags)
        connection.execute(f"CREATE TABLE plant_wide (time timestamptz PRIMARY KEY, {columns})")
        marks = ", ".join(["%s"] * (len(tags) + 1))
        with connection.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO plant_wide VALUES ({marks})",
                [(at(stamp), *values) for stamp, values in rows],
            )
            connection.execute(
                "CREATE TABLE plant_long (time timestamptz, tag text, value double precision)"
            )
            cursor.executemany("INSERT INTO plant_long VALUES (%s, %s, %s)", long)
            connection.execute(
                "CREATE TABLE plant_naive (time timestamp, tag text, value double precision)"
            )
            cursor.executemany(
                "INSERT INTO plant_naive VALUES (%s, %s, %s)",
                [(when.replace(tzinfo=None), tag, value) for when, tag, value in long],
            )
