"""Command line: ``alarmcraft serve`` and ``alarmcraft check``.

Settings come from the environment (``alarmcraft.config``). The commands every app has, and
their logs, are ``plantcraft_sdk.server.cli``.
"""

from __future__ import annotations

from plantcraft_sdk.server.cli import app_parser, check_platform, serve, start_logs


def main(argv: list[str] | None = None) -> int:
    parser, _commands = app_parser(
        "alarmcraft",
        __doc__,
        port=8110,
        serve_help="Run the web application, the API and the alarm monitor.",
        check_help="Check the app key and that PlantCraft answers.",
    )
    args = parser.parse_args(argv)
    from alarmcraft import __version__
    from alarmcraft.config import Settings

    start_logs("alarmcraft", __version__, Settings, args.command)

    if args.command == "serve":
        from alarmcraft.api.app import create_app

        return serve(create_app(), args)

    from alarmcraft.api.runtime import Runtime

    settings = Settings.from_environment()
    settings.monitor = False
    runtime = Runtime(settings)
    return check_platform(runtime, alarms=lambda: len(runtime.alarms.list()))


if __name__ == "__main__":
    raise SystemExit(main())
