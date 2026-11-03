"""Command line: ``histcraft serve``, ``histcraft collect``, ``histcraft housekeeping``.

Settings come from the environment (``histcraft.config``); the commands every app has, and
their logs, are ``plantcraft_sdk.server.cli``.

- ``serve``: the web application (API and pages); with ``HISTCRAFT_COLLECTOR=embedded``
  (the default) it also collects.
- ``collect``: the collector alone, for the container on the plant network.
- ``housekeeping``: merge small chunks and apply retention now (the collector does it hourly;
  refused while a collector runs, it writes the archive).
- ``healthcheck``: exit 0 while the collector's heartbeat is fresh (the collector container's
  health check: it has no HTTP port).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import signal
from pathlib import Path

from plantcraft_sdk.server.cli import app_parser, serve, start_logs


def main(argv: list[str] | None = None) -> int:
    parser, commands = app_parser(
        "histcraft", __doc__, port=8100, serve_help="Run the web application (API and pages)."
    )
    commands.add_parser("collect", help="Run the collector alone.")
    commands.add_parser("housekeeping", help="Merge small chunks and apply retention now.")
    commands.add_parser("healthcheck", help="Exit 0 while the collector's heartbeat is fresh.")
    args = parser.parse_args(argv)
    # The server (uid 10008) and the collector (uid 10013, group 10008) share /data: files they
    # create stay readable and writable by the group, closed to everyone else.
    os.umask(0o007)
    from histcraft import __version__
    from histcraft.config import Settings

    start_logs("histcraft", __version__, Settings, args.command)
    logging.getLogger("asyncua").setLevel(logging.WARNING)

    if args.command == "serve":
        import uvicorn
        from plantcraft_sdk.server.workers import worker_count

        settings = Settings.from_environment()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        # Heavy reads run in Python: one process answers them on one core (0.6.0 load tests).
        # A collector inside the server keeps it to one process.
        workers = (
            1
            if settings.collector == "embedded"
            else worker_count("HISTCRAFT_WORKERS", folder=settings.data_dir)
        )
        if workers > 1:
            # Each process builds its app from the environment and holds its part of the read
            # budget (``Settings.read_values``).
            os.environ["HISTCRAFT_SERVER_PROCESSES"] = str(workers)
        extra: dict = {}
        if (
            workers > 1
            and "timeout_worker_healthcheck" in inspect.signature(uvicorn.run).parameters
        ):
            # A worker turning a long read into JSON (240 h of 10 signals, ~29 MB) holds the GIL
            # past uvicorn's 5 s ping, and the supervisor killed it mid-answer: a 502 for the
            # reader (pc-carga, 2026-11-01). Only a worker silent for a minute is stuck.
            extra["timeout_worker_healthcheck"] = 60
        return serve(
            "histcraft.cli:app_factory" if workers > 1 else _app(),
            args,
            factory=workers > 1,
            workers=workers,
            **extra,
        )

    from histcraft.archive.store import ArchiveStore
    from histcraft.catalog.store import CatalogStore
    from histcraft.collector.service import Collector
    from histcraft.config import Settings
    from histcraft.db import Database

    settings = Settings.from_environment()
    if args.command == "healthcheck":
        from histcraft.archive.store import now_ms

        target = settings.archive_target
        if isinstance(target, Path) and not target.exists():
            return 1
        try:
            archive = ArchiveStore(Database(target, password=settings.database_password()))
            state = archive.state().get("collector") or {}
        except Exception:  # database not reachable: unhealthy, without a traceback
            return 1
        fresh = (
            now_ms() - int(state.get("heartbeat") or 0)
            < max(60.0, 6 * settings.flush_seconds) * 1000
        )
        return 0 if fresh else 1
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    password = settings.database_password()
    collector = Collector(
        settings,
        CatalogStore(Database(settings.config_target, password=password)),
        ArchiveStore(Database(settings.archive_target, password=password)),
    )
    if args.command == "housekeeping":
        # It writes the archive: only while no collector holds it (``collector.lease``).
        if not collector.lease.acquire():
            print("A collector is running: stop it first (it does this hourly).")
            return 1
        try:
            print(json.dumps(collector.housekeeping(force=True)))
        finally:
            collector.lease.release()
        return 0

    async def run() -> bool:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in ("SIGINT", "SIGTERM"):
            try:
                loop.add_signal_handler(getattr(signal, name), stop.set)
            except (NotImplementedError, AttributeError):
                pass
        return await collector.run(stop)

    # A lost lease (the database connection dropped) exits 1: the container restarts and waits.
    return 0 if asyncio.run(run()) else 1


if __name__ == "__main__":
    raise SystemExit(main())


def _app():
    from histcraft.api.app import create_app

    return create_app()


def app_factory():
    """One server process's app when there are several (``uvicorn --factory``): its own JSON
    logs, as ``main`` sets them for one."""

    from histcraft import __version__
    from histcraft.config import Settings

    start_logs("histcraft", __version__, Settings, "serve")
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    return _app()
