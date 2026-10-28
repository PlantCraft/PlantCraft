"""The Examples folder: one folder per app, PlantCraft's own first (owner, 2026-10-26).

``Examples/PlantCraft`` holds the platform's examples (``templates``); every app that declares
``[contributes.notebooks] examples`` gets ``Examples/<app>`` (``Examples/Analytics``) with the ones
it serves at ``<prefix>api/notebooks/examples``, read through ``processcraft.api.app_proxy``. A
person sees the folders of the apps they may open. The browser's JupyterLab, the PlantCraft
Notebooks app on a computer (API v1) and "Open in a notebook" all read this one list.
"""

from __future__ import annotations

import logging
from typing import Any

from processcraft.api import app_proxy as proxy
from processcraft.notebooks import EXAMPLES_FOLDER, file_name, templates

LOGGER = logging.getLogger(__name__)
PLATFORM = "processcraft"
PLATFORM_FOLDER = "PlantCraft"
_LISTS = proxy.Cached()
_NOTEBOOKS = proxy.Cached()


def folder_of(name: str) -> str:
    """An app's folder: its name without the suite's (``PlantCraft Analytics`` -> ``Link``)."""

    short = name.removeprefix("PlantCraft ").strip()
    return file_name(short or name)[: -len(".ipynb")]


def _item(app: str, folder: str, example_id: str, title: str, summary: str) -> dict[str, Any]:
    name = file_name(title)
    return {
        "app": app,
        "folder": folder,
        "id": example_id if app == PLATFORM else f"{app}:{example_id}",
        "example": example_id,
        "title": title,
        "summary": summary,
        "name": name,
        "path": f"{EXAMPLES_FOLDER}/{folder}/{name}",
    }


def _apps(rt: Any, username: str) -> list[tuple[str, str]]:
    """``(app id, folder)`` of the installed apps with examples that ``username`` may open."""

    from processcraft.api.identity import user_claims

    claims = user_claims(rt, username) or {"apps": {}}
    names = {app.id: app.name for app in rt.suite_apps()}
    found = []
    for row in rt.contributions.listing(list(names)):
        notebooks = (row.get("contributes") or {}).get("notebooks") or {}
        if notebooks.get("examples") and row["app"] in claims["apps"]:
            found.append((row["app"], folder_of(names[row["app"]])))
    return found


def _app_examples(rt: Any, app: str, username: str) -> list[dict[str, Any]]:
    def read() -> list[dict[str, Any]]:
        try:
            answer = proxy.get(rt, app, "api/notebooks/examples", username)
        except proxy.AppUnreachable as exc:
            LOGGER.info("examples of %s: %s", app, exc)
            return []
        if answer.status != 200:
            return []
        items = answer.json().get("items") or []
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    return _LISTS.get(app, read)


def listing(rt: Any, username: str) -> list[dict[str, Any]]:
    """Every example ``username`` sees, PlantCraft's first, then each app's in the suite's order."""

    found = [
        _item(PLATFORM, PLATFORM_FOLDER, item["id"], item["title"], item["summary"])
        for item in templates.examples()
    ]
    for app, folder in _apps(rt, username):
        for item in _app_examples(rt, app, username):
            found.append(
                _item(
                    app,
                    folder,
                    str(item["id"]),
                    str(item.get("title") or item["id"]),
                    str(item.get("summary") or ""),
                )
            )
    return found


def folders(items: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(item["folder"] for item in items))


def notebook(rt: Any, username: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """The ``.ipynb`` of one listed example; None when its app does not answer."""

    if item["app"] == PLATFORM:
        return templates.example_notebook(item["example"])[1]

    def read() -> dict[str, Any] | None:
        try:
            answer = proxy.get(
                rt, item["app"], f"api/notebooks/examples/{item['example']}", username
            )
        except proxy.AppUnreachable:
            return None
        return answer.json() if answer.status == 200 else None

    return _NOTEBOOKS.get((item["app"], item["example"]), read)


def find(rt: Any, username: str, path: str) -> dict[str, Any] | None:
    """The listed example at ``path`` (``Examples/<folder>/<name>``), or by id."""

    return next(
        (item for item in listing(rt, username) if path in (item["path"], item["id"])), None
    )


def clear() -> None:
    _LISTS.clear()
    _NOTEBOOKS.clear()


__all__ = ["PLATFORM_FOLDER", "clear", "find", "folder_of", "folders", "listing", "notebook"]
