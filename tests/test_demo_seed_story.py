"""The demo story stays the same story: the size of each of its tables, and what the steps that
write PlantCraft's own database leave there, row counts per table (``demo_seed_story.json``).

The file was written from the single-module seed before it became a package (2026-11-03), so
the split proved it changed nothing. A change to the story changes these counts on purpose:
write the file again with ``python tests/test_demo_seed_story.py`` and review its diff.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED = Path(__file__).with_name("demo_seed_story.json")
# A fixed "now" in the plant's past, so the dates the steps compute never depend on today.
NOW = datetime(2026, 10, 28, 15, 30, tzinfo=timezone.utc)

TABLES = (
    "ALARM_RULES",
    "ASSISTANT_CHATS",
    "CALC_SIGNALS",
    "CAST",
    "CONVERSATIONS",
    "CRITICALITY",
    "DOC_FOLDERS",
    "GROUPS",
    "IMPORT_TAGS",
    "IT_ACTIONS",
    "LAB_TAGS",
    "MODEL_RUNS",
    "MODEL_STUDIES",
    "NOTEBOOKS",
    "OLD_DIAGRAMS",
    "OPEN_ACTIONS",
    "PAST_ACTIONS",
    "PAST_CONVERSATIONS",
    "REPORTS",
    "RETIRED_REPORTS",
    "SHIFT_TODOS",
    "SOURCE_FIELDS",
    "STICTION_LOOPS",
    "SURGE_LEVELS",
    "TEAM_DAY",
    "TOUR",
    "VIEW_TRENDS",
    "VISITOR_ALARMS",
    "VISITOR_APP_NOTICES",
    "VISITOR_EVENTS",
    "VISITOR_TODOS",
)


def _tables() -> dict[str, int]:
    from plantcraft import demo_seed

    return {name: len(getattr(demo_seed, name)) for name in TABLES}


def _rows(folder: Path) -> dict[str, Any]:
    """PlantCraft's database after the seed's own steps on it (no app answers here)."""

    from plantcraft import demo_seed
    from plantcraft.desk import DeskStore
    from plantcraft.platform.workspace import Workspace

    workspace = Workspace(folder / "workspace.sqlite3")
    for person in [
        *demo_seed.CAST,
        {"username": "admin", "display_name": "Admin", "role": "Admin"},
    ]:
        workspace.users.upsert_user(person["username"], person["display_name"], person["role"])
    workspace.users.upsert_user(demo_seed.VISITOR, "Demo visitor", "Visitor")

    class Admin(demo_seed.Http):
        def get(self, path: str, **kw: Any) -> Any:
            loop = path.rsplit("/", 1)[-1]
            return {
                "signals": [
                    {"role": role, "source_id": "plantcraft", "signal_id": f"{loop}.{role.upper()}"}
                    for role in ("pv", "sp", "op")
                ]
            }

    links = demo_seed.Links({"DOC-MH-001": "doc:9", "PRO-U200-012": "doc:12"})
    written = {
        "past": demo_seed.past(workspace, "admin", now=NOW, links=links),
        "assistant": demo_seed.assistant_and_notebooks(
            workspace, Admin("http://t"), "admin", links
        ),
        "notifications": demo_seed.visitor_alarms(workspace, now=NOW),
    }
    demo_seed.chat_sources(workspace, links)
    demo_seed.start_here(DeskStore(workspace.db), "admin", links)
    written["unread"] = demo_seed.visitor_unread(workspace)
    written["links"] = len(links.refs)
    with sqlite3.connect(folder / "workspace.sqlite3") as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        counts = {
            name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in sorted(names)
        }
    written["rows"] = {name: count for name, count in counts.items() if count}
    return written


def _story(folder: Path) -> dict[str, Any]:
    return {"tables": _tables(), "workspace": _rows(folder)}


def test_the_story_and_what_it_writes_are_unchanged(tmp_path):
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert _story(tmp_path) == expected


def test_every_name_of_the_seed_is_still_importable():
    from plantcraft import demo_seed

    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    missing = [name for name in expected["tables"] if not hasattr(demo_seed, name)]
    assert not missing
    for name in demo_seed.__all__:
        assert hasattr(demo_seed, name), name


if __name__ == "__main__":
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory() as folder:
        story = _story(Path(folder))
    EXPECTED.write_text(json.dumps(story, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {EXPECTED}")
