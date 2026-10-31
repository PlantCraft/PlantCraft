"""Command line: ``histcraft serve``, ``histcraft collect``, ``histcraft housekeeping``.

Settings come from the environment (``histcraft.config``).

- ``serve``: the web application (API and pages); with ``HISTCRAFT_COLLECTOR=embedded``
  (the default) it also collects.
- ``collect``: the collector alone, for the container on the plant network.
- ``housekeeping``: merge small chunks and apply retention now (the collector does it hourly;
  refused while a collector runs, it writes the archive).
- ``healthcheck``: exit 0 while the collector's heartbeat is fresh (the collector container's
  health check: it has no HTTP port).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="histcraft", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the web application (API and pages).")
    serve.add_argument("--host", default=os.environ.get("HISTCRAFT_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("HISTCRAFT_PORT", "8100")))
    commands.add_parser("collect", help="Run the collector alone.")
    commands.add_parser("housekeeping", help="Merge small chunks and apply retention now.")
    commands.add_parser("healthcheck", help="Exit 0 while the collector's heartbeat is fresh.")
    args = parser.parse_args(argv)
    # The server (uid 10008) and the collector (uid 10013, group 10008) share /data: files they
    # create stay readable and writable by the group, closed to everyone else.
    os.umask(0o007)
    from plantcraft_sdk.server.logs import configure_logging

    from histcraft import __version__
    from histcraft.config import Settings

    # JSON lines to standard error and, for the server, the rotating file in the data folder
    # (HISTCRAFT_LOG_LEVEL sets the level).
    configure_logging(
        "histcraft",
        version=__version__,
        data_dir=Settings.from_environment().data_dir if args.command == "serve" else None,
    )
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
        uvicorn.run(
            "histcraft.cli:app_factory" if workers > 1 else _app(),
            factory=workers > 1,
            workers=workers,
            host=args.host,
            port=args.port,
            proxy_headers=True,
            log_config=None,
            access_log=False,
        )
        return 0

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

    from plantcraft_sdk.server.logs import configure_logging

    from histcraft import __version__
    from histcraft.config import Settings

    configure_logging(
        "histcraft", version=__version__, data_dir=Settings.from_environment().data_dir
    )
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    return _app()
