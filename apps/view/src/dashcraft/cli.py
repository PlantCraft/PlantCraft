"""Command line: ``dashcraft serve``, ``dashcraft check`` and ``dashcraft migrate-signals``.

Settings come from the environment (``dashcraft.config``). The commands every app has, and
their logs, are ``plantcraft_sdk.server.cli``.
"""

from __future__ import annotations

import json

from plantcraft_sdk.server.cli import app_parser, check_platform, serve, start_logs


def main(argv: list[str] | None = None) -> int:
    parser, commands = app_parser(
        "dashcraft",
        __doc__,
        port=8080,
        serve_help="Run the web application (API and interface).",
        check_help="Check the app key and that PlantCraft answers (assets, signals).",
    )
    commands.add_parser(
        "migrate-signals",
        help="Move saved cards from bare tags to API v1 signal ids (also done at every start).",
    )
    args = parser.parse_args(argv)
    from dashcraft import __version__
    from dashcraft.config import Settings

    start_logs("dashcraft", __version__, Settings, args.command)

    if args.command == "serve":
        from dashcraft.api.app import create_app

        return serve(create_app(), args)

    from dashcraft.api.runtime import Runtime

    runtime = Runtime(Settings.from_environment())
    if args.command == "check":
        return check_platform(runtime)
    try:
        if runtime.service_client is None:
            print(json.dumps({"status": "error", "error": "PLANTCRAFT_APP_KEY is not set."}))
            return 1
        report = runtime.migrate_signal_ids()
        print(json.dumps({"status": "error" if "error" in report else "ok", **report}))
        return 1 if "error" in report else 0
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
