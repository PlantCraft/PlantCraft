"""What a specialist may read: assets, actions, and what its apps published (read-only).

Every function here only reads. Results, runs and events come from the apps
through API v1; a specialist sees those of the apps in its profile, plus
PlantCraft's own (assets, people, actions). Its answer goes to the people of the conversation,
so it reads no more than they may: only the apps of its profile they all open, and only the
actions they all see (security review, 2026-10-26).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plantcraft.actions import OPEN_STATUSES
from plantcraft.i18n import t
from plantcraft.refs import parse_ref

# Events PlantCraft itself publishes (asset changes, actions): always readable.
OWN_SOURCES = {"platform", "processcraft"}
# Worst first when a specialist lists what needs attention.
STATUS_ORDER = {"bad": 0, "critical": 0, "problem": 0, "warning": 1, "attention": 1, "unknown": 2}


STATUS_WORDS = {"ok": "ok", "warning": "attention", "alarm": "alarm", "unknown": "unknown"}
RESULT_KINDS = {"loop_health": "Loop health", "signal_quality": "Signal quality"}


def result_kind(kind: str) -> str:
    """A result's kind in words: `loop_health` -> Loop health, a protocol output `out_valve` -> Valve."""

    if kind in RESULT_KINDS:
        return t(RESULT_KINDS[kind])
    words = kind.removeprefix("out_").replace("_", " ").replace(".", " ").strip()
    return words[:1].upper() + words[1:]


def _number(value: Any, digits: int = 0) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


class SpecialistFacts:
    def __init__(
        self,
        workspace: Any,
        apps: list[str] | set[str],
        app_names: dict[str, str],
        sees_action: Callable[[dict[str, Any]], bool] | None = None,
        sees_subject: Callable[[str], bool] | None = None,
    ):
        self.workspace = workspace
        self.apps = set(apps)
        self.app_names = app_names
        # Whether the people the answer goes to may read an action (None: every action).
        self.sees_action = sees_action or (lambda _action: True)
        # Whether an asset or signal is in their asset scope (None: the whole plant).
        self.sees_subject = sees_subject or (lambda _subject: True)

    def _hidden_event(self, event: dict[str, Any]) -> bool:
        kind, _, item_id = str(event.get("subject") or "").partition(":")
        if kind in {"asset", "signal"}:
            return not self.sees_subject(str(event["subject"]))
        if kind != "action":
            return False
        action = self.workspace.actions.get(int(item_id)) if item_id.isdigit() else None
        return action is None or not self.sees_action(action)

    def app_name(self, app: str) -> str:
        return self.app_names.get(app, app)

    # Objects -----------------------------------------------------------------

    def search_assets(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {"ref": f"asset:{item['asset_id']}", "name": item["name"], "kind": item["kind"]}
            for item in self.workspace.assets.search(
                text.strip(), limit=max(1, min(limit, 30)) * 10
            )
            if self.sees_subject(f"asset:{item['asset_id']}")
        ][: max(1, min(limit, 30))]

    def results(self, subject: str) -> list[dict[str, Any]]:
        if not self.apps or not self.sees_subject(subject):
            return []
        return [
            {**item, "app_name": self.app_name(item["app"])}
            for item in self.workspace.results.results(subjects=[subject])
            if item["app"] in self.apps
        ]

    def result_history(self, subject: str, limit: int = 30) -> list[dict[str, Any]]:
        if not self.sees_subject(subject):
            return []
        rows = self.workspace.results.history(subject, limit=500)
        return [item for item in rows if item["app"] in self.apps][-limit:]

    def events(self, ref: str, limit: int = 15) -> list[dict[str, Any]]:
        if not self.sees_subject(ref):
            return []
        allowed = self.apps | OWN_SOURCES
        return [
            {
                "at": item["at"],
                "kind": item["kind"],
                "source": item["source"],
                "subject": item["subject"],
                "summary": item["summary"],
            }
            for item in self.workspace.events.timeline(ref, limit=100)
            if item["source"] in allowed and not self._hidden_event(item)
        ][:limit]

    def actions(self, ref: str | None = None, *, open_only: bool = True) -> list[dict[str, Any]]:
        rows = self.workspace.actions.list(
            statuses=list(OPEN_STATUSES) if open_only else None, ref=ref, limit=30
        )
        return [
            {
                "ref": f"action:{item['action_id']}",
                "title": item["title"],
                "status": item["status"],
                "priority": item["priority"],
                "owner": item["owner_name"],
                "due_at": item["due_at"],
                "about": item["refs"],
            }
            for item in rows
            if self.sees_action(item)
        ]

    def asset(self, asset_id: str) -> dict[str, Any] | None:
        item = self.workspace.assets.get(asset_id)
        ref = f"asset:{asset_id}"
        if item is None or not self.sees_subject(ref):
            return None
        return {
            "ref": ref,
            "name": item["name"],
            "kind": item["kind"],
            "description": item.get("description") or "",
            "path": [
                part["name"]
                for part in self.workspace.assets.path(asset_id)
                if self.sees_subject(f"asset:{part['asset_id']}")
            ],
            "attributes": self.workspace.assets.attributes(asset_id),
            "signals": [
                {
                    "role": signal.get("role") or "",
                    "signal": signal["signal_id"],
                    "name": signal.get("name") or "",
                    "unit": signal.get("unit") or "",
                }
                for signal in self.workspace.assets.signals(asset_id)
            ],
            "results": self.results(ref),
            "open_actions": self.actions(ref),
            "recent_events": self.events(ref, limit=8),
        }

    def explained(self, ref: str) -> list[dict[str, Any]]:
        """What the specialist's apps wrote about ``ref`` (its protocol, its run report...)."""

        return [
            {
                "ref": item["ref"],
                "app": self.app_name(item["app"]),
                "kind": item["kind"],
                "title": item["title"],
                "text": item["text"],
                "updated_at": item["updated_at"],
            }
            for item in self.workspace.knowledge.about(ref, apps=self.apps)[:4]
        ]

    def search_knowledge(self, text: str, limit: int = 8) -> list[dict[str, Any]]:
        """Texts of the specialist's apps matching ``text``: their refs, titles and openings."""

        return [
            {
                "ref": item["ref"],
                "app": self.app_name(item["app"]),
                "kind": item["kind"],
                "title": item["title"],
                "opening": item["text"][:300],
            }
            for item in self.workspace.knowledge.search(
                text, apps=self.apps, limit=max(1, min(limit, 20))
            )
        ]

    def run(self, ref: str) -> dict[str, Any] | None:
        """A run (``run:<app>/<id>``) of one of the specialist's apps, with its report."""

        app, _, run_id = parse_ref(ref).id.partition("/")
        if app not in self.apps or not run_id:
            return None
        found = self.workspace.results.run(app, run_id)
        explained = self.explained(ref)
        if found is None and not explained:
            return None
        return {"ref": ref, "app": self.app_name(app), "run": found, "explained": explained}

    def recent_runs(
        self, *, status: str | None = None, subject: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        rows = [
            item
            for item in self.workspace.results.runs(status=status, subject=subject, limit=100)
            if item["app"] in self.apps and self.sees_subject(str(item.get("subject") or ""))
        ]
        return [
            {
                "ref": f"run:{item['app']}/{item['id']}",
                "app": self.app_name(item["app"]),
                "name": item["name"],
                "status": item["status"],
                "started_at": item["started_at"],
                "summary": item["summary"],
            }
            for item in rows[:limit]
        ]

    def lookup(self, ref: str) -> dict[str, Any] | None:
        parsed = parse_ref(ref)
        if parsed.kind == "asset":
            found = self.asset(parsed.id)
            if found is not None:
                found["explained"] = self.explained(ref)
            return found
        if parsed.kind == "action" and parsed.id.isdigit():
            item = self.workspace.actions.get(int(parsed.id))
            return {**item, "ref": ref} if item and self.sees_action(item) else None
        if parsed.kind == "run":
            return self.run(ref)
        if parsed.kind == "app":
            # A whole app (its assistant page): what it explained about itself, its worst first.
            if parsed.id not in self.apps:
                return None
            name = self.app_name(parsed.id)
            return {
                "ref": ref,
                "app": name,
                "explained": self.explained(ref),
                "attention": [item for item in self.worst(30) if item["app"] == name],
                "recent_runs": [item for item in self.recent_runs(limit=30) if item["app"] == name][
                    :10
                ],
            }
        if not self.sees_subject(ref):
            return None
        found = {
            "ref": ref,
            "explained": self.explained(ref),
            "results": self.results(ref),
            "recent_events": self.events(ref),
        }
        return found if found["explained"] or found["results"] or found["recent_events"] else None

    def worst(self, limit: int = 10) -> list[dict[str, Any]]:
        """Results of the specialist's apps that are not ok, worst first."""

        if not self.apps:
            return []
        rows = [
            item
            for item in self.workspace.results.not_ok(sorted(self.apps), ("ok", "good", "normal"))
            if self.sees_subject(item["subject"])
        ]
        rows.sort(key=lambda item: (STATUS_ORDER.get(item["status"], 3), item["score"] or 1e9))
        return [
            {
                "subject": item["subject"],
                "app": self.app_name(item["app"]),
                "kind": item["kind"],
                "status": item["status"],
                "score": item["score"],
                "summary": item["summary"],
            }
            for item in rows[: max(1, min(limit, 30))]
        ]

    # Text --------------------------------------------------------------------

    def result_line(self, item: dict[str, Any]) -> str:
        """`Link · Loop health: warning, 54/100. PV–SP mean absolute error...`: in words, no ids."""

        score = f", {_number(item['score'])}/100" if item.get("score") is not None else ""
        summary = f". {item['summary']}" if item.get("summary") else ""
        status = t(STATUS_WORDS.get(str(item["status"]), str(item["status"])))
        return (
            f"{self.app_name(item['app'])} · {result_kind(item['kind'])}: {status}{score}{summary}"
        )
