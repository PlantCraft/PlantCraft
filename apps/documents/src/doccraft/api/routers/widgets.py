"""HTTP routes: Documents' widgets, for its Overview and Desk's Today (PlantCraft's
docs/widgets.md). Declared in app.toml ``[[contributes.widgets]]``; each answer is one of the
suite's shapes, built by ``plantcraft_sdk.widgets``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from plantcraft_sdk import widgets as w

from doccraft.api.deps import CurrentUser, RuntimeDep
from doccraft.i18n import t
from doccraft.meta import FILES

router = APIRouter(prefix="/api/widgets")


@router.get("")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(FILES.manifest(), t)


@router.get("/{widget_id}")
def widget(widget_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    root = rt.settings.root_path
    perms = rt.permissions(user)
    docs = perms.docs(rt.store.documents(perms.visible_folders()))
    if widget_id == "count":
        return w.number(len(docs), label=_count_label(docs), href=f"{root}/documents")
    if widget_id == "latest":
        return w.items(
            [
                w.item(
                    f"{doc['number']} {doc['title']}".strip(),
                    detail=" · ".join(
                        part for part in (t(doc["kind"]), _when(doc.get("updated_at"))) if part
                    ),
                    href=f"{root}/documents/{doc['doc_id']}",
                )
                for doc in docs[:8]
            ],
            href=f"{root}/documents",
            empty=t("No document yet."),
        )
    if widget_id == "reading":
        counts = rt.store.counts(rt.permissions(user).visible_folders())
        return w.items(
            [
                w.item(t("Indexed passages"), detail=str(counts["passages"])),
                w.item(t("Waiting to be read"), detail=str(counts["queued"])),
                w.item(t("Could not be read"), detail=str(counts["failed"])),
            ],
            href=f"{root}/documents",
        )
    if widget_id == "unlinked":
        unlinked = [doc for doc in docs if not any(a["source"] == "manual" for a in doc["assets"])]
        return w.items(
            [
                w.item(
                    f"{doc['number']} {doc['title']}".strip(),
                    detail=_tags_found(len(doc["assets"])),
                    href=f"{root}/documents/{doc['doc_id']}",
                )
                for doc in unlinked[:8]
            ],
            href=f"{root}/documents",
            empty=t("Every document is linked to its assets."),
        )
    raise HTTPException(status_code=404, detail=t("Widget not found."))


def _count_label(docs: list[dict[str, Any]]) -> str:
    """What the count holds: ready for search (read), being read (waiting or reading) and, when
    any, the files that could not be read; a library that is all read says so in one line."""

    if not docs:
        return t("documents")
    status = [doc.get("status") for doc in docs]
    ready = status.count("indexed")
    reading = sum(1 for item in status if item in ("queued", "indexing"))
    failed = status.count("failed")
    if ready == len(docs):
        return t("documents, all ready for search")
    parts = [t("documents"), t("{n} ready for search", n=ready)]
    if reading:
        parts.append(t("{n} being read", n=reading))
    if failed:
        parts.append(t("{n} could not be read", n=failed))
    return " · ".join(parts)


def _when(stamp: str | None) -> str:
    """When the document was sent or changed: "2 h ago" this week, its date before (owner,
    2026-10-27: the latest documents say when)."""

    if not stamp:
        return ""
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if datetime.now(UTC) - moment < timedelta(days=7):
        return w.ago(moment, t) or ""
    return moment.date().isoformat()


def _tags_found(n: int) -> str:
    if n == 0:
        return t("No tag found")
    return t("1 tag found") if n == 1 else t("{n} tags found", n=n)
