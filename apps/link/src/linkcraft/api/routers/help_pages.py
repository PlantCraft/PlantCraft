"""Help: the guides and method pages of the help browser, and the loop-type defaults.

``/api/help`` is the app-standard index (section 7); ``/api/help/docs`` and
``/api/help/docs/<id>`` feed the suite's help browser (``catalog.help_docs``).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

from linkcraft import APP_ID
from linkcraft.api.deps import CurrentUser, RuntimeDep
from linkcraft.catalog import help_docs
from linkcraft.catalog.help import help_index, method_help
from linkcraft.catalog.labels import METHOD_LABELS
from linkcraft.catalog.loop_types import GENERIC_PROFILE, GENERIC_WHY, LOOP_TYPE_DEFAULTS
from linkcraft.i18n import t

router = APIRouter()


@router.get("/api/help")
def help_pages(_user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """The help pages index (app standard, section 7): every page, where people read it."""

    root = rt.settings.root_path
    pages = [
        {
            "id": doc["id"],
            "kind": "method" if doc["id"].startswith("methods/") else "screen",
            "title": doc["title"],
            "category": doc["category"],
            "url": f"{root}/help/{doc['id']}"
            if doc["id"].startswith("methods/")
            else f"{root}/help?doc={quote(doc['id'], safe='/')}",
            "api": f"{root}/api/help/docs/{doc['id']}",
        }
        for doc in help_docs.docs()
    ]
    return {"app": APP_ID, "pages": pages}


@router.get("/api/help/docs")
def help_doc_index(_user: CurrentUser) -> list[dict[str, str]]:
    """Every guide and method page, as ``{id, title, category}`` for the help browser."""

    return help_docs.docs()


@router.get("/api/help/docs/{doc_id:path}")
def help_doc(doc_id: str, _user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """One help page as Markdown, with this site's configured defaults."""

    kind, _, name = doc_id.partition("/")
    markdown: str | None = None
    if kind == "guides" and name == "loop-types":
        markdown = help_docs.loop_types_markdown(loop_types_help(_user, rt))
    elif kind == "guides":
        markdown = help_docs.guide(name)
    elif kind == "methods" and name.startswith("sq_"):
        configured = rt.quality_settings.get().check_parameters.get(name)
        markdown = help_docs.check_markdown(name, configured)
    elif kind == "methods":
        markdown = help_docs.loop_method_markdown(name, rt.presets.list_method_defaults().get(name))
    if markdown is None:
        raise HTTPException(status_code=404, detail=t("Help page not found."))
    title = next((doc["title"] for doc in help_docs.docs() if doc["id"] == doc_id), doc_id)
    return {"id": doc_id, "title": title, "markdown": markdown}


@router.get("/api/help/methods")
def methods_help(_user: CurrentUser) -> list[dict[str, Any]]:
    return help_index()


@router.get("/api/help/methods/{method_id}")
def method_help_page(method_id: str, _user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    page = method_help(method_id, rt.presets.list_method_defaults().get(method_id))
    if page is None:
        raise HTTPException(status_code=404, detail=t("Method not found."))
    return page


@router.get("/api/help/loop-types")
def loop_types_help(_user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    """The algorithm and parameters each loop type of the asset record starts a loop with."""

    names = {item["profile_id"]: item["name"] for item in rt.presets.list_profiles()}
    rows = [
        {
            "loop_type": loop_type,
            "profile_id": defaults["profile_id"],
            "profile_name": names.get(defaults["profile_id"], defaults["profile_id"]),
            "parameters": [
                {
                    "method_id": method_id,
                    "method": METHOD_LABELS.get(method_id, method_id),
                    "values": values,
                }
                for method_id, values in defaults["parameters"].items()
            ],
            "why": t(defaults["why"]),
        }
        for loop_type, defaults in LOOP_TYPE_DEFAULTS.items()
    ]
    rows.append(
        {
            "loop_type": None,
            "profile_id": GENERIC_PROFILE,
            "profile_name": names.get(GENERIC_PROFILE, GENERIC_PROFILE),
            "parameters": [],
            "why": t(GENERIC_WHY),
        }
    )
    return rows
