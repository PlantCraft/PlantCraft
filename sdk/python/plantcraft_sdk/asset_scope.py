"""The part of the plant a person sees, for an app that answers from its own store
(PlantCraft's docs/asset-scope.md, decision D2, 2026-10-27).

PlantCraft gives a person, or a group, the roots of the asset tree they see; the person's token
carries them in the claim ``assets`` (absent: the whole plant). API v1 already answers that
person only about those assets. An app that answers people from its own database (the
Historian's trends, View's panels, Alarms' alarms, Analytics' loops) keeps the same ones::

    from plantcraft_sdk.asset_scope import scope_of

    scope = scope_of(user, runtime.client)      # once per request
    rows = [row for row in rows if scope.subject(row["subject"])]

``scope_of`` asks PlantCraft, with the person's own token, which assets and signals they see
(already filtered there) and keeps the answer a minute. Everyone else (no claim, an
administrator, an app's own token) sees the whole plant and costs nothing.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

CLAIM = "assets"
# How long one person's answer is kept (a change of scope ends their token anyway).
CACHE_SECONDS = 60.0
CACHE_SIZE = 512
_PLANT_KINDS = ("asset", "signal")


@dataclass(frozen=True)
class AssetScope:
    """The assets and signals one reader sees; ``roots is None`` is the whole plant."""

    roots: tuple[str, ...] | None = None
    assets: frozenset[str] = frozenset()
    # Signal ids as API v1 gives them (``<source>:<tag>``, ``app-<app>:<name>``).
    signals: frozenset[str] = frozenset()
    # The tag of each signal id, so a bare tag (an app's older reference) matches too.
    tags: frozenset[str] = field(default=frozenset())

    @property
    def everything(self) -> bool:
        return self.roots is None

    def asset(self, asset_id: str | None) -> bool:
        return self.everything or (asset_id is not None and asset_id in self.assets)

    def signal(self, signal_id: str | None) -> bool:
        """A signal by its API v1 id or its bare tag."""

        if self.everything:
            return True
        if not signal_id:
            return False
        return signal_id in self.signals or signal_id in self.tags

    def subject(self, subject: str | None) -> bool:
        """A subject (``asset:<id>``, ``signal:<id>``); anything else is not about the plant."""

        if self.everything or not subject:
            return True
        kind, sep, item = str(subject).partition(":")
        if not sep:
            return True
        if kind == "asset":
            return item in self.assets
        if kind == "signal":
            return self.signal(item)
        return True

    def refs(self, refs: Iterable[str]) -> bool:
        """Whether something that names ``refs`` stays in scope: it names no asset or signal,
        or one of those it names is in scope."""

        if self.everything:
            return True
        plant = [ref for ref in refs if str(ref).partition(":")[0] in _PLANT_KINDS]
        return not plant or any(self.subject(ref) for ref in plant)

    def all_signals(self, signals: Iterable[str]) -> bool:
        """Whether every signal of a list (a panel's, a rule's) is in scope: a panel drawing
        one hidden tag would show it."""

        return self.everything or all(self.signal(item) for item in signals)


EVERYTHING = AssetScope()
NOTHING = AssetScope(roots=())

_cache: dict[tuple[str, int, tuple[str, ...]], tuple[float, AssetScope]] = {}
_lock = threading.Lock()


def roots_of(claims: dict[str, Any] | None) -> tuple[str, ...] | None:
    """The roots in a token's claims; None for the whole plant (no claim, an administrator,
    an app's own token)."""

    claims = claims or {}
    if str(claims.get("sub") or "").startswith("app:") or claims.get("level") == "admin":
        return None
    roots = claims.get(CLAIM)
    if not isinstance(roots, list):
        return None
    return tuple(str(item) for item in roots)


def limited(user: Any) -> bool:
    """Whether ``user`` sees only part of the plant (their token carries ``assets``). Something
    an app later does with its own token on their behalf (a public link, a scheduled send)
    would read past that part, so such a person does not set it up."""

    return roots_of(getattr(user, "claims", None)) is not None


def _tag(signal_id: str) -> str:
    return signal_id.partition(":")[2] or signal_id


def build(roots: tuple[str, ...], assets: Iterable[Any], signals: Iterable[Any]) -> AssetScope:
    """A scope from what PlantCraft answered the person (``/api/v1/assets`` and ``/signals``)."""

    ids = frozenset(str(item.get("id")) for item in assets if isinstance(item, dict))
    found = frozenset(str(item.get("id")) for item in signals if isinstance(item, dict))
    return AssetScope(
        roots=roots,
        assets=ids,
        signals=found,
        tags=frozenset(_tag(item) for item in found),
    )


def scope_of(user: Any, client: Any) -> AssetScope:
    """What ``user`` (``plantcraft_sdk.auth.User``) sees, asked of PlantCraft with their own
    token through ``client`` (``PlantCraftClient``) and kept a minute. If PlantCraft cannot
    say, nothing of the plant: a person limited to part of it never reads more by an outage."""

    return scope_for(getattr(user, "claims", None) or {}, getattr(user, "token", ""), client)


def scope_for(claims: dict[str, Any], token: str, client: Any) -> AssetScope:
    """``scope_of`` from a token's verified claims and the token itself."""

    roots = roots_of(claims)
    if roots is None:
        return EVERYTHING
    if not roots:
        return NOTHING
    key = (str(claims.get("sub") or ""), int(claims.get("iat") or 0), roots)
    now = time.monotonic()
    with _lock:
        kept = _cache.get(key)
        if kept is not None and kept[0] > now:
            return kept[1]
    try:
        own = client.with_token(token)
        # Straight to PlantCraft (never a Historian's direct reads): it applies the scope.
        assets = own._all_pages(own._exchange, "/api/v1/assets", {})
        signals = own._all_pages(own._exchange, "/api/v1/signals", {})
        scope = build(roots, assets, signals)
    except Exception:  # PlantCraft down or the token refused: nothing rather than everything
        return NOTHING
    with _lock:
        if len(_cache) >= CACHE_SIZE:
            for old in sorted(_cache, key=lambda item: _cache[item][0])[: CACHE_SIZE // 4]:
                _cache.pop(old, None)
        _cache[key] = (now + CACHE_SECONDS, scope)
    return scope


def forget() -> None:
    """Drop every kept answer (tests)."""

    with _lock:
        _cache.clear()


__all__ = [
    "CLAIM",
    "EVERYTHING",
    "NOTHING",
    "AssetScope",
    "build",
    "forget",
    "limited",
    "roots_of",
    "scope_for",
    "scope_of",
]
