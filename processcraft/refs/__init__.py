"""References: a short ``kind:id`` address for anything in the platform.

``asset:FIC-101``, ``action:42``, ``execution:job-9`` or ``loop:FIC-101`` can
be written in a message, stored on an event or put in a link. Each module
registers a resolver for the kinds it owns; the platform turns a reference
into a name, a state and a link without knowing the module. A reference whose
module is not installed resolves to ``available: False`` instead of failing.

In text a mention is written ``#[label](kind:id)`` (what the editor inserts)
or ``#kind:id``.

An id follows the suite's one rule (``plantcraft_sdk.refs.check_id``,
``docs/app-standard.md`` section 2): 1 to 300 visible characters without spaces
at either end, written as they are (a PI tag keeps its spaces and ``\\``:
``signal:pi:Unit 2\\FIC 101.PV``). Only a mention in text is narrower.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from plantcraft_sdk.refs import valid_id
from processcraft.i18n import t

_KIND = r"[a-z][a-z_]{1,31}"
# Any id of the suite's rule; ``valid_id`` checks it (docs/app-standard.md, section 2).
REF_PATTERN = re.compile(rf"^(?P<kind>{_KIND}):(?P<id>.+)$", re.DOTALL)
# What a mention in text can hold: "/" for runs (run:linkcraft/2026-10-19-0600).
_ID = r"[A-Za-z0-9][A-Za-z0-9_.:/\-]{0,127}"
MENTION_PATTERN = re.compile(
    rf"#\[(?P<label>[^\]\n]{{1,120}})\]\((?P<kind>{_KIND}):(?P<id>{_ID})\)"
    # A bare mention never ends in punctuation: "#loop:FIC-1." mentions FIC-1.
    rf"|#(?P<bare_kind>{_KIND}):(?P<bare_id>[A-Za-z0-9](?:[A-Za-z0-9_.:/\-]{{0,126}}[A-Za-z0-9])?)"
)

KIND_LABELS = {
    "asset": "Asset",
    "loop": "Loop",
    "signal": "Signal",
    "action": "Action",
    "execution": "Run",
    "job": "Run",
    "run": "Run",
    "protocol": "Protocol",
    "algorithm": "Algorithm",
    "block": "Block",
    "user": "Person",
    "group": "Group",
    "conversation": "Conversation",
    "chat": "Assistant chat",
    "dashboard": "Dashboard",
    "app": "App",
    "note": "Note",
    "todo": "To-do",
    "event": "Event",
}


def kind_label(kind: str) -> str:
    """The name of a kind of reference in the current language (the kind itself when unknown)."""

    label = KIND_LABELS.get(kind)
    return t(label) if label else kind


@dataclass(frozen=True)
class Ref:
    kind: str
    id: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}"


def parse_ref(text: str) -> Ref:
    match = REF_PATTERN.match(text.strip()) if isinstance(text, str) else None
    if match is None or not valid_id(match["id"]):
        raise ValueError(
            t("Invalid reference: {text}. Use kind:id, for example asset:FIC-101.", text=repr(text))
        )
    return Ref(match["kind"], match["id"])


def make_ref(kind: str, item_id: str) -> str:
    return str(parse_ref(f"{kind}:{item_id}"))


def find_refs(text: str) -> list[str]:
    """Every reference mentioned in a text, in order, without repeats."""

    found: list[str] = []
    for match in MENTION_PATTERN.finditer(text or ""):
        kind = match["kind"] or match["bare_kind"]
        item = match["id"] or match["bare_id"]
        ref = f"{kind}:{item}"
        if ref not in found:
            found.append(ref)
    return found


# (id) -> {"title": str, "href": str, "status": str | None, ...} or None when it does not exist.
Resolver = Callable[[str], dict[str, Any] | None]
# username -> (id -> whether that person may read what the item is: its title and state). Built
# once per reader, so a list of references checks the person's access once.
Guard = Callable[[str], Callable[[str], bool]]


class RefResolvers:
    """Who answers for each kind of reference."""

    def __init__(self) -> None:
        self._resolvers: dict[str, tuple[str, Resolver]] = {}
        # Kinds only some people may read (an action of another group): who asks decides.
        self._guards: dict[str, Guard] = {}
        # Answers for a whole reference no module owns (an app's text about its object).
        self.fallback: Callable[[str], dict[str, Any] | None] | None = None
        # The kinds the installed apps declare in [[contributes.refs]] (docs/app-standard.md,
        # 4b): kind -> {"app", "title", "url"} with "{id}" in the url, or None.
        self.declared: Callable[[str], dict[str, Any] | None] | None = None
        # username -> (app id -> whether they may open that app): an item an app answers for
        # (its model, its run, its text) names itself only to who opens the app (2026-10-27).
        self.app_guard: Guard | None = None

    def register(self, kind: str, resolver: Resolver, *, owner: str = "platform") -> None:
        self._resolvers[kind] = (owner, resolver)

    def guard(self, kind: str, sees: Guard) -> None:
        """Only people ``sees`` lets in read what a ``kind`` item is; anyone else (and a reader
        nobody named) gets its kind and number, like a private note."""

        self._guards[kind] = sees

    def kinds(self) -> list[str]:
        return sorted(self._resolvers)

    def reader(self, viewer: str | None) -> Callable[[str], bool]:
        """Whether ``viewer`` may read what a reference names (kinds without a guard: yes),
        checking the person's access once per kind however many references are asked."""

        checks: dict[str, Callable[[str], bool]] = {}
        answers: dict[str, bool] = {}
        opened: dict[str, bool] = {}

        def opens(app_id: str) -> bool:
            if self.app_guard is None:
                return True
            if viewer is None:
                return False
            if app_id not in opened:
                try:
                    if "" not in checks:
                        checks[""] = self.app_guard(viewer)
                    opened[app_id] = bool(checks[""](app_id))
                except Exception:  # a broken check hides rather than shows
                    opened[app_id] = False
            return opened[app_id]

        def sees(ref: str) -> bool:
            kind, _, item_id = ref.partition(":")
            guard = self._guards.get(kind)
            if guard is None:
                return True
            if viewer is None:
                return False
            if ref not in answers:
                try:
                    if kind not in checks:
                        checks[kind] = guard(viewer)
                    answers[ref] = bool(checks[kind](item_id))
                except Exception:  # a broken check hides rather than shows
                    answers[ref] = False
            return answers[ref]

        sees.opens = opens  # type: ignore[attr-defined]
        return sees

    def resolve(
        self,
        ref: str,
        *,
        viewer: str | None = None,
        sees: Callable[[str], bool] | None = None,
    ) -> dict[str, Any]:
        """What ``ref`` is, as ``viewer`` may read it (security review, 2026-10-26: an action's
        title reached people its group keeps it from through a link). ``sees``: a ``reader``
        already made for ``viewer``."""

        found = self._resolve(ref)
        if not found.get("exists"):
            return found
        app = found.get("app")
        if app and self.app_guard is not None:
            reader = sees if hasattr(sees, "opens") else self.reader(viewer)
            if not reader.opens(app):  # type: ignore[union-attr]
                return {
                    **found,
                    "title": f"{found['kind_label']} {found['id']}",
                    "href": None,
                    "status": None,
                    "hidden": True,
                }
        if found["kind"] not in self._guards:
            return found
        if (sees or self.reader(viewer))(found["ref"]):
            return found
        return {
            **found,
            "title": f"{found['kind_label']} {found['id']}",
            "status": None,
            "hidden": True,
        }

    def _resolve(self, ref: str) -> dict[str, Any]:
        parsed = parse_ref(ref)
        base = {
            "ref": str(parsed),
            "kind": parsed.kind,
            "id": parsed.id,
            "kind_label": kind_label(parsed.kind),
        }
        entry = self._resolvers.get(parsed.kind)
        declared = None
        if entry is None and self.declared is not None:
            try:
                declared = self.declared(parsed.kind)
            except Exception:  # a broken registry must not break the page that shows the link
                declared = None
        if declared is not None:
            base["kind_label"] = declared["title"]
            # An app's own kind written as the assistant writes any app's object
            # (``dashboard:dashcraft/<id>``) is the app's ``dashboard:<id>``.
            prefix = f"{declared['app']}/"
            if parsed.id.startswith(prefix) and len(parsed.id) > len(prefix):
                parsed = Ref(parsed.kind, parsed.id[len(prefix) :])
                base.update(ref=str(parsed), id=parsed.id)
        if entry is None and self.fallback is not None:
            try:
                found = self.fallback(str(parsed))
            except Exception:  # a broken lookup must not break the page that shows the link
                found = None
            if found is not None:
                return {**base, "available": True, "exists": True, "owner": "apps", **found}
        if entry is None and declared is not None:
            # The app's own kind: its page, named by the id until the app wrote a text about it.
            return {
                **base,
                "available": True,
                "exists": True,
                "owner": declared["app"],
                "title": parsed.id,
                "href": declared["url"].replace("{id}", quote(parsed.id, safe="")),
                "status": None,
                "app": declared["app"],
            }
        if entry is None:
            return {
                **base,
                "available": False,
                "exists": False,
                "title": parsed.id,
                "href": None,
                "reason": t("This item's module is not active in this installation."),
            }
        try:
            found = entry[1](parsed.id)
        except Exception:  # a broken resolver must not break the page that shows the link
            found = None
        if found is None:
            return {**base, "available": True, "exists": False, "title": parsed.id, "href": None}
        return {**base, "available": True, "exists": True, "owner": entry[0], **found}

    def resolve_many(
        self, refs: list[str], *, viewer: str | None = None
    ) -> dict[str, dict[str, Any]]:
        resolved = {}
        sees = self.reader(viewer)
        for ref in refs:
            try:
                resolved[ref] = self.resolve(ref, viewer=viewer, sees=sees)
            except ValueError:
                continue
        return resolved


__all__ = [
    "Guard",
    "KIND_LABELS",
    "MENTION_PATTERN",
    "Ref",
    "RefResolvers",
    "Resolver",
    "find_refs",
    "kind_label",
    "make_ref",
    "parse_ref",
]
