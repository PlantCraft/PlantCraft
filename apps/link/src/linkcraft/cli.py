"""Command line: ``linkcraft serve``, ``engine``, ``round``, ``signals``, ``sync`` and ``compact``.

Settings come from the environment (``linkcraft.config``). ``linkcraft engine`` runs the
schedules and the queue's workers (``engine.process``): ``serve`` starts it as its child unless
``LINKCRAFT_ENGINE`` says otherwise.
"""

from __future__ import annotations

import argparse
import json
import os


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linkcraft", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the web application (API and interface).")
    serve.add_argument("--host", default=os.environ.get("LINKCRAFT_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("LINKCRAFT_PORT", "8140")))
    engine = commands.add_parser("engine", help="Run the schedules and the queue's workers.")
    engine.add_argument("--parent", type=int, default=None, help=argparse.SUPPRESS)
    commands.add_parser("round", help="Sync loops from PlantCraft and run one round now.")
    commands.add_parser("signals", help="Run the Signal quality algorithm once now.")
    commands.add_parser("sync", help="Read the loop assets from PlantCraft.")
    compact = commands.add_parser(
        "compact", help="Give the disk back after old history was thinned (SQLite VACUUM)."
    )
    compact.add_argument(
        "--min-free", type=float, default=0.2, help="Only when this share of the file is free."
    )
    compact.add_argument("--dry-run", action="store_true", help="Say what it would do.")
    args = parser.parse_args(argv)
    from plantcraft_sdk.server.logs import configure_logging

    from linkcraft import __version__
    from linkcraft.config import Settings

    # One JSON line per record, to the console and <data dir>/logs (LINKCRAFT_LOG_LEVEL).
    configure_logging(
        "linkcraft", version=__version__, data_dir=Settings.from_environment().data_dir
    )

    if args.command == "serve":
        import uvicorn

        from linkcraft.api.app import create_app

        uvicorn.run(
            create_app(),
            host=args.host,
            port=args.port,
            proxy_headers=True,
            log_config=None,
            access_log=False,
        )
        return 0

    if args.command == "compact":
        from linkcraft.compact import compact as run_compact

        found = run_compact(
            Settings.from_environment().database_path,
            min_free=args.min_free,
            dry_run=args.dry_run,
        )
        print(json.dumps(found, indent=2))
        return 0

    if args.command == "engine":
        from linkcraft.api.runtime import Runtime
        from linkcraft.engine.process import run_engine

        return run_engine(Settings.from_environment(), Runtime, parent=args.parent)

    from linkcraft.api.runtime import Runtime

    runtime = Runtime(Settings.from_environment())
    try:
        if args.command == "signals":
            result = runtime.run_signal_quality(trigger="manual", started_by="cli")
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("status") in ("ok", "partial") else 1
        if args.command == "sync":
            result = runtime.sync_loops()
        else:
            result = runtime.run_round()
            result.pop("header", None)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") == "ok" else 1
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
