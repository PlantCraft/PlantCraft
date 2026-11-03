"""The demo story: fills a fresh installation with data that explains the suite by itself.

``plantcraft demo seed`` (run by ``install.sh --demo`` inside the PlantCraft container) signs
in as the administrator and goes through every app's own HTTP API, exactly as a person would in
the browser, so the story only uses what the apps already offer. One plant, Riverbend Refinery
(the Simulator: four units, 50 loops), and one week of a team that looks after it:

1. PlantCraft: the plant map (the OPC UA source, units, areas and loops), ten people in their
   groups, the read-only visitor ``demo``, a valve specialist, conversations and actions, and
   three weeks of their past.
2. Historian: the Simulator's last 48 hours archived, the lab's analyses (a CSV source) and a
   finished test run imported.
3. Analytics: loops with their criticality and three monitors: Control loop
   performance on every loop, Signal quality on every signal and the process model beside the
   plant (Furnaces says TIC-1209 drifts), with 48 hours of results replayed.
4. View: Plant overview (public link), Control room (pages in kiosk mode) and Loop detail, four
   descriptive reports sent on a schedule (loop performance, alarms, the unit's day, valves and
   instruments), and the process display "Riverbend plant" (an overview page, then a page per
   part of a unit with its loops' values, health and mode).
5. Alarms: seven example rules (Simple, Blocks and Python), two days of the pressure alarm's past
   and a silence on U-300.
6. Models: a simulation of each example, one fed by the plant, two grid studies, an optimization
   of the level controller and the Furnaces FMU published to Analytics.
7. Documents: the plant's twelve documents, linked to their assets.
8. Desk: notes, to-dos, the calendar, the team's day, assistant chats and two notebooks of loop
   data.

The plant's problems are the Simulator's own (``simcraft loops serve``): FIC-1003 has a sticky
valve, PIC-1202 oscillates, TIC-1209 drifts, TIC-1104 sees a cyclic disturbance; FIC-1001 is the
healthy loop to compare with. Every day and time is the plant's (the installation's zone).

Every step is idempotent: running the seed again adds only what is missing. The HTTP steps use
only the Python standard library.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path
from typing import Any

from .actions import OPEN_ACTIONS, actions
from .alarms import (
    ALARM_OPERATOR,
    ALARM_PHILOSOPHY,
    ALARM_REPLAY_HOURS,
    ALARM_RULES,
    ALARM_SILENCE,
    DAY_SHIFT,
    INSTRUMENTS,
    ON_CALL,
    PLANT_ZONE,
    PRESSURE_LOOP,
    PRESSURE_QUANTILE,
    PROCESS,
    SATURATION_CODE,
    SATURATION_DIAGRAM,
    SUPERVISOR,
    TO_COORDINATOR,
    U100,
    U200,
    _event,
    _iso,
    _node,
    _pressure_archive,
    _pressure_limit,
    _simple,
    _wire,
    alarmcraft,
)
from .analytics import link_models, linkcraft
from .assistant import (
    ASSISTANT_CHATS,
    DEMO_ANSWER,
    NOTEBOOKS,
    _signals_of,
    assistant_and_notebooks,
    chat_sources,
)
from .base import (
    _STARTED,
    CRITICALITY,
    DEMO_MAP,
    STICTION_LOOPS,
    SURGE_LEVELS,
    VISITOR,
    Http,
    SeedError,
    Suite,
    _day,
    _decode,
    _detail,
    _ident,
    _InsidePolicy,
    _items,
    log,
    wait_until,
)
from .conversations import CONVERSATIONS, conversations, follow_ups
from .desk import (
    IT_ACTIONS,
    SHIFT_LIST,
    SHIFT_TODOS,
    START_HERE,
    TEAM_DAY,
    TOUR,
    VALVE_NOTE,
    VALVE_PLAN,
    VALVE_STEPS,
    VISITOR_EVENTS,
    VISITOR_TODOS,
    _heading,
    _visitor_event,
    _weekday,
    _workday,
    desk,
    desk_day,
    shift_list,
    start_here,
    team_day,
    visitor_day,
)
from .documents import DOC_FOLDERS, doccraft
from .historian import (
    BACKFILL_HOURS,
    BACKFILL_WAIT,
    CALC_SIGNALS,
    IMPORT_FILE,
    IMPORT_TAGS,
    LAB_DAYS,
    LAB_EVERY_HOURS,
    LAB_SOURCE,
    LAB_TAGS,
    SOURCE_FIELDS,
    histcraft,
    histcraft_calc,
    histcraft_import,
    histcraft_lab,
    import_csv,
    lab_csv,
)
from .links import (
    GUIDE_PAGES,
    NAMED,
    PAGES,
    Links,
    _checklist,
    _doc,
    _mention,
    _named,
    _para,
    guide_links,
    story_links,
)
from .models import (
    CALIBRATION_HOURS,
    MODEL_FMU,
    MODEL_FMU_LABEL,
    MODEL_OPTIMIZATION,
    MODEL_PLANT_LABEL,
    MODEL_RUNS,
    MODEL_STUDIES,
    PLANT_LOOP,
    PLANT_LOOP_PARAMETERS,
    _model_run,
    _model_study,
    _plant_run,
    _settings,
    _signal_of,
    modelcraft,
)
from .past import (
    PAST_ACTIONS,
    PAST_CONVERSATIONS,
    VISITOR_ALARMS,
    VISITOR_APP_NOTICES,
    VISITOR_UNREAD,
    _past,
    _relink,
    _workspace,
    past,
    visitor_alarms,
    visitor_unread,
)
from .people import CAST, GROUPS, RETIRED_SPECIALIST, _member, groups, people, retire_specialist
from .plant import PLANT, PLANT_RECORD, _short, archive_signals, name_the_plant, plant_map
from .view import (
    CONTROL_ROOM,
    FURNACE_AREA,
    INSTRUMENTATION,
    LOOP_DETAIL,
    MODEL_DEVIATION,
    OPERATION,
    OVERVIEW,
    _folders,
    _kpi,
    _note,
    _on,
    _result_kpi,
    _scatter,
    _trend,
    dashcraft,
)
from .view_displays import (
    DIAGRAMS_FOLDER,
    OLD_DIAGRAMS,
    RENAMED_TEST_TREND,
    TEST_TREND_NAMES,
    VIEW_TRENDS,
    _diagram_specs,
    _loop_lines,
    view_diagrams,
    view_trends,
)
from .view_reports import (
    ALARM_EVENTS,
    FINDINGS,
    HEALTH_SCALE,
    RAISED,
    REPORTS,
    RETIRED_REPORTS,
    SENSOR_LOOPS,
    U100_LEVELS,
    U100_LOOPS,
    VALVE_LOOPS,
    WATCHED_LOOPS,
    _card,
    _events,
    _health,
    _pvs,
    _ranked,
    _ranking,
    _text,
    view_reports,
)

# Every name the seed had when it was one module (tests and the CLI import them from here).
__all__ = [
    "_apps_from_env",
    "_card",
    "_checklist",
    "_day",
    "_decode",
    "_demo_map",
    "_detail",
    "_diagram_specs",
    "_doc",
    "_event",
    "_events",
    "_folders",
    "_heading",
    "_health",
    "_ident",
    "_InsidePolicy",
    "_iso",
    "_items",
    "_kpi",
    "_loop_lines",
    "_member",
    "_mention",
    "_model_run",
    "_model_study",
    "_named",
    "_node",
    "_note",
    "_on",
    "_para",
    "_password",
    "_past",
    "_plant_run",
    "_pressure_archive",
    "_pressure_limit",
    "_pvs",
    "_ranked",
    "_ranking",
    "_relink",
    "_result_kpi",
    "_scatter",
    "_settings",
    "_short",
    "_signal_of",
    "_signals_of",
    "_simple",
    "_STARTED",
    "_text",
    "_trend",
    "_visitor_event",
    "_visitor_password",
    "_weekday",
    "_wire",
    "_workday",
    "_workspace",
    "actions",
    "ALARM_EVENTS",
    "ALARM_OPERATOR",
    "ALARM_PHILOSOPHY",
    "ALARM_REPLAY_HOURS",
    "ALARM_RULES",
    "ALARM_SILENCE",
    "alarmcraft",
    "archive_signals",
    "assistant_and_notebooks",
    "ASSISTANT_CHATS",
    "BACKFILL_HOURS",
    "BACKFILL_WAIT",
    "CALC_SIGNALS",
    "CALIBRATION_HOURS",
    "CAST",
    "chat_sources",
    "CONTROL_ROOM",
    "CONVERSATIONS",
    "conversations",
    "CRITICALITY",
    "dashcraft",
    "DAY_SHIFT",
    "DEMO_ANSWER",
    "DEMO_MAP",
    "desk",
    "desk_day",
    "DIAGRAMS_FOLDER",
    "DOC_FOLDERS",
    "doccraft",
    "FINDINGS",
    "follow_ups",
    "FURNACE_AREA",
    "GROUPS",
    "groups",
    "guide_links",
    "GUIDE_PAGES",
    "HEALTH_SCALE",
    "histcraft",
    "histcraft_calc",
    "histcraft_import",
    "histcraft_lab",
    "Http",
    "import_csv",
    "IMPORT_FILE",
    "IMPORT_TAGS",
    "INSTRUMENTATION",
    "INSTRUMENTS",
    "IT_ACTIONS",
    "lab_csv",
    "LAB_DAYS",
    "LAB_EVERY_HOURS",
    "LAB_SOURCE",
    "LAB_TAGS",
    "link_models",
    "linkcraft",
    "Links",
    "log",
    "LOOP_DETAIL",
    "main",
    "MODEL_DEVIATION",
    "MODEL_FMU",
    "MODEL_FMU_LABEL",
    "MODEL_OPTIMIZATION",
    "MODEL_PLANT_LABEL",
    "MODEL_RUNS",
    "MODEL_STUDIES",
    "modelcraft",
    "name_the_plant",
    "NAMED",
    "NOTEBOOKS",
    "OLD_DIAGRAMS",
    "ON_CALL",
    "OPEN_ACTIONS",
    "OPERATION",
    "OVERVIEW",
    "PAGES",
    "past",
    "PAST_ACTIONS",
    "PAST_CONVERSATIONS",
    "people",
    "PLANT",
    "PLANT_LOOP",
    "PLANT_LOOP_PARAMETERS",
    "plant_map",
    "PLANT_RECORD",
    "PLANT_ZONE",
    "PRESSURE_LOOP",
    "PRESSURE_QUANTILE",
    "PROCESS",
    "RAISED",
    "RENAMED_TEST_TREND",
    "REPORTS",
    "retire_specialist",
    "RETIRED_REPORTS",
    "RETIRED_SPECIALIST",
    "run",
    "SATURATION_CODE",
    "SATURATION_DIAGRAM",
    "SeedError",
    "SENSOR_LOOPS",
    "SHIFT_LIST",
    "shift_list",
    "SHIFT_TODOS",
    "SOURCE_FIELDS",
    "START_HERE",
    "start_here",
    "STICTION_LOOPS",
    "story_links",
    "Suite",
    "SUPERVISOR",
    "SURGE_LEVELS",
    "TEAM_DAY",
    "team_day",
    "TEST_TREND_NAMES",
    "TO_COORDINATOR",
    "TOUR",
    "U100",
    "U100_LEVELS",
    "U100_LOOPS",
    "U200",
    "VALVE_LOOPS",
    "VALVE_NOTE",
    "VALVE_PLAN",
    "VALVE_STEPS",
    "view_diagrams",
    "view_reports",
    "VIEW_TRENDS",
    "view_trends",
    "VISITOR",
    "VISITOR_ALARMS",
    "visitor_alarms",
    "VISITOR_APP_NOTICES",
    "visitor_day",
    "VISITOR_EVENTS",
    "VISITOR_TODOS",
    "VISITOR_UNREAD",
    "visitor_unread",
    "wait_until",
    "WATCHED_LOOPS",
]


def run(suite: Suite) -> int:
    log(f"PlantCraft at {suite.processcraft}")
    admin = wait_until(
        "PlantCraft",
        lambda: suite.session(suite.admin, suite.password),
        suite.wait,
    )
    plant_map(admin, suite)
    archive_signals(admin, suite)
    # Every app's client now, on this thread: the admin session is not shared across threads.
    clients = {app_id: suite.app(admin, app_id) for app_id in suite.apps}
    platform = Http(suite.processcraft, token=admin.post("/api/v1/auth/token")["token"])
    failed: list[str] = []
    cast_ready = threading.Event()

    def step(app_id: str, work: Any) -> None:
        client = clients.get(app_id)
        if client is None:
            log(f"{app_id} is not installed: skipped")
            return
        try:
            work(client)
        except SeedError as error:
            failed.append(app_id)
            log(f"WARNING {app_id}: {error}")

    def data_chain() -> None:
        """The plant's data, which waits on long jobs (the Historian's 48 h backfill, Analytics'
        rounds, the alarms' replay): on its own thread, beside the people, View and Documents,
        which do not read it."""

        step(
            "histcraft",
            lambda client: (
                histcraft(client, suite),
                histcraft_lab(client),
                histcraft_import(client),
                histcraft_calc(client),
            ),
        )
        step("linkcraft", lambda client: linkcraft(client, suite))
        step("linkcraft", lambda client: link_models(client, suite))
        # Alarm rules and models name the cast and its groups.
        cast_ready.wait()
        step("alarmcraft", lambda client: alarmcraft(client, suite))
        step(
            "modelcraft",
            lambda client: modelcraft(client, suite, clients.get("linkcraft"), platform),
        )

    crashed: list[BaseException] = []

    def guarded() -> None:
        try:
            data_chain()
        except BaseException as error:  # noqa: BLE001 - raised again on the main thread
            crashed.append(error)
        finally:
            cast_ready.set()

    data = threading.Thread(target=guarded, name="demo-data", daemon=True)
    data.start()
    try:
        passwords = people(admin, suite)
        groups(admin, suite.admin)
        workspace = _workspace()
        retire_specialist(admin, workspace)
    finally:
        cast_ready.set()
    step("dashcraft", dashcraft)
    step("dashcraft", view_reports)
    step("dashcraft", view_trends)
    step("dashcraft", lambda client: view_diagrams(client, suite))
    step("doccraft", lambda client: doccraft(client, suite))
    data.join()
    if crashed:
        raise crashed[0]
    # What the team wrote, last: it links what the apps now hold (Links).
    links = story_links(suite, admin)
    if workspace is None:
        log("PlantCraft's past skipped: run the seed inside the PlantCraft container")
    else:
        written = past(workspace, suite.admin, links=links)
        log(
            f"PlantCraft's past: {written['actions']} actions and "
            f"{written['conversations']} conversations of the last three weeks"
        )
        made = assistant_and_notebooks(workspace, admin, suite.admin, links)
        log(f"Notifications: {visitor_alarms(workspace)} from the apps for the visitor")
        log(f"Desk: {made['chats']} assistant chats, {made['notebooks']} notebooks of loop data")
    started = conversations(suite, passwords, links, workspace)
    actions(suite, passwords, links)
    follow_ups(started, links)
    if workspace is not None:
        chat_sources(workspace, links)
    desk(suite, passwords, workspace, links)
    team_day(suite, passwords)
    if workspace is not None:
        log(f"Messages: {visitor_unread(workspace)} unread for the visitor")
        log(f"guides by role: {guide_links(workspace, suite, admin, links)} pages they open")
    log(f"links: {len(links.refs)} documents, dashboards, reports, chats, actions and talks")
    log(
        f"done. The read-only visitor account is '{VISITOR}' (the sign-in page offers it"
        " only on a public demo, install.sh --public-demo)"
        + (f"; failed: {', '.join(failed)}" if failed else "")
    )
    return 1 if failed else 0


def _apps_from_env(default_host: bool) -> dict[str, str]:
    """Where each app answers: the compose service names, or PLANTCRAFT_DEMO_<APP>_URL."""

    services = {
        "linkcraft": "http://linkcraft:8140/link",
        "dashcraft": "http://dashcraft:8080/dash",
        "histcraft": "http://histcraft:8100/hist",
        "alarmcraft": "http://alarmcraft:8110/alarm",
        "modelcraft": "http://modelcraft:8130/model",
        "doccraft": "http://doccraft:8150/doc",
    }
    installed = {
        entry.split("=", 1)[0].strip()
        for entry in os.environ.get("PLANTCRAFT_APPS", "").split(",")
        if "=" in entry
    }
    apps = {}
    for app_id, url in services.items():
        override = os.environ.get(f"PLANTCRAFT_DEMO_{app_id.upper()}_URL")
        if override:
            apps[app_id] = override
        elif app_id in installed and default_host:
            apps[app_id] = url
    return apps


def _visitor_password() -> str:
    """The visitor's password as PlantCraft reads it (``plantcraft.auth.public_demo``): the
    environment variable, else the secret file ``install.sh`` writes (``data/public-demo-password``)."""

    password = os.environ.get("PLANTCRAFT_PUBLIC_DEMO_PASSWORD", "").strip()
    file = os.environ.get("PLANTCRAFT_PUBLIC_DEMO_PASSWORD_FILE", "").strip()
    if not password and file and Path(file).is_file():
        password = Path(file).read_text(encoding="utf-8").strip()
    return password


def _password(args: argparse.Namespace) -> str:
    if args.password_file:
        return Path(args.password_file).read_text(encoding="utf-8").strip()
    password = os.environ.get("PLANTCRAFT_PASSWORD") or os.environ.get(
        "PLANTCRAFT_BASIC_AUTH_PASSWORD", ""
    )
    file = os.environ.get("PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE")
    if not password and file and Path(file).is_file():
        password = Path(file).read_text(encoding="utf-8").strip()
    if not password:
        raise SeedError("no administrator password: --password-file or PLANTCRAFT_PASSWORD")
    return password


def _demo_map(args: argparse.Namespace) -> Path:
    candidates = [args.map] if args.map else []
    here = Path(__file__).resolve().parents[2]
    candidates += [here / "deploy" / "demo" / DEMO_MAP, Path("/app/deploy/demo") / DEMO_MAP]
    for path in candidates:
        if path and Path(path).is_file():
            return Path(path)
    raise SeedError(f"{DEMO_MAP} not found (--map)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plantcraft demo seed",
        description="Fill a fresh installation with the Simulator demo story (idempotent).",
    )
    parser.add_argument(
        "--url", default=os.environ.get("PLANTCRAFT_DEMO_URL", "http://127.0.0.1:8060")
    )
    parser.add_argument(
        "--admin", default=os.environ.get("PLANTCRAFT_BASIC_AUTH_USERNAME", "admin")
    )
    parser.add_argument("--password-file")
    parser.add_argument(
        "--visitor-password",
        default=_visitor_password() or "plantcraft-demo",
        help="Password of the read-only visitor account 'demo'.",
    )
    parser.add_argument("--map", type=Path)
    parser.add_argument("--wait", type=float, default=600.0, help="Seconds to wait for each app.")
    parser.add_argument(
        "--app",
        action="append",
        default=[],
        metavar="ID=URL",
        help="Where an app answers, e.g. linkcraft=http://127.0.0.1:8140/link (repeatable).",
    )
    args = parser.parse_args(argv)
    try:
        apps = _apps_from_env(default_host=not args.app)
        for entry in args.app:
            app_id, _, url = entry.partition("=")
            apps[app_id.strip()] = url.strip()
        suite = Suite(
            processcraft=args.url,
            apps=apps,
            admin=args.admin,
            password=_password(args),
            visitor_password=args.visitor_password,
            demo_map=_demo_map(args),
            wait=args.wait,
        )
        return run(suite)
    except SeedError as error:
        print(f"[demo] ERROR: {error}", file=sys.stderr)
        return 2
