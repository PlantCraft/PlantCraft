"""Command line: ``modelcraft serve``, ``modelcraft check`` and ``modelcraft runner``.

Settings come from the environment (``modelcraft.config``).
"""

from __future__ import annotations

import argparse
import json
import os


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modelcraft", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the web application and the API.")
    serve.add_argument("--host", default=os.environ.get("MODELCRAFT_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("MODELCRAFT_PORT", "8130")))
    commands.add_parser("check", help="Check the app key, PlantCraft and the Modelica runner.")
    commands.add_parser(
        "runner",
        help="Run the Modelica runner on this machine (needs omc; the suite runs it in its own container).",
        add_help=False,
    )
    args, rest = parser.parse_known_args(argv)
    from plantcraft_sdk.server.logs import configure_logging

    from modelcraft import __version__
    from modelcraft.config import Settings

    # JSON lines to standard error and, for the server, the rotating file in the data folder
    # (MODELCRAFT_LOG_LEVEL sets the level).
    configure_logging(
        "modelcraft",
        version=__version__,
        data_dir=Settings.from_environment().data_dir if args.command == "serve" else None,
    )

    if args.command == "runner":
        from modelcraft.omc import runner

        return runner.main(rest)
    if rest:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")

    if args.command == "serve":
        import uvicorn

        from modelcraft.api.app import create_app

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

    from modelcraft.api.runtime import Runtime
    from modelcraft.config import Settings

    settings = Settings.from_environment()
    settings.examples = False
    runtime = Runtime(settings)
    try:
        answer: dict = {
            "runner": runtime.workbench.runner(),
            "projects": len(runtime.projects.list()),
        }
        if runtime.service_client is None:
            print(
                json.dumps({**answer, "status": "error", "error": "PLANTCRAFT_APP_KEY is not set."})
            )
            return 1
        try:
            runtime.service_client.apps()
        except PlantCraftError as exc:
            print(json.dumps({**answer, "status": "error", "error": str(exc)}))
            return 1
        ok = answer["runner"].get("available")
        print(json.dumps({**answer, "status": "ok" if ok else "error"}))
        return 0 if ok else 1
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
