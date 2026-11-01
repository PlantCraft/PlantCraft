"""The events Models writes, by the names its ``app.toml`` declares (``[[publishes.events]]``),
through ``EventCatalog``: a name or a payload field the manifest does not declare is refused here,
before PlantCraft sees it. Models reports; the Alarms app decides whether anyone hears it."""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.events import EventCatalog

from modelcraft import APP_ID
from modelcraft.meta import manifest

SUBJECT = f"app:{APP_ID}"


def _send(client: Any, name: str, summary: str, payload: dict[str, Any]) -> None:
    event = EventCatalog.from_manifest(manifest()).event(
        name, SUBJECT, summary=summary[:300], payload=payload
    )
    client.post_events([event])


def tracking_mismatch(client: Any, changes: list[dict[str, Any]]) -> None:
    """A tracking's variables off the plant past their limit (``start``) or back (``end``):
    one ``tracking.mismatch`` condition each, key ``tracking:<id>:<variable>``."""

    catalog = EventCatalog.from_manifest(manifest())
    client.post_events(
        [
            catalog.event(
                "tracking.mismatch",
                SUBJECT,
                summary=item["summary"][:300],
                payload=item["payload"],
                key=item["key"],
                phase=item["phase"],
                severity="warning" if item["phase"] == "start" else "ok",
            )
            for item in changes
        ]
    )


def run_failed(client: Any, run: dict[str, Any], name: str, root_path: str) -> None:
    _send(
        client,
        "run.failed",
        f"{name}: {run.get('summary') or 'failed'}",
        {
            "run_id": run["id"],
            "model": run["model"],
            "kind": run["kind"],
            "by": run.get("created_by") or "",
            "url": f"{root_path}/runs/{run['id']}",
        },
    )


def study_finished(
    client: Any, study: dict[str, Any], counts: dict[str, int], root_path: str
) -> None:
    done, failed = counts.get("done", 0), counts.get("failed", 0)
    _send(
        client,
        "study.finished",
        f"Study {study.get('name') or study['id']}: {done} done, {failed} failed",
        {
            "study_id": study["id"],
            "done": done,
            "failed": failed,
            "url": f"{root_path}/studies/{study['id']}",
        },
    )
