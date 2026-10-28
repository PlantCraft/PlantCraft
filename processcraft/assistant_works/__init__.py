"""The assistant's works (owner, 2026-10-25): what the assistant does on each page, declared as
data, and the context it gets when a person picks one (``docs/assistant.md``, "Works").

A work is declared once: PlantCraft's own in ``PLATFORM_WORKS``, an app's in its ``app.toml``
(``[[contributes.assistant.works]]``, checked by the SDK's ``AssistantWork``). A page only says
where the person is (``useAssistantPage({page, subject, facts, view})``); the button beside the
page's title lists the works of that page, and the chosen one opens the standard assistant chat
with a context PlantCraft builds here, always in the same sections:

- ``work``: what the person chose and what to do (the work's instructions);
- ``place``: the app, the page, where it is in the suite;
- ``subject``: the object of the page (its reference, as the suite names it, and small facts);
- ``view``: what the page shows (filters, selection, the ids of the rows on screen);
- ``fields``: for a ``create`` work, the fields of the object to propose;
- ``person``: who asks, with their access level.

Each section has a size limit; a cut says so. The page sends references and a few facts, never
whole tables: the model reads the rest with its read-only tools, as the person (so it sees only
what the person may see). A ``create`` work never writes: the model calls ``propose`` with the
fields, PlantCraft checks them (``check_fields``) and the person clicks Create on the card, which
calls the object's own route with their session.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from plantcraft_sdk.contributes import (
    AssistantOffer,
    AssistantWork,
    WorkField,
    check_fields,
    fields_schema,
)
from processcraft.assistant_works.platform import platform_works

LOGGER = logging.getLogger(__name__)

PLATFORM_APP = "processcraft"
CONTEXT_VERSION = "assistant-context/1"
# Characters each section of the context may weigh (about 12,000 in all).
LIMITS = {"work": 2000, "place": 300, "subject": 3000, "view": 2000, "fields": 4000, "person": 300}
MAX_FACTS = 30
MAX_ROWS = 50
MAX_VALUE = 300
LEVELS = ("dashboards", "viewer", "editor", "admin")

# PlantCraft's own works, page by page (assistant_works/platform.py; docs/assistant.md, "Works").
PLATFORM_WORKS: list[AssistantWork] = platform_works()


@dataclass(frozen=True)
class Work:
    app: str
    spec: AssistantWork
    # The apps' pages a PlantCraft work is also offered on ([[contributes.assistant.offers]]).
    offered_on: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.app}:{self.spec.id}"

    def pages(self) -> list[str]:
        return [f"{self.app}:{page}" for page in self.spec.pages] + list(self.offered_on)

    def offered_to(self, level: str | None) -> bool:
        if level not in LEVELS:
            return False
        return LEVELS.index(level) >= LEVELS.index(self.spec.level)

    def public(self) -> dict[str, Any]:
        """What the panel draws: the work, and for a create work the card's fields and routes."""

        spec = self.spec
        item: dict[str, Any] = {
            "key": self.key,
            "app": self.app,
            "kind": spec.kind,
            "title": spec.title,
            "hint": spec.hint,
            "ask": spec.ask,
        }
        if spec.kind == "create":
            item.update(
                object=spec.object,
                fields=[field.model_dump(mode="json") for field in spec.fields],
                create=spec.create,
                open=spec.open,
                form=spec.form,
            )
        return item

    def tool(self) -> dict[str, Any]:
        """The model's ``propose`` tool for this work."""

        button = (
            f"a button that opens the {self.spec.object}'s own form filled in with them, where "
            "they check it and save"
            if self.spec.form
            else "a Create button; nothing is created until they click it"
        )
        return {
            "name": PROPOSE,
            "description": (
                f"Propose the {self.spec.object} to the person, with its fields. They see a card "
                f"with the fields and {button}. Call it once every required field is known; if it "
                "answers problems, ask the person and propose again."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"fields": fields_schema(list(self.spec.fields))},
                "required": ["fields"],
            },
        }

    def check(self, fields: Any) -> tuple[dict[str, Any], list[str]]:
        return check_fields(list(self.spec.fields), fields)


PROPOSE = "propose"


class WorkRegistry:
    """Every work of the suite: PlantCraft's and those of the apps installed now.

    ``listing`` gives the apps' contributions (``ContributionStore.listing``); ``prefixes`` each
    installed app's address prefix: an app's create and open routes stay under it."""

    def __init__(
        self,
        listing: Callable[[list[str]], list[dict[str, Any]]] | None = None,
        prefixes: Callable[[], dict[str, str]] | None = None,
        platform: list[AssistantWork] | None = None,
    ):
        self.listing = listing
        self.prefixes = prefixes
        self.platform = PLATFORM_WORKS if platform is None else platform

    def all(self) -> list[Work]:
        if self.listing is None or self.prefixes is None:
            return [Work(PLATFORM_APP, spec) for spec in self.platform]
        prefixes = self.prefixes()
        rows = self.listing(list(prefixes))
        works = [Work(PLATFORM_APP, spec, tuple(_offered(rows, spec.id))) for spec in self.platform]
        for row in rows:
            prefix = prefixes.get(row["app"]) or ""
            table = (row.get("contributes") or {}).get("assistant") or {}
            for raw in table.get("works") or []:
                try:
                    spec = AssistantWork.model_validate(raw)
                except ValidationError as exc:
                    LOGGER.warning("%s declares a work PlantCraft cannot read: %s", row["app"], exc)
                    continue
                routes = [route for route in (spec.create, spec.open, spec.form) if route]
                if any(
                    not (prefix.startswith("/") and route.startswith(prefix)) for route in routes
                ):
                    LOGGER.warning("%s: work %s has a route outside the app", row["app"], spec.id)
                    continue
                works.append(Work(row["app"], spec))
        return works

    def for_page(self, page: str, level: str | None) -> list[Work]:
        """The works offered on ``page`` (``<app>:<page id>``) to a person of ``level``, the
        create works first."""

        found = [work for work in self.all() if page in work.pages() and work.offered_to(level)]
        return sorted(found, key=lambda work: work.spec.kind != "create")

    def get(self, key: str) -> Work | None:
        return next((work for work in self.all() if work.key == key), None)

    def creatable(self, level: str | None, apps: set[str] | None = None) -> list[Work]:
        """The create works a free chat may propose (owner, 2026-10-26: asked in any chat, a
        new block comes as a card that opens its form filled in): offered to ``level``, of an
        app the person may open, and not about one page's object (no ``{subject}``)."""

        found = []
        for work in self.all():
            spec = work.spec
            routes = "".join(route or "" for route in (spec.create, spec.open, spec.form))
            if spec.kind != "create" or "{subject}" in routes or not work.offered_to(level):
                continue
            if apps is not None and work.app != PLATFORM_APP and work.app not in apps:
                continue
            found.append(work)
        return found


CREATE = "propose_create"


def create_tool_name(work: Work) -> str:
    """The free chat's tool that proposes ``work``'s object: ``propose_create_<app>_<work>``."""

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", work.key)
    return f"{CREATE}_{slug}"[:64]


def create_tools(works: list[Work]) -> dict[str, tuple[Work, dict[str, Any]]]:
    """A chat started from no work proposes whatever the person may create: one tool per kind,
    with that kind's fields typed (a small model sent lists as text or objects to one tool
    with a free ``fields``, 2026-10-26) and its instructions, by tool name."""

    found: dict[str, tuple[Work, dict[str, Any]]] = {}
    for work in works:
        name = create_tool_name(work)
        tool = work.tool()
        tool["name"] = name
        tool["description"] = (
            f"Create a {work.spec.object} ({work.spec.title}) for the person: "
            + tool["description"]
            + " Never write the object as text for the person to copy instead."
            + (f" How to: {work.spec.instructions}" if work.spec.instructions else "")
        )[:2000]
        found[name] = (work, tool)
    return found


def _offered(rows: list[dict[str, Any]], work_id: str) -> list[str]:
    """The apps' pages that offer PlantCraft's work ``work_id``, as ``<app>:<page>``."""

    found: list[str] = []
    for row in rows:
        table = (row.get("contributes") or {}).get("assistant") or {}
        for raw in table.get("offers") or []:
            try:
                offer = AssistantOffer.model_validate(raw)
            except ValidationError as exc:
                LOGGER.warning("%s offers a work PlantCraft cannot read: %s", row["app"], exc)
                continue
            if offer.work == work_id:
                found += [f"{row['app']}:{page}" for page in offer.pages]
    return found


def _cut(text: str, limit: int, rest: str) -> str:
    if len(text) <= limit:
        return text
    return (
        text[: max(limit - 120, 0)].rstrip()
        + f"\n[cut: {len(text) - limit} more characters; {rest}]"
    )


def _small(value: Any) -> Any:
    """A fact or view value, short (a page sends references and a few facts, never tables)."""

    if isinstance(value, str):
        return value[:MAX_VALUE]
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, list):
        return [_small(item) for item in value[:MAX_ROWS]]
    if isinstance(value, Mapping):
        return {str(key)[:60]: _small(item) for key, item in list(value.items())[:MAX_FACTS]}
    return str(value)[:MAX_VALUE]


def envelope(
    work: Work | None,
    *,
    place: str = "",
    page: str = "",
    subject: Mapping[str, Any] | None = None,
    facts: Mapping[str, Any] | None = None,
    view: Mapping[str, Any] | None = None,
    person: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The context of a chat started from a page, in its sections (``CONTEXT_VERSION``)."""

    sections: dict[str, Any] = {"version": CONTEXT_VERSION}
    if work is not None:
        spec = work.spec
        sections["work"] = {
            "key": work.key,
            "kind": spec.kind,
            "title": spec.title,
            "instructions": spec.instructions,
        }
    sections["place"] = {"page": page, "where": place}
    if work is not None and work.spec.context:
        # The work's own context: only the facts and the view it names.
        keep = set(work.spec.context)
        facts = {key: value for key, value in (facts or {}).items() if key in keep}
        view = {key: value for key, value in (view or {}).items() if key in keep}
    if subject or facts:
        sections["subject"] = {**dict(subject or {}), "facts": _small(dict(facts or {}))}
    if view:
        sections["view"] = _small(dict(view))
    if work is not None and work.spec.kind == "create":
        sections["fields"] = {
            "object": work.spec.object,
            "fields": [
                {
                    key: value
                    for key, value in field.model_dump(mode="json").items()
                    if value not in (None, "", [], False) or key == "required"
                }
                for field in work.spec.fields
            ],
        }
    if person:
        sections["person"] = dict(person)
    return sections


READ_MORE = {
    "subject": "read the object with your tools",
    "view": "read the page's objects with your tools",
    "fields": "ask the person for the rest",
}


def render(sections: Mapping[str, Any]) -> str:
    """The context as the model reads it (and the person, under "See the context"): one titled
    block per section, each within its limit."""

    blocks = [f"[{sections.get('version', CONTEXT_VERSION)}]"]
    for name, limit in LIMITS.items():
        if name not in sections:
            continue
        text = json.dumps(sections[name], ensure_ascii=False, default=str, indent=None)
        blocks.append(f"## {name}\n{_cut(text, limit, READ_MORE.get(name, 'it was too long'))}")
    return "\n\n".join(blocks)


__all__ = [
    "CONTEXT_VERSION",
    "LIMITS",
    "PLATFORM_APP",
    "PLATFORM_WORKS",
    "PROPOSE",
    "Work",
    "WorkField",
    "WorkRegistry",
    "envelope",
    "render",
]
