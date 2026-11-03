"""The command line every app server has, written once: ``<app> serve`` and ``<app> check``.

An app's ``cli.py`` keeps its own commands and calls these for the shared ones:

    parser, commands = app_parser("dashcraft", __doc__, port=8080, serve_help="Run ...")
    args = parser.parse_args(argv)
    start_logs("dashcraft", __version__, Settings, args.command)
    if args.command == "serve":
        return serve(create_app(), args)
    return check_platform(Runtime(Settings.from_environment()))

- ``app_parser``: the parser, with ``serve --host --port`` (defaults ``<APP_ID>_HOST``,
  ``<APP_ID>_PORT``) and, given its help, ``check``.
- ``start_logs``: JSON lines to standard error and, for the server, the rotating file in the
  data folder (``<APP_ID>_LOG_LEVEL`` sets the level; ``plantcraft_sdk.server.logs``).
- ``serve``: uvicorn behind the suite's proxy, with the suite's JSON logs and no access log.
- ``check_platform``: the app key is set and PlantCraft answers (assets, signals), as one JSON
  line; exit 0 or 1.

Only the standard library at import; ``serve`` needs uvicorn, ``check_platform`` the client.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plantcraft_sdk.server.logs import configure_logging


def app_parser(
    app_id: str,
    doc: str | None,
    *,
    port: int,
    serve_help: str,
    check_help: str | None = None,
) -> tuple[argparse.ArgumentParser, Any]:
    """The app's parser and its subcommands, with ``serve`` (and ``check``) already added."""

    description = (doc or "").splitlines()[0] if doc else None
    parser = argparse.ArgumentParser(prog=app_id, description=description)
    commands = parser.add_subparsers(dest="command", required=True)
    prefix = app_id.upper()
    serve_parser = commands.add_parser("serve", help=serve_help)
    serve_parser.add_argument("--host", default=os.environ.get(f"{prefix}_HOST", "127.0.0.1"))
    serve_parser.add_argument(
        "--port", type=int, default=int(os.environ.get(f"{prefix}_PORT", str(port)))
    )
    if check_help is not None:
        commands.add_parser("check", help=check_help)
    return parser, commands


def start_logs(
    app_id: str, version: str, settings: Any, command: str | None, *, to_file: bool | None = None
) -> None:
    """The suite's JSON logs; the rotating file in the data folder for ``serve`` (or as
    ``to_file`` says). ``settings`` is the app's ``Settings`` class."""

    if to_file is None:
        to_file = command == "serve"
    data_dir: Path | None = settings.from_environment().data_dir if to_file else None
    configure_logging(app_id, version=version, data_dir=data_dir)


def serve(app: Any, args: argparse.Namespace, **options: Any) -> int:
    """Run ``app`` (or an import string, with ``factory=True``) on ``args.host``/``args.port``."""

    import uvicorn

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        log_config=None,
        access_log=False,
        **options,
    )
    return 0


def check_platform(runtime: Any, **extra: Callable[[], Any]) -> int:
    """``<app> check``: print whether the app key is set and PlantCraft answers, then shut the
    runtime down. Each ``extra`` adds a field of its own to the answer (``alarms=lambda: ...``).
    """

    from plantcraft_sdk.client import PlantCraftError

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
        answer: dict[str, Any] = {"status": "ok", "assets": len(assets), "signals": len(signals)}
        answer.update({name: field() for name, field in extra.items()})
        print(json.dumps(answer))
        return 0
    finally:
        runtime.shutdown()
