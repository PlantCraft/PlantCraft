"""What part of the plant a person sees: their asset scope (docs/asset-scope.md).

A person, and a group, may be given the roots of the asset tree they see ("U-100", "Utilities").
A person sees the assets under their own roots and under the roots of their groups that have
some; a group without a scope never widens anything. Nobody with roots anywhere sees the whole
plant, as before scopes existed; so do administrators and apps' own tokens.

Everything the platform keeps about the plant follows the assets: a signal is in scope when it is
bound to an asset in scope (a derived signal, when its subject is), and a result, event or run
when its subject is. A signal bound to no asset is out of every scope: a contractor of one unit
never reads a tag nobody placed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from plantcraft_sdk.derived import split_derived

# The token claim that carries a person's roots (absent: the whole plant).
CLAIM = "assets"
# Roots one person or group may be given: whole units and areas, not a list of tags.
MAX_SCOPE_ROOTS = 50


@dataclass(frozen=True)
class AssetScope:
    """The assets one reader sees; ``roots is None`` is the whole plant."""

    roots: tuple[str, ...] | None = None
    assets: frozenset[str] = frozenset()
    # Tags bound to an asset in scope (the platform binds signals by tag).
    tags: frozenset[str] = frozenset()
    # The subject of a derived signal, looked up only when a bare id is checked.
    derived_subject: Callable[[str], str | None] = field(default=lambda _signal: None)

    @property
    def everything(self) -> bool:
        return self.roots is None

    def asset(self, asset_id: str | None) -> bool:
        return self.everything or (asset_id is not None and asset_id in self.assets)

    def signal(self, signal_id: str, *, subject: str | None = None) -> bool:
        """A signal by its API v1 id (``<source>:<tag>``, a bare tag, or a derived signal)."""

        if self.everything:
            return True
        if split_derived(signal_id) is not None:
            subject = subject if subject is not None else self.derived_subject(signal_id)
            return bool(subject) and self.subject(subject)
        if signal_id in self.tags:
            return True
        _source, sep, tag = signal_id.partition(":")
        return bool(sep) and tag in self.tags

    def signal_item(self, item: dict[str, Any]) -> bool:
        """A signal as API v1 lists it (``id``, and ``subject`` for a derived one)."""

        return self.signal(str(item.get("id") or ""), subject=item.get("subject") or "")

    def subject(self, subject: str | None) -> bool:
        """A subject (``asset:<id>`` or ``signal:<id>``); anything else is not about the plant."""

        if self.everything or not subject:
            return True
        kind, sep, item = subject.partition(":")
        if not sep:
            return True
        if kind == "asset":
            return item in self.assets
        if kind == "signal":
            return self.signal(item)
        return True

    def refs(self, refs: Iterable[str]) -> bool:
        """Whether a set of references stays in scope: none names an asset or signal, or one
        of those it names is in scope."""

        if self.everything:
            return True
        plant = [ref for ref in refs if ref.partition(":")[0] in {"asset", "signal"}]
        return not plant or any(self.subject(ref) for ref in plant)

    def __and__(self, other: AssetScope) -> AssetScope:
        """What two readers both see (a conversation's answer reads no more than that)."""

        if self.everything:
            return other
        if other.everything:
            return self
        return AssetScope(
            roots=tuple(sorted(set(self.roots or ()) | set(other.roots or ()))),
            assets=self.assets & other.assets,
            tags=self.tags & other.tags,
            derived_subject=self.derived_subject,
        )

    def items(self, assets: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """The assets in scope of a list of the store's items; a root's parent out of scope
        reads as none, so the tree starts at the person's roots."""

        if self.everything:
            return list(assets)
        return [
            item if item.get("parent_id") in self.assets else {**item, "parent_id": None}
            for item in assets
            if item["asset_id"] in self.assets
        ]

    def claim(self) -> dict[str, list[str]]:
        """The token claim: nothing for the whole plant."""

        return {} if self.roots is None else {CLAIM: list(self.roots)}


EVERYTHING = AssetScope()


def scope_roots(workspace: Any, username: str) -> tuple[str, ...] | None:
    """The roots ``username`` sees: their own and their scoped groups'; None for the whole
    plant (administrators are not asked: the caller knows the level)."""

    user = workspace.users.get_user(username) or {}
    own = user.get("asset_scope")
    groups = workspace.groups.asset_scopes_of(username)
    if own is None and not groups:
        return None
    roots: set[str] = set(own or [])
    for found in groups:
        roots |= set(found)
    return tuple(sorted(roots))


def build_scope(
    workspace: Any,
    roots: tuple[str, ...] | None,
    *,
    derived_subject: Callable[[str], str | None] | None = None,
) -> AssetScope:
    """The scope of ``roots``: every asset under them and the tags bound to those assets."""

    if roots is None:
        return EVERYTHING
    store = workspace.assets
    children: dict[str | None, list[str]] = {}
    known: set[str] = set()
    for item in store.list():
        known.add(item["asset_id"])
        children.setdefault(item["parent_id"], []).append(item["asset_id"])
    assets: set[str] = set()
    pending = [root for root in roots if root in known]
    while pending:
        current = pending.pop()
        if current in assets:
            continue
        assets.add(current)
        pending.extend(children.get(current, []))
    tags = {
        tag
        for tag, uses in store.signal_assets().items()
        if any(use["asset_id"] in assets for use in uses)
    }
    return AssetScope(
        roots=roots,
        assets=frozenset(assets),
        tags=frozenset(tags),
        derived_subject=derived_subject or (lambda _signal: None),
    )


def check_roots(workspace: Any, roots: list[str] | None) -> list[str] | None:
    """The roots as given, without repeats; ``ValueError`` names one that is not an asset."""

    if roots is None:
        return None
    cleaned = list(dict.fromkeys(str(root).strip() for root in roots if str(root).strip()))
    for root in cleaned:
        if workspace.assets.get(root) is None:
            raise ValueError(root)
    return cleaned
