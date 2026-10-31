"""The instructor's commands for a training session on the loop portfolio.

``simcraft loops faults check|key`` reads a fault schedule and prints its answer key (with what
the server saw when each fault began, from the state file). ``snapshot save|list|restore|
delete``, ``freeze``, ``resume``, ``speed`` and ``status`` act on the state file the running
server reads every step, so they need no network and no writable OPC UA node.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from ..settings import env
from .dynamics import LOOP_DEFINITIONS
from .faults import FaultScheduleError, answer_key, answer_key_markdown, load_schedule
from .storage import MAX_SPEED, MIN_SPEED, SimulatorStateStore

DEFAULT_STATE_DB = "var/opcua-state.sqlite3"


def add_commands(commands: Any) -> None:
    """The training commands under ``simcraft loops``."""

    def with_state(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--state-db", default=env("SIMCRAFT_STATE_DB", DEFAULT_STATE_DB))
        return parser

    faults = commands.add_parser("faults", help="check a fault schedule or print its answer key")
    which = faults.add_subparsers(dest="faults_command", required=True)
    which.add_parser("check", help="check a schedule").add_argument("schedule")
    key = with_state(which.add_parser("key", help="the instructor's answer key"))
    key.add_argument("schedule")
    key.add_argument("--format", choices=("markdown", "json"), default="markdown")

    snapshot = commands.add_parser("snapshot", help="named snapshots of every loop's state")
    action = snapshot.add_subparsers(dest="snapshot_command", required=True)
    save = with_state(action.add_parser("save", help="keep the current state under a name"))
    save.add_argument("name")
    save.add_argument("--note", default="")
    with_state(action.add_parser("list", help="the snapshots kept"))
    restore = with_state(action.add_parser("restore", help="put a snapshot back (next step)"))
    restore.add_argument("name")
    delete = with_state(action.add_parser("delete", help="forget a snapshot"))
    delete.add_argument("name")

    with_state(commands.add_parser("freeze", help="hold the model: nothing moves or publishes"))
    with_state(commands.add_parser("resume", help="run again after a freeze"))
    speed = with_state(commands.add_parser("speed", help="run the model N times the clock"))
    speed.add_argument("factor", type=float, help=f"from {MIN_SPEED:g} to {MAX_SPEED:g}")
    with_state(commands.add_parser("status", help="frozen, speed, snapshots and faults fired"))


COMMANDS = {"faults", "snapshot", "freeze", "resume", "speed", "status"}


def run(args: argparse.Namespace) -> int:
    loops = {definition.loop_id for definition in LOOP_DEFINITIONS}
    try:
        if args.loops_command == "faults":
            schedule = load_schedule(args.schedule, loops)
            if args.faults_command == "check":
                print(f"PASS: {len(schedule)} faults on "
                      f"{len({item.loop_id for item in schedule})} loops")  # fmt: skip
                return 0
            fired = SimulatorStateStore(args.state_db).fired()
            found = answer_key(schedule, fired)
            print(json.dumps(found, indent=2) if args.format == "json"
                  else answer_key_markdown(found), end="" if args.format == "markdown" else "\n")  # fmt: skip
            return 0
        store = SimulatorStateStore(args.state_db)
        if args.loops_command == "snapshot":
            if args.snapshot_command == "save":
                print(json.dumps(store.save_snapshot(args.name, args.note)))
            elif args.snapshot_command == "list":
                print(json.dumps(store.snapshots(), indent=2))
            elif args.snapshot_command == "restore":
                store.set_controls(restore=args.name)
                print(f"snapshot {args.name!r} is restored at the server's next step")
            elif not store.delete_snapshot(args.name):
                raise LookupError(f"no snapshot {args.name!r}")
            return 0
        if args.loops_command == "freeze":
            print(json.dumps(store.set_controls(frozen=True)))
        elif args.loops_command == "resume":
            print(json.dumps(store.set_controls(frozen=False)))
        elif args.loops_command == "speed":
            print(json.dumps(store.set_controls(speed=args.factor)))
        else:
            print(json.dumps({**store.controls(), "snapshots": store.snapshots(),
                              "faults_fired": store.fired()}, indent=2))  # fmt: skip
        return 0
    except (FaultScheduleError, LookupError, ValueError) as exc:
        print(f"FAIL: {exc}")
        return 2
