"""Command line: ``linkcraft serve``, ``engine``, ``round``, ``signals``, ``sync`` and ``compact``.

Settings come from the environment (``linkcraft.config``); the commands every app has, and their logs, are
``plantcraft_sdk.server.cli``. ``linkcraft engine`` runs the
schedules and the queue's workers (``engine.process``): ``serve`` starts it as its child unless
``LINKCRAFT_ENGINE`` says otherwise.
"""

from __future__ import annotations

import argparse
import json

from plantcraft_sdk.server.cli import app_parser, serve, start_logs


def main(argv: list[str] | None = None) -> int:
    parser, commands = app_parser(
        "linkcraft",
        __doc__,
        port=8140,
        serve_help="Run the web application (API and interface).",
    )
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
    from linkcraft import __version__
    from linkcraft.config import Settings

    # One JSON line per record, to the console and <data dir>/logs (LINKCRAFT_LOG_LEVEL).
    start_logs("linkcraft", __version__, Settings, args.command, to_file=True)

    if args.command == "serve":
        from linkcraft.api.app import create_app

        return serve(create_app(), args)

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
