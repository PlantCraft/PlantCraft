"""The setup guide: the robot beside the screen that walks an administrator through a new
installation, one step at a time (docs/setup-guide.md).

Each step knows by itself whether it is done, from the installation's own state (a language
model answers, a source is connected, the asset tree has assets, someone else can sign in), so
the guide moves on as soon as the person does the step anywhere, with the robot or on the
step's own page. A step the guide cannot see (the documents, the email server) is done when the
person says so. The person may skip any step and come back to it.

The robot talks through the assistant: each step has a work on the page ``processcraft:setup-guide``
(``assistant_works/platform.py``) that knows the step, asks the person what it needs and, where a
step writes something, proposes it as a card the person applies with one click (the model never
writes). Before a language model is connected the robot cannot talk, so its first step points
to Settings › Language models and the rest wait.

What the guide keeps: the steps marked done or skipped, for the installation (a preference row of
the reserved name ``@installation``, which no person can have), and whether each administrator
hid the robot (their own preference).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from plantcraft.i18n import t

LOGGER = logging.getLogger(__name__)

KEY = "setup-guide"
# A preference row of the installation, not a person's: usernames are lowercase letters,
# digits, dots, dashes and underscores (auth/users.py), so "@" never names one.
INSTALLATION = "@installation"
MARKS = ("done", "skipped")
DOCUMENTS_APP = "doccraft"
ANALYTICS_APP = "linkcraft"
PLANT_READS = {"tool:show_chart", "tool:read_series", "tool:signal_value", "tool:latest_results"}


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    # One line: what the step does, as the robot says it.
    summary: str
    # Why it matters, in one or two sentences.
    why: str
    # The page where the step is done by hand.
    page: str
    page_label: str
    optional: bool = False
    # The guide sees by itself when it is done (False: the person says so).
    seen: bool = True
    # The app the step needs; left out when that app is not installed.
    app: str | None = None


def steps() -> list[Step]:
    """The steps, in the order a new plant takes them (translated as asked)."""

    return [
        Step(
            "model",
            t("Connect a language model"),
            t("Connect the language model I think with, so I can talk with you."),
            t(
                "I am the assistant: without a model I can only point the way. A model on your own "
                "machines (Ollama, vLLM) or a cloud one with your company's key both work."
            ),
            "/setup/language-model",
            t("Language models"),
        ),
        Step(
            "basics",
            t("The basics"),
            t("The plant's time zone and the language you read."),
            t(
                "Every time on every screen and schedule is shown in the plant's time zone, so it "
                "comes first."
            ),
            "/setup/installation",
            t("Installation"),
        ),
        Step(
            "connection",
            t("Connect the plant's data"),
            t("Connect PlantCraft to your OPC UA server, PI Web API or a file, read only."),
            t(
                "Everything else reads the plant from here. PlantCraft only reads: it never writes "
                "to the control system."
            ),
            "/data",
            t("Sources"),
        ),
        Step(
            "documents",
            t("Add the plant's documents"),
            t("P&IDs, loop lists, data sheets and manuals, so I know where each tag sits."),
            t(
                "With the documents, the asset tree comes out with each loop in its unit and area, "
                "and I can cite them when I answer."
            ),
            "/doc/",
            t("Documents"),
            optional=True,
            seen=False,
            app=DOCUMENTS_APP,
        ),
        Step(
            "assets",
            t("Build the asset tree"),
            t("Turn the source's tags into loops, instruments and equipment, and review them."),
            t(
                "The asset tree is how every app finds the plant: the loops Analytics watches, the "
                "signals an alarm uses, the units a dashboard shows."
            ),
            "/asset-import",
            t("Assets › Import"),
        ),
        Step(
            "start",
            t("Let the apps start"),
            t("Each app takes its first step on the new assets: collect, monitor, draft alarms."),
            t(
                "Nothing is switched on without review: drafted alarms stay off and dashboards "
                "are drafts until you look at them."
            ),
            "/asset-import",
            t("Assets › Import"),
        ),
        Step(
            "people",
            t("Invite your team"),
            t("Add the people who will use PlantCraft, each with the access they need."),
            t(
                "Operators, engineers and managers see the same plant with different access. You "
                "can also connect your company's sign-in later."
            ),
            "/users",
            t("Users"),
        ),
        Step(
            "email",
            t("Send notifications by email"),
            t("Your company's mail server, so alarms and reports also reach people's inboxes."),
            t("Optional: notifications always reach Messages in PlantCraft."),
            "/setup/email",
            t("Email"),
            optional=True,
            seen=False,
        ),
    ]


def step_ids() -> list[str]:
    return [step.id for step in steps()]


# What the guide keeps ---------------------------------------------------------------------


def marks(rt: Any) -> dict[str, str]:
    """The steps the person marked: ``{step: "done" | "skipped"}``."""

    stored = rt.workspace.preferences.get(INSTALLATION, KEY)
    found = stored.get("marks") if isinstance(stored, dict) else None
    if not isinstance(found, dict):
        return {}
    known = set(step_ids())
    return {str(key): value for key, value in found.items() if key in known and value in MARKS}


def _stored(rt: Any) -> dict[str, Any]:
    stored = rt.workspace.preferences.get(INSTALLATION, KEY)
    return stored if isinstance(stored, dict) else {}


def mark(rt: Any, step: str, state: str | None, *, actor: str) -> None:
    """Mark ``step`` done or skipped; ``None`` takes the mark back."""

    stored = _stored(rt)
    found = dict(marks(rt))
    if state is None:
        found.pop(step, None)
    else:
        found[step] = state
    rt.workspace.preferences.put(INSTALLATION, KEY, {**stored, "marks": found})
    rt.workspace.audit.record(
        actor, "setup_guide.mark", f"setup-guide:{step}", {"state": state}, app_id="processcraft"
    )


def remember(rt: Any, **values: Any) -> None:
    """Keep small facts the guide learnt (the last connection test) with the installation's row."""

    stored = _stored(rt)
    rt.workspace.preferences.put(INSTALLATION, KEY, {**stored, **values})


def hidden(rt: Any, username: str) -> bool:
    from plantcraft.auth.public_demo import public_demo

    if public_demo() is not None:  # a public demo is set up already: no robot for its visits
        return True
    stored = rt.workspace.preferences.get(username, KEY)
    return bool(stored.get("hidden")) if isinstance(stored, dict) else False


def hide(rt: Any, username: str, value: bool) -> None:
    rt.workspace.preferences.put(username, KEY, {"hidden": bool(value)})


# What the installation shows -------------------------------------------------------------


def _model(rt: Any) -> dict[str, Any]:
    store = rt.specialist_chat.store
    allowed = bool(store.settings().get("allowed"))
    found = store.use_model("assistant") if allowed else None
    facts: dict[str, Any] = {"models_allowed": allowed}
    if found is not None:
        facts["model"] = found.get("label") or found.get("name") or ""
    return {"done": found is not None, "facts": facts}


def _basics(rt: Any, username: str) -> dict[str, Any]:
    from plantcraft.api.routers.installation import preferences
    from plantcraft.i18n import translations_on

    settings = rt.workspace.installation.settings()
    mine = preferences(rt, username)
    facts = {
        "time_zone": settings.get("time_zone"),
        "time_zone_chosen": bool(settings.get("chosen")),
        "time_zone_fixed_by_installer": bool(settings.get("locked")),
        "my_language": mine.get("language") or "",
        "languages": ["en", "pt-BR", "es"] if translations_on() else ["en"],
    }
    return {"done": bool(settings.get("chosen") or settings.get("locked")), "facts": facts}


def plant_sources(rt: Any, username: str) -> list[dict[str, Any]]:
    """The sources a person added (not the scenario's own, which an empty installation points at
    an empty file), with the collector's view of each."""

    from plantcraft.api.routers.data import list_sources

    try:
        listed = list_sources(username, rt)
    except Exception as exc:  # the Historian may be starting: the guide waits
        LOGGER.info("setup guide: the sources could not be listed: %s", exc)
        return []
    found = []
    for item in listed:
        if item.get("origin") == "scenario" and not item.get("configured_tags"):
            continue
        found.append(
            {
                "source_id": item.get("source_id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "endpoint": item.get("endpoint"),
                "enabled": item.get("enabled", True),
                "state": item.get("state"),
                "signals": item.get("configured_tags") or 0,
            }
        )
    return found


def _connected(source: dict[str, Any], tested: dict[str, Any]) -> bool:
    state = source.get("state") or {}
    if state.get("status") == "connected":
        return True
    last = tested.get(str(source.get("source_id")))
    return bool(isinstance(last, dict) and last.get("ok"))


def _connection(rt: Any, username: str) -> dict[str, Any]:
    sources = plant_sources(rt, username)
    tested = _stored(rt).get("tested") or {}
    tested = tested if isinstance(tested, dict) else {}
    connected = [item for item in sources if _connected(item, tested)]
    facts: dict[str, Any] = {
        "sources": [
            {
                "name": item["name"],
                "type": item["type"],
                "endpoint": item["endpoint"],
                "connected": _connected(item, tested),
                "detail": (item.get("state") or {}).get("detail")
                or (tested.get(str(item["source_id"])) or {}).get("message")
                or "",
            }
            for item in sources[:10]
        ],
    }
    return {"done": bool(connected), "facts": facts, "sources": sources}


def _assets(rt: Any) -> dict[str, Any]:
    counts = rt.workspace.assets.counts()
    total = sum(counts.values())
    # An empty installation holds only the plant's root.
    added = max(0, total - 1)
    facts = {"assets": added, "by_kind": counts}
    return {"done": added > 0, "facts": facts}


def _start(rt: Any) -> dict[str, Any]:
    from plantcraft.platform import assetfile

    found = assetfile.last_import(rt.platform)
    if found is None or found.get("undone_at") is not None:
        return {"done": False, "facts": {"import": None}}
    taken = {
        str(row.get("subject") or "")
        for row in rt.workspace.audit.list(limit=200, action="assets.start_step")
        if (row.get("detail") or {}).get("import_id") == found.get("import_id")
    }
    apps = {app.id for app in rt.suite_apps()}
    declared = [
        f"{row['app']}:{step['id']}"
        for row in rt.contributions.listing(list(apps))
        for step in (row.get("contributes") or {}).get("start") or []
    ]
    left = [key for key in declared if key not in taken]
    facts = {"import": found.get("import_id"), "taken": sorted(taken), "left": left}
    return {"done": bool(declared) and not left, "facts": facts}


def _people(rt: Any) -> dict[str, Any]:
    from plantcraft.auth.users import DEMO_USERS

    demo = {user["username"] for user in DEMO_USERS}
    # The demonstration team (a development run) is not the plant's.
    people = [
        user
        for user in rt.workspace.users.list_users(kind="person")
        if user["username"] not in demo
    ]
    facts = {"people": len(people)}
    return {"done": len(people) > 1, "facts": facts}


def status(rt: Any, username: str) -> dict[str, Any]:
    """Every step with its state (``done``, ``skipped``, ``current`` or ``todo``), the facts the
    robot and its work read, and which step comes now."""

    installed = {app.id for app in rt.suite_apps()}
    marked = marks(rt)
    checks = {
        "model": lambda: _model(rt),
        "basics": lambda: _basics(rt, username),
        "connection": lambda: _connection(rt, username),
        "assets": lambda: _assets(rt),
        "start": lambda: _start(rt),
        "people": lambda: _people(rt),
    }
    items: list[dict[str, Any]] = []
    current: str | None = None
    for step in steps():
        if step.app and step.app not in installed:
            continue
        seen = checks[step.id]() if step.id in checks else {"done": False, "facts": {}}
        mark_state = marked.get(step.id)
        if seen["done"] or mark_state == "done":
            state = "done"
        elif mark_state == "skipped":
            state = "skipped"
        elif current is None:
            state = "current"
            current = step.id
        else:
            state = "todo"
        item = {
            "id": step.id,
            "title": step.title,
            "summary": step.summary,
            "why": step.why,
            "page": step.page,
            "page_label": step.page_label,
            "optional": step.optional,
            "seen": step.seen,
            "state": state,
            "marked": mark_state,
            "facts": seen.get("facts") or {},
            "work": f"processcraft:guide-{step.id}",
        }
        if "sources" in seen:
            item["sources"] = seen["sources"]
        items.append(item)
    ready = items[0]["state"] == "done" if items and items[0]["id"] == "model" else True
    done = sum(1 for item in items if item["state"] == "done")
    found_missions = missions_status(rt, username, installed)
    return {
        "hidden": hidden(rt, username),
        "ready": ready,
        "current": current,
        "done": done,
        "total": len(items),
        "finished": current is None,
        "steps": items,
        "missions": found_missions,
        "missions_done": sum(1 for item in found_missions if item["done"]),
    }


# First missions: after the setup, the things that show what PlantCraft does ----------------


@dataclass(frozen=True)
class Mission:
    id: str
    title: str
    summary: str
    page: str
    page_label: str
    # Done when this person's audit log has this action (an app's, with its id, or PlantCraft's).
    app: str
    action: str
    # The app the mission needs; left out when it is not installed.
    needs: str | None = None


def missions() -> list[Mission]:
    """The first missions (owner, 2026-11-03: "configure your first Analytics, share your first
    dashboard, open your first notebook"), in the order they show the suite. Each is done once
    the person did it, anywhere: the guide reads their audit log."""

    return [
        Mission(
            "ask",
            t("Ask about your plant"),
            t("Ask the assistant how a loop or a signal behaved; it reads the plant and draws it."),
            "/assistant",
            t("Assistant"),
            "processcraft",
            "assistant.tool",
        ),
        Mission(
            "analytics",
            t("Run your first Analytics round"),
            t("See which loops perform poorly, which valves stick and which signals are bad."),
            "/link/results",
            "Analytics",
            ANALYTICS_APP,
            "round.started",
            needs=ANALYTICS_APP,
        ),
        Mission(
            "alarm",
            t("Switch on your first alarm"),
            t("Review one of the drafted alarm rules and switch it on."),
            "/alarm/rules",
            "Alarms",
            "alarmcraft",
            "rule.enabled",
            needs="alarmcraft",
        ),
        Mission(
            "dashboard",
            t("Share your first dashboard"),
            t(
                "Open a unit's dashboard and share it with a link, for a screen in the control room."
            ),
            "/dash/",
            "View",
            "dashcraft",
            "share.create",
            needs="dashcraft",
        ),
        Mission(
            "notebook",
            t("Open your first notebook"),
            t("Analyse the plant's data in Python, in the browser: nothing to install."),
            "/notebooks",
            t("Notebooks"),
            "processcraft",
            "notebooks.create",
        ),
    ]


def missions_status(rt: Any, username: str, installed: set[str]) -> list[dict[str, Any]]:
    found = []
    for mission in missions():
        if mission.needs and mission.needs not in installed:
            continue
        rows = rt.workspace.audit.list(
            limit=200 if mission.id == "ask" else 1,
            username=username,
            app_id=mission.app,
            action=mission.action,
        )
        if mission.id == "ask":
            # A question about the plant reads its history; the guide's own chats only read help.
            rows = [row for row in rows if row.get("subject") in PLANT_READS]
        done = bool(rows)
        found.append(
            {
                "id": mission.id,
                "title": mission.title,
                "summary": mission.summary,
                "page": mission.page,
                "page_label": mission.page_label,
                "done": done,
                "work": f"processcraft:mission-{mission.id}",
            }
        )
    return found
