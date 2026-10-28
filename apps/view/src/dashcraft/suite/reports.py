"""What View tells PlantCraft about its reports, through API v1:

- each send, to its recipients: a notification in Messages (``POST /api/v1/notifications``), one
  thread per report (``key``), with the PDF one click away;
- the events ``dashcraft.report.sent`` and ``dashcraft.report.failed`` (``[[publishes.events]]``);
- its runs and schedules, for PlantCraft's Executions page (``PUT /api/v1/runs``,
  ``PUT /api/v1/schedules``);
- the coming sends on Desk's calendar, feed ``reports`` (``[[contributes.calendar]]``), each for the
  people and groups the report goes to.

None of it ever stops a report: a refusal is logged and the PDF stays in View.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.desk import MAX_FEED_ITEMS
from plantcraft_sdk.events import EventCatalog

from dashcraft.i18n import t
from dashcraft.meta import manifest

LOGGER = logging.getLogger(__name__)
FEED = "reports"
SENT = "report.sent"
FAILED = "report.failed"
SUBJECT = "app:dashcraft"


def time_zone(client: Any) -> str:
    """The installation's time zone (``PLANTCRAFT_TIMEZONE``), UTC when it cannot be read."""

    if client is None:
        return "UTC"
    try:
        return client.installation_time_zone() or "UTC"
    except (PlantCraftError, AttributeError, ValueError):
        return "UTC"


def deliver(client: Any, report: dict[str, Any], run: dict[str, Any], url: str, period: str) -> int:
    """The notification of one send to each recipient (``period`` in the plant's words, "24 Oct
    06:00 to 25 Oct 06:00"); how many people it reached."""

    recipients = list(report.get("recipients") or [])
    if client is None or not recipients:
        return 0
    problems = int(run.get("problems") or 0)
    text = t("From {period}.", period=period)
    if problems:
        text += " " + unread(problems)
    try:
        answer = client.notify(
            recipients,
            t("Report: {name}", name=report["name"]),
            text,
            priority="low",
            url=url,
            email=bool(report.get("email")),
            refs=[f"run:dashcraft/{run['run_id']}"],
            key=f"report:{report['report_id']}",
            category="info",
            actions=[{"label": t("Open the PDF"), "href": url}],
        )
    except PlantCraftError as exc:
        LOGGER.warning("Report %s not delivered: %s", report.get("report_id"), exc)
        return 0
    delivered = (answer or {}).get("delivered") or []
    return len(delivered) if isinstance(delivered, list) else int(delivered or 0)


def unread(problems: int) -> str:
    """How many sections could not be read in full, in words."""

    if problems == 1:
        return t("1 section could not be read in full.")
    return t("{n} sections could not be read in full.", n=problems)


def _post(
    client: Any,
    name: str,
    report: dict[str, Any],
    run: dict[str, Any],
    summary: str,
    **payload: Any,
) -> None:
    if client is None:
        return
    try:
        event = EventCatalog.from_manifest(manifest()).event(
            name,
            SUBJECT,
            summary=summary[:300],
            refs=[f"run:dashcraft/{run['run_id']}"],
            payload={
                "report": report["report_id"],
                "name": report["name"],
                "run": run["run_id"],
                **payload,
            },
        )
        client.post_events([event])
    except (PlantCraftError, ValueError, KeyError) as exc:
        LOGGER.warning("Event %s not written: %s", name, exc)


def sent(
    client: Any, report: dict[str, Any], run: dict[str, Any], delivered: int, url: str
) -> None:
    _post(
        client,
        SENT,
        report,
        run,
        t("{name} sent to {n} people", name=report["name"], n=delivered)
        if delivered != 1
        else t("{name} sent to 1 person", name=report["name"]),
        recipients=", ".join(report.get("recipients") or []),
        delivered=delivered,
        problems=int(run.get("problems") or 0),
        url=url,
    )


def failed(client: Any, report: dict[str, Any], run: dict[str, Any], url: str) -> None:
    _post(
        client,
        FAILED,
        report,
        run,
        t(
            "{name} could not be made: {error}",
            name=report["name"],
            error=run.get("error") or t("unknown error"),
        ),
        error=run.get("error") or "",
        url=url,
    )


def publish_runs(client: Any, runs: list[dict[str, Any]], root: str) -> None:
    """The reports' recent runs on PlantCraft's Executions page, each linking its PDF."""

    if client is None or not runs:
        return
    items = [
        {
            "id": run["run_id"],
            "name": run["report_name"],
            "status": {"running": "running", "done": "done"}.get(run["status"], "failed"),
            "trigger": "schedule" if run["trigger"] == "schedule" else "manual",
            "started_at": run["started_at"],
            "finished_at": run.get("finished_at"),
            "subjects": [],
            "summary": (run.get("error") or run.get("summary") or "")[:300],
            "url": f"{root}/reports/{run['report_id']}?run={run['run_id']}",
        }
        for run in runs
    ]
    try:
        client.put_runs(items)
    except PlantCraftError as exc:
        LOGGER.warning("Report runs not sent: %s", exc)


def publish_schedules(client: Any, items: list[dict[str, Any]], root: str) -> None:
    """The whole list of scheduled reports (a PUT replaces View's list)."""

    if client is None:
        return
    body = [
        {
            "id": item["report_id"],
            "name": item["name"],
            "cadence": item["cadence"],
            "next_run": item.get("next_run_at"),
            "enabled": bool(item.get("next_run_at")),
            "url": f"{root}/reports/{item['report_id']}",
        }
        for item in items
    ]
    try:
        client.put_schedules(body)
    except PlantCraftError as exc:
        LOGGER.warning("Report schedules not sent: %s", exc)


def publish_calendar(client: Any, items: list[dict[str, Any]]) -> None:
    """The coming sends: ``[{report, at: [datetime], url}]``, one item per send and recipient
    (a report for everyone when it names nobody)."""

    if client is None:
        return
    feed: list[dict[str, Any]] = []
    for item in items:
        report = item["report"]
        audiences = list(report.get("recipients") or []) or ["everyone"]
        for at in item["at"]:
            for audience in audiences:
                if len(feed) >= MAX_FEED_ITEMS:
                    break
                feed.append(
                    {
                        "id": f"{report['report_id']}:{_stamp(at)}:{audience}"[:200],
                        "title": t("Report: {name}", name=report["name"]),
                        "start": _stamp(at),
                        "audience": audience,
                        "ref": f"report:{report['report_id']}",
                        "url": item["url"],
                        "detail": (report.get("description") or "")[:300],
                    }
                )
    try:
        client.put_calendar(FEED, feed)
    except PlantCraftError as exc:
        LOGGER.warning("Calendar feed %s not sent: %s", FEED, exc)


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")
