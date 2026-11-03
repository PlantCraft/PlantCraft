"""Command line: ``modelcraft serve``, ``modelcraft check`` and ``modelcraft runner``.

Settings come from the environment (``modelcraft.config``). The commands every app has, and
their logs, are ``plantcraft_sdk.server.cli``.
"""

from __future__ import annotations

import json

from plantcraft_sdk.server.cli import app_parser, serve, start_logs


def main(argv: list[str] | None = None) -> int:
    parser, commands = app_parser(
        "modelcraft",
        __doc__,
        port=8130,
        serve_help="Run the web application and the API.",
        check_help="Check the app key, PlantCraft and the Modelica runner.",
    )
    commands.add_parser(
        "runner",
        help="Run the Modelica runner on this machine (needs omc; the suite runs it in its own container).",
        add_help=False,
    )
    args, rest = parser.parse_known_args(argv)
    from modelcraft import __version__
    from modelcraft.config import Settings

    start_logs("modelcraft", __version__, Settings, args.command)

    if args.command == "runner":
        from modelcraft.omc import runner

        return runner.main(rest)
    if rest:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")

    if args.command == "serve":
        from modelcraft.api.app import create_app

        return serve(create_app(), args)

    from plantcraft_sdk.client import PlantCraftError

    from modelcraft.api.runtime import Runtime

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
