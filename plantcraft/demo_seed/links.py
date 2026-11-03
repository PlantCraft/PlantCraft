"""The story's links: ``{{name}}`` in a text becomes a link to the document, dashboard, report,
action, chat or conversation it names, once that exists."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from .base import Http, SeedError, Suite, _detail, _items, log


def _doc(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(blocks)}


def _para(*parts: Any) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": part} if isinstance(part, str) else part for part in parts
        ],
    }


def _mention(ref: str, label: str) -> dict[str, Any]:
    return {"type": "mention", "attrs": {"id": ref, "label": label}}


def _checklist(*items: tuple[bool, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "taskList",
        "content": [
            {"type": "taskItem", "attrs": {"checked": done}, "content": [line]}
            for done, line in items
        ],
    }


# The story's links ---------------------------------------------------------------------------

# Everything the team writes points at what it is about ("conectar tudo"): an
# action names the document it follows, the dashboard that shows it and the chat that explained
# it; a message links the action it opened. Texts write ``{{name}}`` (or ``{{name|label}}``) for
# such a thing: a document by its number, a dashboard or report by its name, an action, chat or
# conversation by its title. It becomes a link once the thing exists, its label otherwise.
NAMED = re.compile(r"\{\{([^{}|]+)(?:\|([^{}]+))?\}\}")
# Where a kind's page is, for the assistant's Markdown (a message or note links by reference).
PAGES = {
    "doc": "/doc/documents/{id}",
    "dashboard": "/dash/dashboards/{id}",
    "report": "/dash/reports/{id}",
    "asset": "/assets/{id}",
}


@dataclass
class Links:
    """What the story points at, by name: ``"DOC-MH-001"`` -> ``"doc:<id>"``."""

    refs: dict[str, str] = field(default_factory=dict)

    def add(self, name: str, ref: str) -> None:
        self.refs[name] = ref

    def ref(self, name: str) -> str | None:
        """``name``'s reference (an ``asset:`` reference is its own), or None."""

        name = name.strip()
        return name if name.startswith("asset:") else self.refs.get(name)

    def of(self, *names: str) -> list[str]:
        """The references of ``names`` that exist."""

        return list(dict.fromkeys(ref for ref in map(self.ref, names) if ref))

    def rich(self, text: str) -> tuple[list[Any], str]:
        """``text`` as a note's paragraph parts (mentions for the links) and its plain text."""

        parts: list[Any] = []
        plain, last = [], 0
        for match in NAMED.finditer(text):
            parts.append(text[last : match.start()])
            plain.append(text[last : match.start()])
            label = (match[2] or match[1].removeprefix("asset:")).strip()
            ref = self.ref(match[1])
            parts.append(_mention(ref, label) if ref else label)
            plain.append(f"#{label}" if ref else label)
            last = match.end()
        parts.append(text[last:])
        plain.append(text[last:])
        return [part for part in parts if part], "".join(plain)

    def fill(self, text: str) -> str:
        """``{{name}}`` as a mention, ``#[label](kind:id)``, or its label when it is missing."""

        def mention(match: re.Match[str]) -> str:
            label = (match[2] or match[1].removeprefix("asset:")).strip()
            ref = self.ref(match[1])
            return f"#[{label}]({ref})" if ref else label

        return NAMED.sub(mention, text)

    def markdown(self, text: str) -> str:
        """``{{name}}`` as a Markdown link to its page (the assistant's answers), or bold."""

        def link(match: re.Match[str]) -> str:
            label = (match[2] or match[1].removeprefix("asset:")).strip()
            kind, _, ident = (self.ref(match[1]) or "").partition(":")
            page = PAGES.get(kind)
            return f"[{label}]({page.format(id=ident)})" if page else f"**{label}**"

        return NAMED.sub(link, text)


def story_links(suite: Suite, admin: Http) -> Links:
    """The documents, dashboards and reports the apps hold now, by number and name. Each is
    explained to PlantCraft too (API v1 knowledge, as their app's editor), so a link to it reads
    its name, not its id, and the assistant knows what it is."""

    links = Links()
    texts = []
    found = [
        ("doccraft", "/api/documents", "documents", "number", "doc_id", "doc"),
        ("dashcraft", "/api/dashboards", "dashboards", "name", "dashboard_id", "dashboard"),
        ("dashcraft", "/api/reports", "reports", "name", "report_id", "report"),
    ]
    for app_id, path, key, name, ident, kind in found:
        client = suite.app(admin, app_id)
        if client is None:
            continue
        status, answer = client.call("GET", path, ok=(404, 502, 503))
        for item in _items(answer, key) if status < 300 else []:
            if not item.get(name) or item.get(ident) is None:
                continue
            ref = f"{kind}:{item[ident]}"
            links.add(item[name], ref)
            about = " ".join(str(item.get(field) or "") for field in ("title", "description"))
            texts.append(
                {
                    "app": app_id,
                    "ref": ref,
                    "kind": kind,
                    "title": str(item[name])[:200],
                    "text": f"{item[name]}: {about.strip()}"[:2000]
                    if about.strip()
                    else item[name],
                    "url": PAGES[kind].format(id=item[ident]),
                }
            )
    if texts:
        platform = Http(suite.processcraft, token=admin.post("/api/v1/auth/token")["token"])
        status, answer = platform.call("PUT", "/api/v1/knowledge", texts, ok=(403, 404, 422))
        if status < 300 and answer.get("errors"):
            log(f"WARNING knowledge: {_detail(answer['errors'][:2])}")
    return links


# The pages of what a reference names, for the demo's guides by role (frontend/src/demoGuides.tsx).
GUIDE_PAGES = {
    **PAGES,
    "action": "/actions/{id}",
    "conversation": "/messages/{id}",
    "chat": "/assistant/{id}",
    "diagram": "/dash/diagrams/{id}",
    "study": "/model/studies/{id}",
}


def guide_links(workspace: Any, suite: Suite, admin: Http, links: Links) -> int:
    """Where each name of the story opens now (``demo_guide_links``): the guides by role point at
    "Plant overview" or "DOC-MH-001", whose ids are this installation's. Also the View process
    displays and the Models studies, which the story's texts do not name."""

    _named(links, workspace.actions, workspace.messages, suite.admin)
    pages: dict[str, str] = {}
    for name, ref in links.refs.items():
        kind, _, ident = ref.partition(":")
        if kind in GUIDE_PAGES and ident:
            pages[name] = GUIDE_PAGES[kind].format(id=urllib.parse.quote(ident, safe=""))
    found = [
        ("dashcraft", "/api/diagrams", "name", "diagram_id", "diagram"),
        ("modelcraft", "/api/studies", "name", "id", "study"),
    ]
    for app_id, path, name, ident, kind in found:
        client = suite.app(admin, app_id)
        if client is None:
            continue
        try:
            status, answer = client.call("GET", path, ok=(404, 502, 503))
        except SeedError as error:
            log(f"WARNING guides: {error}")
            continue
        for item in answer if status < 300 and isinstance(answer, list) else []:
            if item.get(name) and item.get(ident) is not None:
                pages.setdefault(str(item[name]), GUIDE_PAGES[kind].format(id=item[ident]))
    workspace.demo_visits.set_guide_links(pages)
    return len(pages)


def _named(links: Links, store: Any, messages: Any, admin: str) -> None:
    """The actions and conversations PlantCraft holds, by title."""

    for item in store.list(limit=1000):
        links.add(item["title"], f"action:{item['action_id']}")
    for item in messages.list_for(admin, limit=1000):
        if item.get("title"):
            links.add(item["title"], f"conversation:{item['conversation_id']}")
