"""Command-line entrypoint for the PlantCraft web application and its tools."""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

from plantcraft.i18n import t


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

    from plantcraft.api.runtime import DEFAULT_SCENARIO, PROJECT_ROOT
    from plantcraft.auth.access import ACCESS_LEVELS, level_label
    from plantcraft.config import load_scenario
    from plantcraft.platform.workspace import Workspace

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

    from plantcraft.api.runtime import PROJECT_ROOT
    from plantcraft.config import load_scenario

    scenario = load_scenario(scenario_path.resolve(), project_root=PROJECT_ROOT)
    database = Path(scenario.storage.sqlite_path)
    removed = []
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def update_notice(scenario_path: Path, minutes: float | None) -> int:
    """Announce a public demo's update ``minutes`` from now, or clear it (None)."""

    import time

    from plantcraft.api.runtime import PROJECT_ROOT
    from plantcraft.auth.demo_visits import DemoVisits
    from plantcraft.config import load_scenario
    from plantcraft.db import Database

    scenario = load_scenario(scenario_path.resolve(), project_root=PROJECT_ROOT)
    visits = DemoVisits(Database(scenario.storage.sqlite_path))
    if minutes is None:
        visits.clear_update()
        print("Update notice cleared: visits can start again.")
    else:
        visits.announce_update(time.time() + max(minutes, 0) * 60)
        print(f"Update announced in {minutes:g} min: no new visits; every visit ends then.")
    return 0


def _demo(argv: list[str]) -> int:
    """``processcraft demo reset``: forget the workspace; the next start recreates it.

    ``processcraft demo seed``: fill a running installation with the demo story (demo_seed).

    ``processcraft demo update-notice --in 2`` (or ``--clear``): a public demo's visits see that
    the demo is updated in 2 minutes; then every visit ends and no new one starts until cleared
    (docs/public-demo.md, "Updating the demo").
    """

    if argv[:1] == ["seed"]:
        from plantcraft.demo_seed import main as seed

        return seed(argv[1:])

    from plantcraft.api.runtime import DEFAULT_SCENARIO

    parser = argparse.ArgumentParser(prog="plantcraft demo")
    parser.add_argument("command", choices=["reset", "seed", "update-notice"])
    parser.add_argument("--in", dest="minutes", type=float, default=2.0)
    parser.add_argument("--clear", action="store_true")
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path(os.environ.get("PLANTCRAFT_SCENARIO", str(DEFAULT_SCENARIO))),
    )
    args = parser.parse_args(argv)
    if args.command == "update-notice":
        return update_notice(args.scenario, None if args.clear else args.minutes)
    removed = reset_workspace(args.scenario)
    print(
        t(
            "Workspace deleted ({count} file(s)). The next start recreates the demo.",
            count=len(removed),
        )
    )
    return 0


def _llm(argv: list[str]) -> int:
    """``plantcraft llm set``: add or replace a language model provider and make one of its models
    the installation's default, without the browser (Setup › Language models does the same).

    The key is read from standard input (``--key-stdin``) or a file (``--key-file``), never from
    the command line, so it stays out of the shell's history and the process list:

        docker compose exec -T processcraft plantcraft llm set --name "OpenAI demo" \\
            --kind openai --model gpt-5-mini --key-stdin < demo-openai.key

    ``plantcraft llm show`` prints the providers and the default (keys only as a hint).
    """

    import sys

    from plantcraft.api.runtime import DEFAULT_SCENARIO, PROJECT_ROOT
    from plantcraft.config import load_scenario
    from plantcraft.platform.workspace import Workspace
    from plantcraft.specialists.profiles import PROVIDERS, REASONING, KeyFile, SpecialistStore

    parser = argparse.ArgumentParser(prog="plantcraft llm")
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path(os.environ.get("PLANTCRAFT_SCENARIO", str(DEFAULT_SCENARIO))),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show")
    chosen = commands.add_parser("set")
    chosen.add_argument("--name", required=True, help=t("the provider's name in Setup"))
    chosen.add_argument("--kind", choices=sorted(PROVIDERS), required=True)
    chosen.add_argument("--model", required=True, help=t("the model to use by default"))
    chosen.add_argument("--endpoint", default="")
    chosen.add_argument("--reasoning", choices=sorted(REASONING), default="")
    secret = chosen.add_mutually_exclusive_group()
    secret.add_argument("--key-stdin", action="store_true", help=t("reads the key from stdin"))
    secret.add_argument("--key-file", type=Path, help=t("reads the key from this file"))
    args = parser.parse_args(argv)

    scenario = load_scenario(args.scenario.resolve(), project_root=PROJECT_ROOT)
    workspace = Workspace(scenario.storage.sqlite_path)
    keys = os.environ.get("PLANTCRAFT_SPECIALIST_KEYS_FILE", "").strip() or Path(
        scenario.storage.sqlite_path
    ).with_name("specialist-keys.json")
    store = SpecialistStore(workspace.db, workspace.users, KeyFile(keys))
    if args.command == "show":
        settings = store.settings()
        for item in store.providers():
            default = item["provider_id"] == settings["provider_id"]
            print(
                f"{item['provider_id']:<20} {item['kind']:<10} {', '.join(item['models'])}"
                f" key={item.get('api_key_hint') or '-'}"
                + (f"  default: {settings['model']}" if default else "")
            )
        return 0
    key = None
    if args.key_stdin:
        key = sys.stdin.read()
    elif args.key_file:
        key = args.key_file.read_text(encoding="utf-8")
    if key is not None:
        # An env file's line (OPENAI_API_KEY=sk-...) or the bare key.
        key = key.strip().split("=", 1)[-1].strip().strip("\"'")
        if not key:
            print(t("The key is empty."), file=sys.stderr)
            return 2
    actor = "cli"
    existing = next(
        (item for item in store.providers() if item["name"] == args.name.strip()[:80]), None
    )
    models = [args.model] + [
        name for name in (existing or {}).get("models", []) if name != args.model
    ]
    try:
        provider = store.save_provider(
            existing["provider_id"] if existing else None,
            actor=actor,
            name=args.name,
            kind=args.kind,
            endpoint=args.endpoint,
            models=models,
            api_key=key,
            reasoning=args.reasoning,
        )
        store.save_settings(actor=actor, provider_id=provider["provider_id"], model=args.model)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    store.sync_egress()
    workspace.audit.record(
        actor,
        "language_model.changed",
        "settings:language-model",
        {"provider_id": provider["provider_id"], "model": args.model, "cli": True},
    )
    print(
        t(
            "Provider {provider} saved; the default model is {model}.",
            provider=provider["provider_id"],
            model=args.model,
        )
    )
    return 0


def _pi(argv: list[str]) -> int:
    """``processcraft pi check``: diagnose the PI Web API source before the pilot."""

    from datetime import datetime, timezone

    from plantcraft.api.runtime import PROJECT_ROOT
    from plantcraft.config import load_scenario
    from plantcraft.industrial_data.pi_check import run_check

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

    from plantcraft.auth.config import AuthConfig

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
    if argv[:1] == ["llm"]:
        return _llm(argv[1:])
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

    from plantcraft.api.runtime import data_folder
    from plantcraft.ops.workers import worker_count

    uvicorn.run(
        "plantcraft.api.app:app",
        host=args.host,
        port=args.port,
        workers=args.workers if args.workers else worker_count(folder=data_folder()),
        proxy_headers=True,
        # The suite's JSON logs (plantcraft_sdk.server.logs); requests are logged by the app.
        log_config=None,
        access_log=False,
    )
    return 0
