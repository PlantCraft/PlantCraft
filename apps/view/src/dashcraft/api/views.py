"""What the dashboard routes and the public-link routes share: drawing a saved card.

The viewer picks the dashboard's variables (``var-<name>`` in the address; ``context`` is the
old single asset) and a window. Saved dashboards are read with the app's service token, so a
value is only taken when the dashboard offers it: an asset of the variable's kind, a value of
its list, one of its intervals. A link to the "Loop detail" dashboard shows loops, not any
asset someone types into the address.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from plantcraft_sdk.auth import User

from dashcraft.api.deps import everyone_sees, guarded, permissions
from dashcraft.api.runtime import Runtime
from dashcraft.dashboards.model import Card, check_window
from dashcraft.dashboards.variables import ALL, MAX_VALUES, Variable
from dashcraft.diagrams.model import on_page
from dashcraft.diagrams.read import read_diagram
from dashcraft.diagrams.symbols import library
from dashcraft.i18n import t
from dashcraft.query.cards import Reader, card_window, read_card
from dashcraft.reports.starter import sections_from

MAX_CONTEXT_OPTIONS = 2000


def _reader(rt: Runtime, user: User | None) -> tuple[Reader, bool]:
    try:
        return rt.dashboard_reader(user)
    except LookupError as exc:
        raise HTTPException(
            status_code=503,
            detail=t(
                "Public links need the Dashboards app key: an admin creates one in PlantCraft "
                "and sets PLANTCRAFT_APP_KEY for Dashboards."
            ),
        ) from exc


def report_reader(rt: Runtime, user: User | None) -> tuple[Reader, bool]:
    """What a saved report reads with (a published report, like a saved dashboard)."""

    return _reader(rt, user)


def _window(window: str | None) -> str | None:
    if window in (None, ""):
        return None
    try:
        return check_window(window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def raw_values(params: Any) -> dict[str, list[str]]:
    """``var-<name>`` query parameters (repeated for several values), as Grafana writes them."""

    found: dict[str, list[str]] = {}
    for key, value in params.multi_items():
        if not key.startswith("var-") or len(found) > 20:
            continue
        name = key[4:]
        if len(name) <= 30 and len(value) <= 300:
            found.setdefault(name, []).append(value)
    return {name: values[: MAX_VALUES + 1] for name, values in found.items()}


def variables_of(dashboard: dict[str, Any]) -> list[Variable]:
    out = []
    for raw in dashboard.get("variables") or []:
        try:
            out.append(Variable.model_validate(raw))
        except ValueError:
            continue
    return out


def asset_options(
    reader: Reader, variable: Variable, parents: list[str] | None, service: bool
) -> list[dict[str, Any]]:
    """The assets an asset variable offers: its kind, under one of ``parents`` when it has a
    parent variable and something is picked there."""

    everything = guarded(lambda: reader.assets(None), service=service)
    by_id = {item.get("id"): item for item in everything}
    wanted = {parent for parent in parents or [] if parent and parent != ALL}

    def under(item: dict[str, Any]) -> bool:
        seen: set[Any] = set()
        parent = item.get("parent_id")
        while parent and parent not in seen:
            if parent in wanted:
                return True
            seen.add(parent)
            parent = (by_id.get(parent) or {}).get("parent_id")
        return False

    options = [
        {
            "value": item.get("id"),
            "text": item.get("name") or item.get("id"),
            "group": (by_id.get(item.get("parent_id")) or {}).get("name") or item.get("parent_id"),
            "description": (item.get("attributes") or {}).get("description") or "",
        }
        for item in everything
        if item.get("kind") == variable.asset_kind and (not wanted or under(item))
    ]
    options.sort(key=lambda item: (str(item["group"] or ""), str(item["text"])))
    return options[:MAX_CONTEXT_OPTIONS]


def variable_options(
    reader: Reader,
    variable: Variable,
    parents: list[str] | None,
    service: bool,
) -> list[dict[str, Any]]:
    if variable.type == "asset":
        return asset_options(reader, variable, parents, service)
    return [
        {"value": value, "text": value, "group": None, "description": ""}
        for value in variable.options
    ]


def resolve_values(
    reader: Reader,
    variables: list[Variable],
    raw: dict[str, list[str]],
    *,
    context: str | None,
    service: bool,
    check: bool = True,
) -> tuple[dict[str, list[str]], dict[str, str], dict[str, list[str]]]:
    """The values each variable stands for, the names to show for them, and their labels.

    A variable nobody picked takes its default, else (a list, an interval) its first value; an
    asset variable without a value leaves its cards asking for one. ``All`` is every option
    (at most ``MAX_VALUES``). With ``check``, a value the dashboard does not offer is refused.
    """

    values: dict[str, list[str]] = {}
    texts: dict[str, list[str]] = {}
    labels = {variable.name: variable.shown_name() for variable in variables}
    first_asset = next((item.name for item in variables if item.type == "asset"), None)
    for variable in variables:
        picked = [
            value.strip() for value in raw.get(variable.name) or [] if value and value.strip()
        ]
        if not picked and context and variable.name == first_asset:
            picked = [context]
        if not picked and variable.default:
            picked = [variable.default]
        if not picked and variable.type != "asset":
            picked = variable.options[:1]
        if len(picked) > 1 and not variable.multi:
            picked = picked[:1]
        if ALL in picked:
            options = variable_options(reader, variable, values.get(variable.parent or ""), service)
            values[variable.name] = [str(item["value"]) for item in options][:MAX_VALUES]
            texts[variable.name] = [str(item["text"]) for item in options][:MAX_VALUES]
            continue
        picked = picked[:MAX_VALUES]
        if variable.type == "asset":
            names = []
            for value in picked:
                asset = guarded(lambda value=value: reader.asset(value), service=service)
                if check and asset.get("kind") != variable.asset_kind:
                    raise HTTPException(
                        status_code=422,
                        detail=t(
                            "{name} shows assets of kind {kind}.",
                            name=variable.shown_name(),
                            kind=variable.asset_kind,
                        ),
                    )
                names.append(str(asset.get("name") or value))
            texts[variable.name] = names
        else:
            if check and any(value not in variable.options for value in picked):
                raise HTTPException(
                    status_code=422,
                    detail=t("{name} has no such value.", name=variable.shown_name()),
                )
            texts[variable.name] = picked
        values[variable.name] = picked
    return values, labels, texts


def card_data(
    rt: Runtime,
    dashboard: dict[str, Any],
    card_id: str,
    *,
    user: User | None,
    context: str | None,
    window: str | None,
    raw: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    found = next(
        (item for item in dashboard.get("cards") or [] if item.get("card_id") == card_id), None
    )
    if found is None:
        raise HTTPException(status_code=404, detail=t("Panel not found."))
    card = Card.model_validate(found)
    window = _window(window)
    reader, service = _reader(rt, user)
    context = (context or "").strip() or None
    variables = variables_of(dashboard)
    if context and len(context) > 300:
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    if context and not any(item.type == "asset" for item in variables):
        raise HTTPException(status_code=422, detail=t("This dashboard has no asset to choose."))
    values, labels, texts = resolve_values(
        reader, variables, raw or {}, context=context, service=service
    )
    if card.kind == "diagram":
        return diagram_card(rt, card, card_window(card, values, window), reader, service, user)
    return guarded(
        lambda: read_card(reader, card, None, window, values=values, labels=labels, texts=texts),
        service=service,
    )


# Diagrams shown elsewhere: on their own public link, and in a dashboard's diagram card -------


def public_diagram(diagram: dict[str, Any]) -> dict[str, Any]:
    """A diagram as a public link or a dashboard card draws it: its canvas and elements and the
    symbols it uses (the page then needs no library of its own); no authors, no stamps."""

    keep = (
        "diagram_id",
        "name",
        "description",
        "width",
        "height",
        "grid",
        "refresh_seconds",
        "default_window",
        "pages",
        "parts",
        "elements",
    )
    used = {
        element.get("symbol")
        for element in diagram.get("elements") or []
        if element.get("type") == "symbol"
    }
    return {
        **{key: diagram.get(key) for key in keep},
        "symbols": [symbol for symbol in library() if symbol["id"] in used],
    }


def shows_diagram(rt: Runtime, diagram: dict[str, Any] | None, user: User | None) -> bool:
    """A card shows a diagram to whoever sees its folder; on a public link (no ``user``), only
    one filed where everyone sees it, so a link never opens a closed folder."""

    if diagram is None:
        return False
    if user is None:
        return everyone_sees(rt, diagram.get("folder_id"))
    return permissions(rt, user).sees(diagram)


def diagram_card(
    rt: Runtime,
    card: Card,
    window: str,
    reader: Reader,
    service: bool,
    user: User | None,
) -> dict[str, Any]:
    """A diagram card's data: the diagram and its values over ``window`` (the dashboard's Time
    picker, else the card's own), or why it is not shown. The window's series stay out: a card
    shows the plant now, the diagram's own page plays it back."""

    found = rt.diagrams.get(card.diagram_id) if card.diagram_id else None
    out: dict[str, Any] = {"card_id": card.card_id, "kind": "diagram", "window": window}
    if found is None or not shows_diagram(rt, found, user):
        out["unavailable"] = t(
            "This process display is not available: it was deleted, or its folder is not open to you."
        )
        out["read_at"] = reader.clock().isoformat()
        return out
    # A card draws the diagram's first page; its own page turns the others.
    pages = found.get("pages") or []
    found = on_page(found, pages[0]["id"]) if pages else found
    data = guarded(lambda: read_diagram(reader, found, window, None), service=service)
    data.pop("series", None)
    out.update(diagram=public_diagram(found), data=data, read_at=data["read_at"])
    # Signed in, a click opens the diagram's page; a public link opens nothing else.
    if user is not None:
        out["url"] = f"/diagrams/{found['diagram_id']}"
    return out


def context_options(rt: Runtime, dashboard: dict[str, Any], user: User | None) -> list[dict]:
    """The assets of the dashboard's first asset variable (the picker before variables)."""

    first = next((item for item in variables_of(dashboard) if item.type == "asset"), None)
    if first is None:
        return []
    reader, service = _reader(rt, user)
    return [
        {
            "id": item["value"],
            "name": item["text"],
            "parent": item["group"],
            "description": item["description"],
        }
        for item in asset_options(reader, first, None, service)
    ]


def dashboard_variable_options(
    rt: Runtime, dashboard: dict[str, Any], name: str, parents: list[str], user: User | None
) -> list[dict[str, Any]]:
    variable = next((item for item in variables_of(dashboard) if item.name == name), None)
    if variable is None:
        raise HTTPException(status_code=404, detail=t("Variable not found."))
    reader, service = _reader(rt, user)
    return variable_options(reader, variable, parents[:MAX_VALUES], service)


def public_dashboard(dashboard: dict[str, Any]) -> dict[str, Any]:
    """A dashboard as a public link shows it: no authors, no internal stamps."""

    keep = (
        "dashboard_id",
        "name",
        "description",
        "context_kind",
        "variables",
        "refresh_seconds",
        "pages",
        "page_seconds",
        "cards",
    )
    return {key: dashboard.get(key) for key in keep}


def report_draft(rt: Runtime, dashboard: dict[str, Any], user: User) -> dict[str, Any]:
    """A report's start from ``dashboard`` (``reports.starter``): each variable at its default,
    else its first value, read with the person's own access."""

    reader, service = rt.user_reader(user), False
    variables = variables_of(dashboard)
    picks: dict[str, list[str]] = {}
    for variable in variables:
        if variable.default and variable.default != ALL:
            picks[variable.name] = [variable.default]
            continue
        try:
            options = variable_options(reader, variable, picks.get(variable.parent or ""), service)
        except HTTPException:
            options = []
        if options:
            picks[variable.name] = [str(options[0]["value"])]
    try:
        values, _labels, names = resolve_values(
            reader, variables, picks, context=None, service=service, check=False
        )
    except HTTPException:
        values, names = picks, picks
    return {
        "name": dashboard.get("name") or "",
        "description": dashboard.get("description") or "",
        "folder_id": dashboard.get("folder_id") or "",
        "sections": sections_from(dashboard, values, names),
    }
