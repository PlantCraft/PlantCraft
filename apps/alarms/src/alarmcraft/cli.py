"""Command line: ``alarmcraft serve`` and ``alarmcraft check``.

Settings come from the environment (``alarmcraft.config``).
"""

from __future__ import annotations

import argparse
import json
import os


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alarmcraft", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser(
        "serve", help="Run the web application, the API and the alarm monitor."
    )
    serve.add_argument("--host", default=os.environ.get("ALARMCRAFT_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("ALARMCRAFT_PORT", "8110")))
    commands.add_parser("check", help="Check the app key and that PlantCraft answers.")
    args = parser.parse_args(argv)
    from plantcraft_sdk.server.logs import configure_logging

    from alarmcraft import __version__
    from alarmcraft.config import Settings

    # JSON lines to standard error and, for the server, the rotating file in the data folder
    # (ALARMCRAFT_LOG_LEVEL sets the level).
    configure_logging(
        "alarmcraft",
        version=__version__,
        data_dir=Settings.from_environment().data_dir if args.command == "serve" else None,
    )

    if args.command == "serve":
        import uvicorn

        from alarmcraft.api.app import create_app

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

    from alarmcraft.api.runtime import Runtime
    from alarmcraft.config import Settings

    settings = Settings.from_environment()
    settings.monitor = False
    runtime = Runtime(settings)
    try:
        if runtime.service_client is None:
            print(json.dumps({"status": "error", "error": "PLANTCRAFT_APP_KEY is not set."}))
            return 1
        try:
            assets = runtime.service_client.assets()
            signals = runtime.service_client.signals()
        except PlantCraftError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}))
            return 1
        print(
            json.dumps(
                {
                    "status": "ok",
                    "assets": len(assets),
                    "signals": len(signals),
                    "alarms": len(runtime.alarms.list()),
                }
            )
        )
        return 0
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
