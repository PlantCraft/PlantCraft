"""The demo story's past: weeks of actions and conversations, stamped when they happened, once."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from plantcraft.demo_seed import CAST, PAST_ACTIONS, PAST_CONVERSATIONS, VISITOR, past
from plantcraft.platform.workspace import Workspace


def _workspace(tmp_path) -> Workspace:
    workspace = Workspace(tmp_path / "workspace.sqlite3")
    for person in [*CAST, {"username": "admin", "display_name": "Admin", "role": "Admin"}]:
        workspace.users.upsert_user(person["username"], person["display_name"], person["role"])
    workspace.users.upsert_user(VISITOR, "Demo visitor", "Visitor")
    return workspace


def test_the_past_is_written_once_with_its_own_dates(tmp_path):
    workspace = _workspace(tmp_path)
    now = datetime.now().astimezone().replace(microsecond=0)

    assert past(workspace, "admin", now=now) == {
        "actions": len(PAST_ACTIONS),
        "conversations": len(PAST_CONVERSATIONS),
    }
    assert past(workspace, "admin", now=now) == {"actions": 0, "conversations": 0}

    actions = {item["title"]: item for item in workspace.actions.list()}
    assert len(actions) == len(PAST_ACTIONS)
    fixed = actions["Replace the FIC-1102 valve positioner"]
    assert fixed["status"] == "done" and fixed["owner"] == "carlos.menezes"
    created = datetime.fromisoformat(fixed["created_at"])
    completed = datetime.fromisoformat(fixed["completed_at"])
    assert now - timedelta(days=20) < created < completed < now - timedelta(days=14)
    history = workspace.actions.history(fixed["action_id"])
    assert [entry["kind"] for entry in history].count("comment") == 3
    assert {item["status"] for item in actions.values()} >= {
        "done",
        "cancelled",
        "blocked",
        "in_progress",
        "open",
    }

    listed = workspace.messages.list_for(VISITOR)
    titles = [item["title"] for item in listed]
    assert sorted(titles) == sorted(item["title"] for item in PAST_CONVERSATIONS)
    # Newest talk first.
    assert titles.index("Dashboard for the control room") < titles.index("Weekly loop review")
    assert workspace.messages.unread_total(VISITOR) == 0
    review = workspace.messages.messages(listed[0]["conversation_id"], limit=50)
    assert all(datetime.fromisoformat(item["created_at"]) < now for item in review)


def test_the_visitor_takes_part_and_alarms_reach_them(tmp_path):
    from plantcraft.demo_seed import VISITOR_ALARMS, VISITOR_APP_NOTICES, visitor_alarms
    from plantcraft.notify import NotificationStore

    workspace = _workspace(tmp_path)
    now = datetime.now().astimezone().replace(microsecond=0)
    past(workspace, "admin", now=now)
    review = next(
        item
        for item in workspace.messages.list_for(VISITOR)
        if item["title"] == "Weekly loop review"
    )
    authors = [item["author"] for item in workspace.messages.messages(review["conversation_id"])]
    assert VISITOR in authors

    total = len(VISITOR_ALARMS) + len(VISITOR_APP_NOTICES)
    assert visitor_alarms(workspace, now=now) == total
    assert visitor_alarms(workspace, now=now) == 0
    notices = workspace.messages.notices_for(VISITOR, since="2000-01-01T00:00:00Z")
    assert len(notices) == total
    categories = [item["meta"]["category"] for item in notices]
    # Mostly alarms, then the other apps' runs and reports.
    assert categories.count("alarm") == len(VISITOR_ALARMS) > total / 2
    assert set(categories) == {"alarm", "run", "info"}
    assert all(datetime.fromisoformat(item["created_at"]) < now for item in notices)
    # Each app's notifications land in the conversation its own notifications use.
    threads = NotificationStore(workspace.db)
    for item in notices:
        assert item["conversation_id"] == threads.thread(item["meta"]["app"], VISITOR)


def test_the_lab_csv_is_a_month_of_samples_every_four_hours():
    from plantcraft.demo_seed import LAB_TAGS, lab_csv

    rows = lab_csv(now=1_792_000_000).decode().splitlines()
    assert rows[0].split(",")[1:] == [tag for tag, *_ in LAB_TAGS]
    assert len(rows) == 1 + 30 * 6
    assert rows[-1].startswith("2026-10-14T") and rows[-1].split(",")[0].endswith("Z")
    assert lab_csv(now=1_792_000_000) == lab_csv(now=1_792_000_000)


def test_the_pressure_alarm_waits_for_an_archive(tmp_path):
    # Alarms suggests no limits since round 11: without an archive the seed says so
    from plantcraft import demo_seed

    class NoArchive(demo_seed.Suite):
        def session(self, username, password):
            raise demo_seed.SeedError("no archive")

    suite = NoArchive("http://test", {}, "admin", "pw", "pw", tmp_path, wait=0.1)
    with pytest.raises(demo_seed.SeedError, match="PIC-1202's archive"):
        demo_seed._pressure_limit(demo_seed.Http("http://alarms"), suite)


def test_the_pressure_alarm_limit_comes_from_the_archived_minutes(tmp_path):
    # the replay reads one value a minute: the limit is one those minutes cross 2% of the time
    from plantcraft import demo_seed

    values = [50.0 + (i % 100) / 10 for i in range(2880)]  # 50.0 .. 59.9

    class Admin(demo_seed.Http):
        def call(self, method, path, body=None, *, ok=(), raw=None, content_type=""):
            if path == "/api/assets/PIC-1202":
                return 200, {"signals": [{"role": "pv", "source_id": "sim", "signal_id": "P"}]}
            assert path == "/api/v1/series" and body["signals"] == ["sim:P"] and body["step"] == 60
            return 200, {"series": [{"signal": "sim:P", "t": [], "v": [*values, None]}]}

    class Archived(demo_seed.Suite):
        def session(self, username, password):
            return Admin("http://test")

    suite = Archived("http://test", {}, "admin", "pw", "pw", tmp_path, wait=1.0)
    limit, deadband = demo_seed._pressure_limit(demo_seed.Http("http://alarms"), suite)
    assert limit == 59.7 and sum(value > limit for value in values) > 0
    assert deadband == 0.625


def test_the_team_s_assistant_chats_and_notebooks_are_written_once(tmp_path):
    from plantcraft import demo_seed
    from plantcraft.assistant_chat import ChatStore

    workspace = _workspace(tmp_path)

    class Admin(demo_seed.Http):
        def get(self, path, **kw):
            loop = path.rsplit("/", 1)[-1]
            return {
                "signals": [
                    {"role": role, "source_id": "plantcraft", "signal_id": f"{loop}.{role.upper()}"}
                    for role in ("pv", "sp", "op")
                ]
            }

    made = demo_seed.assistant_and_notebooks(workspace, Admin("http://test"), "admin")
    assert made == {"chats": len(demo_seed.ASSISTANT_CHATS), "notebooks": len(demo_seed.NOTEBOOKS)}
    assert demo_seed.assistant_and_notebooks(workspace, Admin("http://test"), "admin") == {
        "chats": 0,
        "notebooks": 0,
    }
    chats = ChatStore(workspace.db)
    shared = chats.shared_with(demo_seed.VISITOR, {"everyone"})
    assert {item["username"] for item in shared} == {
        spec["owner"] for spec in demo_seed.ASSISTANT_CHATS if spec["shared"]
    }
    assert len(shared) == sum(spec["shared"] for spec in demo_seed.ASSISTANT_CHATS)
    mine = chats.chats(demo_seed.VISITOR)
    answers = [chats.messages(item["chat_id"])[-1] for item in mine]
    assert all(answer["role"] == "assistant" for answer in answers)
    assert any("FIC-1003" in answer["text"] for answer in answers)
    assert workspace.notebooks.enabled()
    notebook = workspace.notebooks.list(demo_seed.VISITOR)[0]
    assert notebook["name"].startswith("FIC-1003 sticky valve")


def test_the_start_here_note_is_pinned_for_the_visitor_once(tmp_path):
    from plantcraft import demo_seed
    from plantcraft.desk import DeskStore

    store = DeskStore(_workspace(tmp_path).db)
    demo_seed.start_here(store, "admin")
    demo_seed.start_here(store, "admin")
    notes = store.notes(demo_seed.VISITOR, [])
    assert [item["title"] for item in notes] == [demo_seed.START_HERE]
    assert notes[0]["pinned"] and "FIC-1003" in store.note(notes[0]["note_id"])["body_text"]


def test_links_turn_names_into_mentions_and_markdown_links():
    from plantcraft.demo_seed import Links

    links = Links({"DOC-MH-001": "doc:7", "Plant overview": "dashboard:d1", "A chat": "chat:3"})
    assert links.fill("See {{DOC-MH-001}} and {{A chat|this chat}}; {{Gone}}.") == (
        "See #[DOC-MH-001](doc:7) and #[this chat](chat:3); Gone."
    )
    assert links.fill("{{asset:FIC-1003}}") == "#[FIC-1003](asset:FIC-1003)"
    assert links.markdown("{{DOC-MH-001}}, {{Plant overview}}, {{A chat}}") == (
        "[DOC-MH-001](/doc/documents/7), [Plant overview](/dash/dashboards/d1), **A chat**"
    )
    assert links.of("asset:FIC-1003", "Gone", "DOC-MH-001", "DOC-MH-001") == [
        "asset:FIC-1003",
        "doc:7",
    ]
    parts, plain = links.rich("Follow {{A chat|the chat}} on {{asset:FIC-1003}}.")
    assert parts[1] == {"type": "mention", "attrs": {"id": "chat:3", "label": "the chat"}}
    assert plain == "Follow #the chat on #FIC-1003."


def test_the_past_links_the_documents_and_the_chats_cite_the_actions(tmp_path):
    from plantcraft import demo_seed
    from plantcraft.assistant_chat import ChatStore

    workspace = _workspace(tmp_path)
    links = demo_seed.Links({"DOC-MH-001": "doc:9", "PRO-U200-012": "doc:12"})
    past(workspace, "admin", links=links)

    actions = {item["title"]: item for item in workspace.actions.list()}
    fixed = actions["Replace the FIC-1102 valve positioner"]
    assert {"asset:FIC-1102", "doc:9", "doc:12"} <= set(fixed["refs"])
    comments = [e["text"] for e in workspace.actions.history(fixed["action_id"])]
    assert any("#[PRO-U200-012](doc:12)" in text for text in comments)
    assert links.refs["Weekly loop review"].startswith("conversation:")
    review = workspace.messages.messages(int(links.refs["Weekly loop review"].split(":")[1]))
    assert "(action:" in review[0]["text"]

    class Admin(demo_seed.Http):
        def get(self, path, **kw):
            return {"signals": []}

    demo_seed.assistant_and_notebooks(workspace, Admin("http://test"), "admin", links)
    title = "Why does FIC-1003 cycle?"
    links.add("Inspect the FIC-1003 recycle valve for stiction", "action:42")
    demo_seed.chat_sources(workspace, links)
    chats = ChatStore(workspace.db)
    answer = chats.messages(int(links.refs[title].split(":")[1]))[-1]
    assert "[DOC-MH-001](/doc/documents/9)" in answer["text"]
    assert {"asset:FIC-1003", "doc:9", "doc:12", "action:42"} <= set(answer["refs"])


def test_a_story_seeded_before_the_links_gets_them_when_seeded_again(tmp_path):
    from plantcraft import demo_seed
    from plantcraft.desk import DeskStore

    workspace = _workspace(tmp_path)
    past(workspace, "admin")
    fixed = {item["title"]: item for item in workspace.actions.list()}[
        "Replace the FIC-1102 valve positioner"
    ]
    assert fixed["refs"] == ["asset:FIC-1102"]
    store = DeskStore(workspace.db)
    demo_seed.start_here(store, "admin")

    links = demo_seed.Links({"DOC-MH-001": "doc:9", "PRO-U200-012": "doc:12"})
    assert past(workspace, "admin", links=links) == {"actions": 0, "conversations": 0}
    again = workspace.actions.get(fixed["action_id"])
    assert again["refs"] == ["asset:FIC-1102", "doc:12", "doc:9"]
    assert again["status"] == "done" and again["updated_at"] == fixed["created_at"]
    demo_seed.start_here(store, "admin", links)
    notes = store.notes(demo_seed.VISITOR, [])
    assert len(notes) == 1 and "#PRO-U200-012" in store.note(notes[0]["note_id"])["body_text"]


def test_the_guides_open_the_pages_of_the_story_by_name(tmp_path):
    from plantcraft import demo_seed

    workspace = _workspace(tmp_path)
    links = demo_seed.Links({"DOC-MH-001": "doc:9", "Plant overview": "dashboard:d 1"})
    past(workspace, "admin", links=links)

    class App(demo_seed.Http):
        def call(self, method, path, body=None, **kw):
            if path == "/api/diagrams":
                return 200, [{"name": "Riverbend plant", "diagram_id": "g7"}]
            raise demo_seed.SeedError("Models is not answering")

    class Suite:
        admin = "admin"

        def app(self, session, app_id):
            return App("http://test")

    written = demo_seed.guide_links(workspace, Suite(), None, links)
    pages = workspace.demo_visits.guide_links()
    assert written == len(pages)
    assert pages["DOC-MH-001"] == "/doc/documents/9"
    assert pages["Plant overview"] == "/dash/dashboards/d%201"
    assert pages["Riverbend plant"] == "/dash/diagrams/g7"
    assert pages["Weekly loop review"].startswith("/messages/")
    assert pages["Replace the FIC-1102 valve positioner"].startswith("/actions/")


def test_the_retired_specialist_leaves_with_its_conversation(tmp_path):
    from plantcraft.demo_seed import RETIRED_SPECIALIST, retire_specialist

    workspace = _workspace(tmp_path)
    workspace.users.upsert_user(RETIRED_SPECIALIST, "Valve specialist", "Specialist", kind="system")
    old = workspace.messages.start(
        "ana.lima", ["ana.lima", RETIRED_SPECIALIST, VISITOR], title="Old"
    )
    kept = workspace.messages.start("ana.lima", ["ana.lima", VISITOR], title="Kept")

    class Admin:
        calls: list = []

        def call(self, method, path, body=None, *, ok=()):
            self.calls.append((method, path))
            return 404, {}

    admin = Admin()
    retire_specialist(admin, workspace)
    assert admin.calls == [("DELETE", f"/api/specialists/{RETIRED_SPECIALIST}")]
    assert workspace.messages.get(old["conversation_id"]) is None
    assert workspace.messages.get(kept["conversation_id"]) is not None
