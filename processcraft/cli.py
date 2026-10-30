"""Command-line entrypoint for the PlantCraft web application and its tools."""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

from processcraft.i18n import t


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=t("PlantCraft web application"))
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--data-file", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8060)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument(
        "--no-sign-in",
        action="store_true",
        help=t("serves on a network address without sign-in (trusted test networks only)"),
    )
    parser.add_argument(
        "--no-prewarm", action="store_true", help=t("does not fill the history cache at start")
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=t("server processes (default: PLANTCRAFT_WORKERS, else automatic)"),
    )
    return parser


def _users(argv: list[str]) -> int:
    """``processcraft users list|add|password|admin|access``: manage who can sign in."""

    import getpass

    from processcraft.api.runtime import DEFAULT_SCENARIO, PROJECT_ROOT
    from processcraft.auth.access import ACCESS_LEVELS, level_label
    from processcraft.config import load_scenario
    from processcraft.platform.workspace import Workspace

    parser = argparse.ArgumentParser(prog="plantcraft users")
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path(os.environ.get("PLANTCRAFT_SCENARIO", str(DEFAULT_SCENARIO))),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    add = commands.add_parser("add")
    add.add_argument("username")
    add.add_argument("--name", required=True)
    add.add_argument("--role", default="Control engineering")
    add.add_argument(
        "--admin", action="store_true", help=t("can manage people, sources and app keys")
    )
    add.add_argument("--access", choices=ACCESS_LEVELS, help=t("access level (default: editor)"))
    add.add_argument("--apps", help=t("allowed applications, comma-separated (default: all)"))
    access = commands.add_parser("access")
    access.add_argument("username")
    access.add_argument("level", choices=ACCESS_LEVELS)
    access.add_argument("--apps", help=t("allowed applications, comma-separated (default: all)"))
    password = commands.add_parser("password")
    password.add_argument("username")
    admin = commands.add_parser("admin")
    admin.add_argument("username")
    admin.add_argument("--off", action="store_true", help=t("removes admin access"))
    args = parser.parse_args(argv)

    scenario = load_scenario(args.scenario.resolve(), project_root=PROJECT_ROOT)
    users = Workspace(scenario.storage.sqlite_path).users
    if args.command == "list":
        for user in users.list_users():
            signed = t("password set") if users.has_password(user["username"]) else t("no password")
            level = users.access(user["username"])
            apps = (
                t("every application")
                if level is None or level.applications is None
                else ", ".join(level.applications)
            )
            label = level_label(level.level) if level else "-"
            print(
                f"{user['username']:<24} {user['display_name']:<28} {user['role']} ({signed}; {label}; {apps})"
            )
    elif args.command == "add":
        user = users.upsert_user(args.username, args.name, args.role)
        if args.admin or args.access or args.apps:
            users.set_access(
                user["username"],
                "admin" if args.admin else args.access or "editor",
                _apps(args.apps),
            )
        print(
            t(
                "User {username} ready. Set the password with: processcraft users password {username}",
                username=user["username"],
            )
        )
    elif args.command == "access":
        users.set_access(args.username, args.level, _apps(args.apps))
        print(f"{args.username}: {level_label(args.level)}.")
    elif args.command == "admin":
        users.set_admin(args.username, not args.off)
        print(
            t("{username}: without admin access.", username=args.username)
            if args.off
            else t("{username}: with admin access.", username=args.username)
        )
    else:
        secret = os.environ.get("PLANTCRAFT_PASSWORD") or getpass.getpass(t("New password: "))
        users.set_password(args.username, secret)
        print(t("Password of {username} updated.", username=args.username))
    return 0


def _apps(value: str | None) -> list[str] | None:
    return [item.strip() for item in value.split(",") if item.strip()] if value else None


def reset_workspace(scenario_path: Path) -> list[Path]:
    """Delete the scenario's workspace database so the next start seeds it anew."""

    from processcraft.api.runtime import PROJECT_ROOT
    from processcraft.config import load_scenario

    scenario = load_scenario(scenario_path.resolve(), project_root=PROJECT_ROOT)
    database = Path(scenario.storage.sqlite_path)
    removed = []
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def _demo(argv: list[str]) -> int:
    """``processcraft demo reset``: forget the workspace; the next start recreates it.

    ``processcraft demo seed``: fill a running installation with the demo story (demo_seed).
    """

    if argv[:1] == ["seed"]:
        from processcraft.demo_seed import main as seed

        return seed(argv[1:])

    from processcraft.api.runtime import DEFAULT_SCENARIO

    parser = argparse.ArgumentParser(prog="plantcraft demo")
    parser.add_argument("command", choices=["reset", "seed"])
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path(os.environ.get("PLANTCRAFT_SCENARIO", str(DEFAULT_SCENARIO))),
    )
    args = parser.parse_args(argv)
    removed = reset_workspace(args.scenario)
    print(
        t(
            "Workspace deleted ({count} file(s)). The next start recreates the demo.",
            count=len(removed),
        )
    )
    return 0


def _pi(argv: list[str]) -> int:
    """``processcraft pi check``: diagnose the PI Web API source before the pilot."""

    from datetime import datetime, timezone

    from processcraft.api.runtime import PROJECT_ROOT
    from processcraft.config import load_scenario
    from processcraft.industrial_data.pi_check import run_check

    default = os.environ.get("PLANTCRAFT_SCENARIO") or str(
        PROJECT_ROOT / "scenarios" / "opcua_demo.json"
    )
    parser = argparse.ArgumentParser(prog="plantcraft pi")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help=t("tests network, authentication, tags and loops"))
    check.add_argument("--scenario", type=Path, default=Path(default))
    check.add_argument("--hours", type=float, default=48, help=t("window read for each tag"))
    check.add_argument("--report", type=Path, help=t("Markdown file for the report"))
    args = parser.parse_args(argv)

    scenario = load_scenario(args.scenario.resolve(), project_root=PROJECT_ROOT)
    report = run_check(scenario, hours=args.hours)
    print(report.text())
    path = args.report or Path(f"pi-check-{datetime.now(timezone.utc):%Y%m%d-%H%M}Z.md")
    path.write_text(report.markdown(), encoding="utf-8")
    print("\n" + t("Report saved to {path}", path=path.resolve()))
    return 1 if report.failed else 0


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _refuse_open_network(host: str, allowed: bool) -> str | None:
    """Why the server must not start: a network address with sign-in off (secure by default)."""

    from processcraft.auth.config import AuthConfig

    if host in _LOOPBACK or host.startswith("127.") or allowed:
        return None
    if AuthConfig.from_environment().enabled:
        return None
    return t(
        "Sign-in is off, so PlantCraft only serves 127.0.0.1. To serve {host}, turn sign-in on "
        "(PLANTCRAFT_BASIC_AUTH_ENABLED, docs/deployment.md) or pass --no-sign-in on a trusted "
        "test network.",
        host=host,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else __import__("sys").argv[1:]
    if argv[:1] == ["users"]:
        return _users(argv[1:])
    if argv[:1] == ["demo"]:
        return _demo(argv[1:])
    if argv[:1] == ["pi"]:
        return _pi(argv[1:])
    args = _parser().parse_args(argv)
    refusal = _refuse_open_network(args.host, args.no_sign_in)
    if refusal:
        print(refusal, file=__import__("sys").stderr)
        return 2
    if args.scenario:
        os.environ["PLANTCRAFT_SCENARIO"] = str(args.scenario.resolve())
    if args.data_file:
        os.environ["PLANTCRAFT_DATA_FILE"] = str(args.data_file.resolve())
    if args.no_prewarm:
        os.environ["PLANTCRAFT_PREWARM_HISTORY"] = "false"
    os.environ["PLANTCRAFT_PORT"] = str(args.port)
    if args.browser:
        threading.Timer(1.2, webbrowser.open, args=(f"http://{args.host}:{args.port}",)).start()
    import uvicorn

    from processcraft.ops.workers import worker_count

    uvicorn.run(
        "processcraft.api.app:app",
        host=args.host,
        port=args.port,
        workers=args.workers if args.workers else worker_count(),
        proxy_headers=True,
        # The suite's JSON logs (plantcraft_sdk.server.logs); requests are logged by the app.
        log_config=None,
        access_log=False,
    )
    return 0
