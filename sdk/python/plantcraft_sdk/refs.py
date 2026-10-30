"""References the suite writes the same way everywhere (``docs/app-standard.md``, section 2).

=========  ============================  ==============================
Kind       Form                          Example
=========  ============================  ==============================
asset      ``asset:<asset id>``          ``asset:u200-fic1001``
signal     ``signal:<source id>:<tag>``  ``signal:pi:FIC1001.PV``
person     ``user:<user name>``          ``user:ana.lima``
run        ``run:<app id>/<run id>``     ``run:linkcraft/2026-10-19-0600``
=========  ============================  ==============================

::

    from plantcraft_sdk.refs import format_ref, parse_ref

    ref = parse_ref("signal:pi:FIC1001.PV")    # Ref(kind="signal", id="FIC1001.PV", source="pi")
    ref.signal_id                              # "pi:FIC1001.PV", the API v1 signal id
    format_ref("run", "2026-10-19-0600", app="linkcraft")    # "run:linkcraft/2026-10-19-0600"

Signals are named with their source: a signal id of API v1 is
``<source id>:<tag>`` and its reference ``signal:<source id>:<tag>``. A
signal reference whose text before the first ``:`` after ``signal:`` is a
source id (lower-case letters, digits, ``_`` and ``-``, as PlantCraft gives
them) is read as ``<source>:<tag>``; anything else is a bare tag (the form
before the rename, still read until API v1 is frozen), with ``source`` None.

Ids are written as they are, never percent-encoded: a tag keeps its spaces,
``/``, ``\\`` and ``:`` (PI and OPC UA tags hold them). An id is 1 to 300
visible characters without spaces at either end (``check_id``); compare
references as text. Only URLs encode them (``quote(id, safe="")``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KINDS = ("asset", "signal", "user", "run")
# Source ids as PlantCraft gives them (``pi``, ``scenario``, ``opcua-1``, ``2-pi``).
SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
APP_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")
MAX_ID = 300
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class RefError(ValueError):
    """Text that is not a reference of the suite."""


@dataclass(frozen=True)
class Ref:
    """A parsed reference. ``id`` is the asset id, tag, user name or run id."""

    kind: str
    id: str
    # Signals: the source id (None for a bare tag, the form before the rename).
    source: str | None = None
    # Runs: the app that ran it.
    app: str | None = None

    def __str__(self) -> str:
        return format_ref(self.kind, self.id, source=self.source, app=self.app)

    @property
    def signal_id(self) -> str:
        """A signal's API v1 id: ``<source>:<tag>`` (the bare tag when it has no source)."""

        if self.kind != "signal":
            raise RefError(f"A {self.kind} reference is not a signal.")
        return f"{self.source}:{self.id}" if self.source else self.id


def valid_id(value: object) -> bool:
    """1 to ``MAX_ID`` characters, no control characters, no spaces at either end."""

    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_ID
        and value == value.strip()
        and not _CONTROL.search(value)
    )


def check_id(kind: str, value: str) -> str:
    """``value`` when it is a valid id of a ``kind`` reference; raises ``RefError``."""

    if not valid_id(value):
        raise RefError(f"Invalid {kind} reference: the id is 1 to {MAX_ID} visible characters.")
    return value


def format_ref(kind: str, id: str, *, source: str | None = None, app: str | None = None) -> str:
    """The reference text of ``kind`` and ``id`` (``source`` for signals, ``app`` for runs)."""

    if kind not in KINDS:
        raise RefError(f"Unknown reference kind {kind!r}: use one of {', '.join(KINDS)}.")
    check_id(kind, id)
    if kind == "signal":
        if source is None:
            return f"signal:{id}"
        if not SOURCE_ID.match(source):
            raise RefError(f"Invalid source id {source!r}.")
        return f"signal:{source}:{id}"
    if kind == "run":
        if not app or not APP_ID.match(app):
            raise RefError("A run reference needs the app id: run:<app id>/<run id>.")
        if not RUN_ID.match(id):
            raise RefError(f"Invalid run id {id!r}.")
        return f"run:{app}/{id}"
    if source is not None or app is not None:
        raise RefError(f"A {kind} reference has no source or app.")
    return f"{kind}:{id}"


def parse_ref(text: str) -> Ref:
    """``Ref`` of an asset, signal, person or run reference; raises ``RefError``."""

    if not isinstance(text, str):
        raise RefError("A reference is text, like asset:<id>.")
    kind, sep, rest = text.partition(":")
    if not sep or kind not in KINDS:
        raise RefError(f"Invalid reference {text!r}: use {', '.join(k + ':...' for k in KINDS)}.")
    if kind == "signal":
        source, tag = split_signal_id(rest)
        return Ref("signal", check_id(kind, tag), source=source)
    if kind == "run":
        app, sep, run_id = rest.partition("/")
        if not sep or not APP_ID.match(app) or not RUN_ID.match(run_id):
            raise RefError(f"Invalid run reference {text!r}: use run:<app id>/<run id>.")
        return Ref("run", run_id, app=app)
    return Ref(kind, check_id(kind, rest))


def split_signal_id(signal_id: str) -> tuple[str | None, str]:
    """``(source, tag)`` of an API v1 signal id; ``(None, tag)`` for a bare tag."""

    source, sep, tag = signal_id.partition(":")
    if sep and SOURCE_ID.match(source) and tag:
        return source, tag
    return None, signal_id


def asset_ref(asset_id: str) -> str:
    return format_ref("asset", asset_id)


def signal_ref(tag: str, source: str | None = None) -> str:
    """``signal:<source>:<tag>``; with no ``source``, ``tag`` may be an API v1 signal id."""

    if source is None:
        source, tag = split_signal_id(tag)
    return format_ref("signal", tag, source=source)


def user_ref(username: str) -> str:
    return format_ref("user", username)


def run_ref(app: str, run_id: str) -> str:
    return format_ref("run", run_id, app=app)


__all__ = [
    "KINDS",
    "Ref",
    "RefError",
    "asset_ref",
    "check_id",
    "format_ref",
    "parse_ref",
    "run_ref",
    "signal_ref",
    "split_signal_id",
    "user_ref",
    "valid_id",
]
