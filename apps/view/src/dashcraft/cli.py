"""Command line: ``dashcraft serve``, ``dashcraft check`` and ``dashcraft migrate-signals``.

Settings come from the environment (``dashcraft.config``).
"""

from __future__ import annotations

import argparse
import json
import os


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dashcraft", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the web application (API and interface).")
    serve.add_argument("--host", default=os.environ.get("DASHCRAFT_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("DASHCRAFT_PORT", "8080")))
    commands.add_parser(
        "check", help="Check the app key and that PlantCraft answers (assets, signals)."
    )
    commands.add_parser(
        "migrate-signals",
        help="Move saved cards from bare tags to API v1 signal ids (also done at every start).",
    )
    args = parser.parse_args(argv)
    from plantcraft_sdk.server.logs import configure_logging

    from dashcraft import __version__
    from dashcraft.config import Settings

    # JSON lines to standard error and, for the server, the rotating file in the data folder
    # (DASHCRAFT_LOG_LEVEL sets the level).
    configure_logging(
        "dashcraft",
        version=__version__,
        data_dir=Settings.from_environment().data_dir if args.command == "serve" else None,
    )

    if args.command == "serve":
        import uvicorn

        from dashcraft.api.app import create_app

        uvicorn.run(
            create_app(),
            host=args.host,
            port=args.port,
            proxy_headers=True,
            log_config=None,
            access_log=False,
        )
        return 0

    from plantcraft_sdk.client import PlantCraftError

    from dashcraft.api.runtime import Runtime
    from dashcraft.config import Settings

    runtime = Runtime(Settings.from_environment())
    try:
        if runtime.service_client is None:
            print(json.dumps({"status": "error", "error": "PLANTCRAFT_APP_KEY is not set."}))
            return 1
        if args.command == "migrate-signals":
            report = runtime.migrate_signal_ids()
            print(json.dumps({"status": "error" if "error" in report else "ok", **report}))
            return 1 if "error" in report else 0
        try:
            assets = runtime.service_client.assets()
            signals = runtime.service_client.signals()
        except PlantCraftError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}))
            return 1
        print(json.dumps({"status": "ok", "assets": len(assets), "signals": len(signals)}))
        return 0
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
