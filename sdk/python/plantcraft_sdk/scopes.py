"""What an app may do in API v1: its ``[permissions]``, held to every route (scale review E4).

An app declares in ``app.toml`` what it reads and writes; the administrator sees that list
before the install, and PlantCraft holds the app's service token to it on every API v1 route:
a route the app did not ask for answers 403. Only an app's own token is held this way; a person's
token (an app acting for the person in front of it) keeps the person's own access.

``ROUTE_SCOPES`` names, for every API v1 route, the permission it needs (``read.<name>`` or
``write.<name>``) or ``None`` for what every app may do: its own identity, the installation,
and what ``[contributes]`` already declares and PlantCraft checks there (calendar feeds, to-dos,
settings). Writing with a language model sends plant text out of the app, so it needs its own
``write.llm`` besides the use declared in ``[[contributes.llm]]`` (security audit, 2026-10-26).
A route missing from the table is refused to apps, so a new route is closed until it is named
here (``tests/contract`` holds the table to the routes).
``CLIENT_SCOPES`` names the permission each client method needs, so an app's CI can tell from
its code what its ``app.toml`` must declare (``apptest.permission_problems``).
"""

from __future__ import annotations

READ_SCOPES: dict[str, str] = {
    "assets": "Read the assets and their tree",
    "signals": "Read the signals and their metadata",
    "series": "Read signal values (time series)",
    "results": "Read results published by apps",
    "events": "Read events published by apps",
    "runs": "Read the runs apps record",
    "schedules": "Read the schedules apps keep",
    "people": "Read the people and groups (names only)",
    "knowledge": "Read the knowledge apps keep for the assistant",
}
WRITE_SCOPES: dict[str, str] = {
    "audit": "Write entries to the audit log",
    "results": "Publish its own results",
    "events": "Publish its own events",
    "runs": "Record its own runs",
    "schedules": "Keep its own schedules",
    "series": "Write its own derived series",
    "notifications": "Send notifications to people",
    "knowledge": "Keep knowledge for the assistant",
    "compute": "Send computations to the suite's compute workers",
    "llm": "Send text to a language model an administrator set up",
}
PERMISSIONS: dict[str, str] = {
    **{f"read.{name}": label for name, label in READ_SCOPES.items()},
    **{f"write.{name}": label for name, label in WRITE_SCOPES.items()},
}

ROUTE_SCOPES: dict[tuple[str, str], str | None] = {
    # Identity and the installation: every app.
    ("GET", "/api/v1/auth/keys"): None,
    ("GET", "/api/v1/auth/revoked"): None,
    ("POST", "/api/v1/auth/token"): None,
    ("POST", "/api/v1/auth/service-token"): None,
    ("GET", "/api/v1/me"): None,
    ("GET", "/api/v1/installation"): None,
    ("GET", "/api/v1/apps"): None,
    # A closed app reads its own licence (docs/app-package.md, section 8).
    ("GET", "/api/v1/apps/self/license"): None,
    # What the app adds, declared in [contributes] and checked there.
    ("PUT", "/api/v1/contributions"): None,
    ("GET", "/api/v1/contributions"): None,
    ("GET", "/api/v1/contributions/settings"): None,
    ("PUT", "/api/v1/events/catalog"): None,
    ("GET", "/api/v1/events/catalog"): None,
    ("PUT", "/api/v1/calendar/{feed}"): None,
    ("POST", "/api/v1/todos"): None,
    ("GET", "/api/v1/todos"): None,
    ("POST", "/api/v1/todos/close"): None,
    # A language model (a use declared in [[contributes.llm]] too).
    ("POST", "/api/v1/llm/{use}"): "write.llm",
    # Plant.
    ("GET", "/api/v1/assets"): "read.assets",
    ("GET", "/api/v1/assets/{asset_id}"): "read.assets",
    ("GET", "/api/v1/asset-types"): "read.assets",
    ("GET", "/api/v1/explore"): "read.assets",
    ("PUT", "/api/v1/assets/results"): "write.results",
    ("POST", "/api/v1/assets/results/remove"): "write.results",
    ("GET", "/api/v1/signals"): "read.signals",
    ("GET", "/api/v1/signals/{signal_id}"): "read.signals",
    ("GET", "/api/v1/signals/{signal_id}/series"): "read.series",
    ("GET", "/api/v1/signals/{signal_id}/value"): "read.series",
    ("GET", "/api/v1/signals/{signal_id}/summary"): "read.series",
    ("GET", "/api/v1/signals/{signal_id}/runs"): "read.series",
    ("POST", "/api/v1/series"): "read.series",
    ("PUT", "/api/v1/series"): "write.series",
    ("PUT", "/api/v1/series/runs"): "write.series",
    ("POST", "/api/v1/series/retire"): "write.series",
    # What apps publish.
    ("POST", "/api/v1/audit"): "write.audit",
    ("GET", "/api/v1/results"): "read.results",
    ("PUT", "/api/v1/results"): "write.results",
    ("GET", "/api/v1/results/history"): "read.results",
    ("GET", "/api/v1/events"): "read.events",
    ("POST", "/api/v1/events"): "write.events",
    ("GET", "/api/v1/runs"): "read.runs",
    ("PUT", "/api/v1/runs"): "write.runs",
    ("GET", "/api/v1/schedules"): "read.schedules",
    ("PUT", "/api/v1/schedules"): "write.schedules",
    ("GET", "/api/v1/knowledge"): "read.knowledge",
    ("PUT", "/api/v1/knowledge"): "write.knowledge",
    ("POST", "/api/v1/knowledge/delete"): "write.knowledge",
    # People.
    ("GET", "/api/v1/people"): "read.people",
    ("GET", "/api/v1/groups"): "read.people",
    ("GET", "/api/v1/notifications"): "write.notifications",
    ("POST", "/api/v1/notifications"): "write.notifications",
    ("POST", "/api/v1/notifications/resolve"): "write.notifications",
    # Compute: tasks for the suite's compute workers (docs/compute.md).
    ("POST", "/api/v1/compute/tasks"): "write.compute",
    ("GET", "/api/v1/compute/tasks/{task_id}"): "write.compute",
    ("POST", "/api/v1/compute/wait"): "write.compute",
    ("GET", "/api/v1/compute/tasks/{task_id}/output"): "write.compute",
    ("POST", "/api/v1/compute/tasks/{task_id}/cancel"): "write.compute",
    ("DELETE", "/api/v1/compute/tasks/{task_id}"): "write.compute",
    ("POST", "/api/v1/compute/runs/{run_id}/cancel"): "write.compute",
    ("GET", "/api/v1/compute/capacity"): "write.compute",
}
# Routes for a person only (their inbox, actions, assistant, notebooks): never an app's token.
PERSON_ONLY: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/inbox"),
        ("GET", "/api/v1/queue"),
        ("GET", "/api/v1/actions"),
        ("GET", "/api/v1/assistant"),
        ("POST", "/api/v1/assistant/conversations"),
        ("GET", "/api/v1/assistant/conversations/{conversation_id}"),
        ("POST", "/api/v1/assistant/conversations/{conversation_id}/messages"),
        ("GET", "/api/v1/notebooks"),
        ("GET", "/api/v1/notebooks/file"),
        ("GET", "/api/v1/objects"),
        ("GET", "/api/v1/apps/{app}/objects/{kind}"),
        ("GET", "/api/v1/apps/{app}/objects/{kind}/{object_id}"),
        ("GET", "/api/v1/apps/{app}/notebooks/runtime"),
        ("POST", "/api/v1/apps/{app}/objects/{kind}/run"),
        ("GET", "/api/v1/tools"),
        ("POST", "/api/v1/apps/{app}/tools/{tool_id}"),
    }
)

# The client's methods (``plantcraft_sdk.client.PlantCraftClient``) and what they need.
CLIENT_SCOPES: dict[str, str] = {
    "assets": "read.assets",
    "asset": "read.assets",
    "asset_types": "read.assets",
    "sync_result_assets": "write.results",
    "remove_result_assets": "write.results",
    "signals": "read.signals",
    "signal": "read.signals",
    "series": "read.series",
    "series_frame": "read.series",
    "series_many": "read.series",
    "series_many_pandas": "read.series",
    "series_pandas": "read.series",
    "series_runs": "read.series",
    "series_run_list": "read.series",
    "value": "read.series",
    "put_series": "write.series",
    "put_series_runs": "write.series",
    "retire_series": "write.series",
    "audit": "write.audit",
    "results": "read.results",
    "result_history": "read.results",
    "put_results": "write.results",
    "events": "read.events",
    "post_events": "write.events",
    "post_event": "write.events",
    "runs": "read.runs",
    "put_runs": "write.runs",
    "schedules": "read.schedules",
    "put_schedules": "write.schedules",
    "knowledge": "read.knowledge",
    "put_knowledge": "write.knowledge",
    "delete_knowledge": "write.knowledge",
    "people": "read.people",
    "groups": "read.people",
    "notification_settings": "write.notifications",
    "notify": "write.notifications",
    "resolve_notification": "write.notifications",
    "llm": "write.llm",
}


def scope_name(kind: str, name: str) -> str:
    return f"{kind}.{name}"


def declared(read: list[str] | tuple[str, ...], write: list[str] | tuple[str, ...]) -> set[str]:
    """The permission ids of an ``app.toml``'s ``[permissions] read`` and ``write`` lists."""

    return {f"read.{name}" for name in read} | {f"write.{name}" for name in write}


def required(method: str, route: str) -> tuple[bool, str | None]:
    """``(known, scope)`` of an API v1 route for an app's token: ``(False, None)`` for a
    route no app may use (a person's, or one missing from the table)."""

    method = "GET" if method.upper() == "HEAD" else method.upper()
    key = (method, route.replace(":path}", "}"))
    if key in ROUTE_SCOPES:
        return True, ROUTE_SCOPES[key]
    return False, None


__all__ = [
    "CLIENT_SCOPES",
    "PERMISSIONS",
    "PERSON_ONLY",
    "READ_SCOPES",
    "ROUTE_SCOPES",
    "WRITE_SCOPES",
    "declared",
    "required",
    "scope_name",
]
