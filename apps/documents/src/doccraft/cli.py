"""Command line: ``doccraft serve`` and ``doccraft check``.

Settings come from the environment (``doccraft.config``). The commands every app has, and
their logs, are ``plantcraft_sdk.server.cli``.
"""

from __future__ import annotations

from plantcraft_sdk.server.cli import app_parser, check_platform, serve, start_logs


def main(argv: list[str] | None = None) -> int:
    parser, _commands = app_parser(
        "doccraft",
        __doc__,
        port=8150,
        serve_help="Run the web application and the API.",
        check_help="Check the app key and that PlantCraft answers.",
    )
    args = parser.parse_args(argv)
    from doccraft import __version__
    from doccraft.config import Settings

    start_logs("doccraft", __version__, Settings, args.command)

    if args.command == "serve":
        from doccraft.api.app import create_app

        return serve(create_app(), args)

    from doccraft.api.runtime import Runtime

    runtime = Runtime(Settings.from_environment())
    return check_platform(runtime, documents=lambda: runtime.store.counts()["documents"])


if __name__ == "__main__":
    raise SystemExit(main())
