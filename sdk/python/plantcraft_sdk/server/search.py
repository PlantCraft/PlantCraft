"""An app's part of the suite's search (Ctrl+K, docs/app-standard.md section 10).

The frame every app draws asks each app ``GET <prefix>/api/search?q=<text>&limit=<n>`` at once
and lists the answers by app. An app answers for its own objects only, with the person's
access, quickly and never with an error::

    from plantcraft_sdk.server.search import SearchItem, search_answer, search_text

    @router.get("/api/search")
    def search(_user: CurrentUser, rt: RuntimeDep, q: str = Query("", max_length=120),
               limit: int = Query(6, ge=1, le=20)) -> dict:
        text = search_text(q)
        if not text:
            return search_answer([])
        found = [SearchItem(row["name"], "/dashboards/" + row["id"], type=t("Dashboard"),
                            detail=row["folder"]) for row in rt.store.dashboards()
                 if matches(text, row["name"], row["description"])]
        return search_answer(found, text, limit=limit)

``search_answer`` ranks the items (an exact title first, then titles that start with the text,
then the rest, each in the order given), cuts them to ``limit`` and to size, and writes the
format ``plantcraft-search/1`` the frame reads.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

FORMAT = "plantcraft-search/1"
MIN_LETTERS = 2


@dataclass(frozen=True)
class SearchItem:
    """One answer: ``title`` what the person looks for, ``href`` a path inside the app,
    ``type`` the kind of object in the person's language, ``detail`` one more line."""

    title: str
    href: str
    type: str | None = None
    detail: str | None = None


def search_text(q: str | None) -> str:
    """The text to search for, its spaces folded; empty under two letters (nobody is asked)."""

    text = " ".join((q or "").split())
    return text if len(text) >= MIN_LETTERS else ""


def matches(text: str, *fields: Any) -> bool:
    """True when every word of ``text`` is in one of the ``fields``, in any case."""

    haystack = " ".join(str(field) for field in fields if field not in (None, "")).casefold()
    return all(word in haystack for word in text.casefold().split())


def rank(text: str, title: str) -> int:
    """0 for an exact title, 1 for a title that starts with the text, 2 for the rest."""

    folded, wanted = title.casefold(), text.casefold()
    return 0 if folded == wanted else 1 if folded.startswith(wanted) else 2


def search_answer(items: Iterable[SearchItem], text: str = "", *, limit: int = 6) -> dict[str, Any]:
    """The body of ``GET /api/search``: the items ranked against ``text`` and cut to ``limit``."""

    ordered = sorted(enumerate(items), key=lambda pair: (rank(text, pair[1].title), pair[0]))
    answer = []
    for _, item in ordered[: max(0, limit)]:
        href = item.href if item.href.startswith("/") else f"/{item.href}"
        answer.append(
            {
                "title": item.title[:120],
                "detail": (item.detail or "")[:160] or None,
                "type": (item.type or "")[:40] or None,
                "href": href,
            }
        )
    return {"format": FORMAT, "items": answer}
