"""An import's next file in the catalog: its new tags become points, the file joins its list.

Both the server (a file a person checked and confirmed, ``api/routers/imports.py``) and the
collector (a file found in the folder an import repeats from, ``collector/imports.py``) add a
file to an import this way; the values are written by the collector afterwards.
"""

from __future__ import annotations

from typing import Any

from histcraft.catalog.models import IMPORT_KIND, CatalogError, PointIn
from histcraft.catalog.store import CatalogStore
from histcraft.i18n import t

# Files listed per import (the newest).
RUNS_KEPT = 50


def points_of(import_id: str, series: Any) -> list[PointIn]:
    return [
        PointIn(tag=item.tag, source_id=import_id, kind=item.kind, step=item.kind == "text")
        for item in series
    ]


def find(catalog: CatalogStore, import_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in catalog.sources()
            if item["id"] == import_id and item["kind"] == IMPORT_KIND
        ),
        None,
    )


def add_file(
    catalog: CatalogStore,
    source: dict[str, Any],
    table: Any,
    run: dict[str, Any],
    read: dict[str, Any],
) -> None:
    """Add one more file (``table``, read with ``read``) to the import ``source``: new tags
    become points, ``run`` heads its list of files. A tag whose kind changed is refused (409)."""

    import_id = source["id"]
    known = {point["tag"]: point for point in catalog.points(source_id=import_id)}
    clash = [
        item.tag
        for item in table.series.values()
        if item.tag in known and known[item.tag]["kind"] != item.kind
    ]
    if clash:
        raise CatalogError(
            t(
                "Tags that were numbers and are now text, or the reverse: {tags}",
                tags=", ".join(clash[:5]),
            ),
            409,
        )
    fresh = [item for item in table.series.values() if item.tag not in known]
    if fresh:
        try:
            catalog.add_points(points_of(import_id, fresh))
        except ValueError as exc:
            raise CatalogError(str(exc), 422) from exc
    options = source["options"]
    runs = [run, *(options.get("runs") or [])][:RUNS_KEPT]
    starts = [item["start_ms"] for item in runs if item.get("start_ms") is not None]
    ends = [item["end_ms"] for item in runs if item.get("end_ms") is not None]
    catalog.set_options(
        import_id,
        {
            **options,
            "file_name": run["file_name"],
            "bytes": run["bytes"],
            "sha256": run["sha256"],
            "shape": table.shape,
            "timezone": read["timezone"],
            "rows": sum(int(item.get("rows") or 0) for item in runs),
            "values": sum(int(item.get("values") or 0) for item in runs),
            "start_ms": min(starts) if starts else None,
            "end_ms": max(ends) if ends else None,
            "imported_by": run["by"],
            "warnings": run["warnings"],
            "read": read,
            "runs": runs,
        },
    )


def drop_newest(catalog: CatalogStore, source: dict[str, Any]) -> None:
    """Take the newest file off an import's list (a file cancelled before it was written)."""

    options = source["options"]
    runs = (options.get("runs") or [])[1:]
    if not runs:
        return
    last = runs[0]
    starts = [item["start_ms"] for item in runs if item.get("start_ms") is not None]
    ends = [item["end_ms"] for item in runs if item.get("end_ms") is not None]
    catalog.set_options(
        source["id"],
        {
            **options,
            "file_name": last.get("file_name", ""),
            "bytes": int(last.get("bytes") or 0),
            "sha256": last.get("sha256", ""),
            "rows": sum(int(item.get("rows") or 0) for item in runs),
            "values": sum(int(item.get("values") or 0) for item in runs),
            "start_ms": min(starts) if starts else None,
            "end_ms": max(ends) if ends else None,
            "imported_by": last.get("by", ""),
            "warnings": int(last.get("warnings") or 0),
            "runs": runs,
        },
    )
