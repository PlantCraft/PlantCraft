"""HTTP routes: API v1's calendar feeds and to-dos, what an app puts in Desk (docs/api-v1.md).

The app declares its feeds in ``[[contributes.calendar]]`` and its to-do kinds in
``[[contributes.todo]]``; a feed or a kind it did not declare is refused, so what an app may
put in anyone's Desk is what the administrator saw on the Apps page. The formats are
``plantcraft_sdk.desk``'s; ``plantcraft.desk.app_items`` keeps them.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from plantcraft.api.deps import Runtime
from plantcraft.api.identity import Caller, V1Caller
from plantcraft.api.routers.v1_links import _app_for, _first_error, _http, _prefix
from plantcraft.desk.app_items import AppItemError
from plantcraft.i18n import t
from plantcraft_sdk.desk import FeedIn, TodoIn
from plantcraft_sdk.links import LinkError, check_url

router = APIRouter(prefix="/api/v1")

SLUG = r"^[a-z][a-z0-9-]{0,40}$"


def _writer(caller: Caller, app: str | None) -> str:
    try:
        return _app_for(caller, app)
    except LinkError as error:
        raise _http(error) from error


def _declared(rt: Any, app: str, table: str) -> dict[str, dict[str, Any]]:
    """The ids ``app`` declared in ``[[contributes.<table>]]``, from the registry."""

    row = rt.contributions.get(app) or {}
    return {item["id"]: item for item in (row.get("contributes") or {}).get(table, [])}


def _url(url: str | None, app: str) -> str | None:
    try:
        return check_url(url, _prefix(app))
    except LinkError as error:
        raise _http(error) from error


def _store_error(error: AppItemError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=t(str(error)))


@router.put("/calendar/{feed}")
def put_calendar(
    feed: Annotated[str, Path(pattern=SLUG)],
    caller: V1Caller,
    rt: Runtime,
    app: str | None = None,
    body: Any = Body(None),
) -> dict[str, Any]:
    """A calendar feed's whole list, replaced: ``[{id, title, start, end?, all_day, audience,
    ref?, url?, detail?}]``. The feed is one of the app's ``[[contributes.calendar]]``."""

    owner = _writer(caller, app)
    if feed not in _declared(rt, owner, "calendar"):
        raise HTTPException(
            status_code=422,
            detail=t(
                "{app} has no calendar feed {feed}: declare it in [[contributes.calendar]].",
                app=owner,
                feed=feed,
            ),
        )
    try:
        given = FeedIn.model_validate({"items": body if isinstance(body, list) else None})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_first_error(exc)) from exc
    items = [{**item.model_dump(mode="json"), "url": _url(item.url, owner)} for item in given.items]
    try:
        count = rt.app_items.put_feed(owner, feed, items)
    except AppItemError as error:
        raise _store_error(error) from error
    return {"app": owner, "feed": feed, "items": count}


@router.post("/todos")
def put_todo(
    caller: V1Caller, rt: Runtime, app: str | None = None, body: Any = Body(None)
) -> dict[str, Any]:
    """A to-do for a person or a group, made or changed by its ``key`` (a done one stays
    done). The ``kind`` is one of the app's ``[[contributes.todo]]``."""

    owner = _writer(caller, app)
    try:
        given = TodoIn.model_validate(body if isinstance(body, dict) else {})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_first_error(exc)) from exc
    if given.kind not in _declared(rt, owner, "todo"):
        raise HTTPException(
            status_code=422,
            detail=t(
                "{app} has no to-do kind {kind}: declare it in [[contributes.todo]].",
                app=owner,
                kind=given.kind,
            ),
        )
    kind, _, target = given.for_.partition(":")
    if kind == "user" and rt.workspace.users.get_user(target) is None:
        raise HTTPException(status_code=422, detail=t("Nobody is called {name}.", name=target))
    if kind == "group" and rt.workspace.groups.get(target) is None:
        raise HTTPException(status_code=422, detail=t("There is no group {name}.", name=target))
    item = {**given.as_body(), "url": _url(given.url, owner)}
    try:
        return rt.app_items.put_todo(owner, item)
    except AppItemError as error:
        raise _store_error(error) from error


@router.get("/todos")
def app_todos(
    caller: V1Caller,
    rt: Runtime,
    app: str | None = None,
    state: Annotated[str, Query(pattern=r"^(open|done|all)$")] = "all",
) -> list[dict[str, Any]]:
    """The app's own to-dos, newest change first, with who ticked them and when."""

    return rt.app_items.app_todos(_writer(caller, app), state)


class CloseIn(BaseModel):
    keys: list[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=500
    )


@router.post("/todos/close")
def close_todos(
    body: CloseIn, caller: V1Caller, rt: Runtime, app: str | None = None
) -> dict[str, Any]:
    """The app closes its to-dos: gone from every Desk. Answers how many there were."""

    owner = _writer(caller, app)
    closed = sum(1 for key in dict.fromkeys(body.keys) if rt.app_items.remove_todo(owner, key))
    return {"app": owner, "closed": closed}
