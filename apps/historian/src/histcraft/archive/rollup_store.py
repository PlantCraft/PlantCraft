"""The stored rollups: hourly (``rollups``) and daily and monthly (``rollups_coarse``, H9)
rows, as ``archive.rollup`` computes them. Part of ``ArchiveStore`` (``archive.store``)."""

from __future__ import annotations

from typing import Any

from histcraft.archive.common import _real


class Rollups:
    """``ArchiveStore``'s stored rollups."""

    # Hourly rollups -----------------------------------------------------------------

    def span(self, point: int) -> tuple[int, int] | None:
        """The first and last archived times of a point (ms), or None."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(t0) AS first, MAX(t1) AS last FROM chunks WHERE point = ?", (point,)
            ).fetchone()
        if row is None or row["first"] is None:
            return None
        return int(row["first"]), int(row["last"])

    def rollups(
        self, point: int, step: bool, start_ms: int, end_ms: int
    ) -> dict[int, tuple[float, float, float | None, float | None, int | None]]:
        """``{hour: (cover, area, low, high, n)}`` of the hours in ``[start, end)`` kept for
        ``step`` (``n`` None: kept before the hours had their extremes)."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT hour, cover, area, low, high, n FROM rollups WHERE point = ? AND step = ?"
                " AND hour >= ? AND hour < ?",
                (point, int(step), start_ms, end_ms),
            ).fetchall()
        return {
            int(row["hour"]): (
                float(row["cover"]),
                float(row["area"]),
                _real(row["low"]),
                _real(row["high"]),
                None if row["n"] is None else int(row["n"]),
            )
            for row in rows
        }

    def put_rollups(self, point: int, step: bool, rows: list[tuple[Any, ...]]) -> None:
        """Keep ``(hour, cover, area, low, high, n)`` rows; rows kept for the other ``step`` are
        dropped."""

        self._writing(lambda: self._put_rollups(point, step, rows))

    def _put_rollups(self, point: int, step: bool, rows: list[tuple[Any, ...]]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM rollups WHERE point = ? AND step <> ?", (point, int(step))
            )
            connection.execute(
                "DELETE FROM rollups_coarse WHERE point = ? AND step <> ?", (point, int(step))
            )
            self._ensure("rollups", (row[0] for row in rows))
            connection.executemany(
                "INSERT INTO rollups (point, hour, step, cover, area, low, high, n)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(point, hour) DO UPDATE"
                " SET step = excluded.step, cover = excluded.cover, area = excluded.area,"
                " low = excluded.low, high = excluded.high, n = excluded.n",
                [(point, row[0], int(step), *row[1:3], *_extremes(row)) for row in rows],
            )

    # Daily and monthly rollups (H9) ------------------------------------------------------

    def coarse(
        self, point: int, step: bool, level: int, start_ms: int, end_ms: int
    ) -> dict[int, tuple[int, float, float, float | None, float | None, int]]:
        """``{t0: (t1, cover, area, low, high, n)}`` of the days (``level`` 1) or months (2)
        starting in ``[start, end)`` kept for ``step``."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT t0, t1, cover, area, low, high, n FROM rollups_coarse WHERE point = ?"
                " AND level = ? AND step = ? AND t0 >= ? AND t0 < ?",
                (point, level, int(step), start_ms, end_ms),
            ).fetchall()
        return {
            int(row["t0"]): (
                int(row["t1"]),
                float(row["cover"]),
                float(row["area"]),
                _real(row["low"]),
                _real(row["high"]),
                int(row["n"]),
            )
            for row in rows
        }

    def coarse_end(self, point: int, step: bool, level: int) -> int | None:
        """The end of the newest day or month kept for ``point`` (ms), or None."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(t1) AS t1 FROM rollups_coarse WHERE point = ? AND level = ?"
                " AND step = ?",
                (point, level, int(step)),
            ).fetchone()
        return None if row is None or row["t1"] is None else int(row["t1"])

    def first_rollup(self, point: int, step: bool) -> int | None:
        """The first hour kept in the hourly rollups of ``point`` (ms), or None."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(hour) AS hour FROM rollups WHERE point = ? AND step = ?",
                (point, int(step)),
            ).fetchone()
        return None if row is None or row["hour"] is None else int(row["hour"])

    def put_coarse(self, point: int, step: bool, level: int, rows: list[tuple[Any, ...]]) -> None:
        """Keep ``(t0, t1, cover, area, low, high, n)`` days (``level`` 1) or months (2)."""

        def write() -> None:
            with self._lock, self._connect() as connection:
                connection.executemany(
                    "INSERT INTO rollups_coarse (point, level, t0, t1, step, cover, area, low,"
                    " high, n) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(point, level, t0)"
                    " DO UPDATE SET t1 = excluded.t1, step = excluded.step, cover = excluded.cover,"
                    " area = excluded.area, low = excluded.low, high = excluded.high, n = excluded.n",
                    [
                        (
                            point,
                            level,
                            int(r[0]),
                            int(r[1]),
                            int(step),
                            float(r[2]),
                            float(r[3]),
                            _real(r[4]),
                            _real(r[5]),
                            int(r[6]),
                        )
                        for r in rows
                    ],
                )

        self._writing(write)

    def rollup_rows(self) -> dict[str, int]:
        """How many rollup rows each level keeps: ``{"hour", "day", "month"}`` (the Settings
        page's disk per retention)."""

        with self._connect() as connection:
            hours = connection.execute("SELECT COUNT(*) AS n FROM rollups").fetchone()["n"]
            levels = {
                int(row["level"]): int(row["n"])
                for row in connection.execute(
                    "SELECT level, COUNT(*) AS n FROM rollups_coarse GROUP BY level"
                ).fetchall()
            }
        return {"hour": int(hours or 0), "day": levels.get(1, 0), "month": levels.get(2, 0)}


def _extremes(row: tuple[Any, ...]) -> tuple[float | None, float | None, int | None]:
    """A rollup row's ``low``, ``high`` and ``n`` (a row of three values has none)."""

    if len(row) < 6:
        return None, None, None
    return _real(row[3]), _real(row[4]), None if row[5] is None else int(row[5])
