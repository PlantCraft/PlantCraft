"""The reports' rules, without HTTP: make a report's PDF, keep it, send it, and keep its schedule.

A report is made three ways (a run's ``trigger``):

- ``schedule``: when its next send comes (``ReportScheduler``), read with View's service token
  like a saved dashboard, and sent to its recipients;
- ``send``: a person's Send now, read the same way and sent;
- ``download``: a person's Download PDF, made and kept but sent to nobody.

Each run keeps its PDF (``reports.store``). What the suite hears of it goes through
``dashcraft.suite``: the notification, the event, the run and the coming sends on Desk's
calendar. Only this module and the routers' calls into it change reports.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.client import Unauthorized
from plantcraft_sdk.utc import utc_iso

from dashcraft.dashboards.model import window_seconds
from dashcraft.delivery.read import read_sections
from dashcraft.i18n import t
from dashcraft.query.cards import Reader
from dashcraft.reports import assistant as helper
from dashcraft.reports import document, docx, html, pdf, text
from dashcraft.reports.model import ReportPayload, Schedule
from dashcraft.reports.schedule import cadence, closed_period, next_run, runs_between
from dashcraft.reports.store import ReportStore
from dashcraft.suite import Suite
from dashcraft.suite.reports import unread

LOGGER = logging.getLogger(__name__)
# How often the installation's time zone is read again, and how far ahead Desk's calendar shows
# the coming sends.
ZONE_SECONDS = 600.0
CALENDAR_DAYS = 31


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReportService:
    def __init__(
        self,
        store: ReportStore,
        suite: Suite,
        *,
        root: str,
        clock: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.suite = suite
        self.root = root
        self.clock = clock or _utc_now
        self._zone: tuple[float, str] | None = None
        self._lock = threading.Lock()

    # Time --------------------------------------------------------------------------------

    def zone(self) -> str:
        """The installation's time zone, read from PlantCraft at most every 10 minutes."""

        now = time.monotonic()
        if self._zone is None or now - self._zone[0] > ZONE_SECONDS:
            self._zone = (now, self.suite.time_zone())
        return self._zone[1]

    def next_run(self, payload: dict[str, Any]) -> datetime | None:
        schedule = Schedule.model_validate(payload.get("schedule") or {})
        return next_run(schedule, self.clock(), self.zone())

    def span(
        self, report: dict[str, Any], reader: Reader
    ) -> tuple[Reader, str, datetime, datetime]:
        """What a report made now reads: the reader, the period as a window, its start and end.
        The report's period ending now; or, when the schedule asks for whole calendar periods,
        the last one (last week, last month) with every read pinned to its end."""

        now = reader.clock()
        closed = closed_period(
            Schedule.model_validate(report.get("schedule") or {}), now, self.zone()
        )
        if closed is None:
            period = report.get("period") or "24h"
            return reader, period, now - timedelta(seconds=window_seconds(period)), now
        start, end = closed
        hours = round((end - start).total_seconds() / 3600)
        return reader.until(end), f"{hours}h", start, end

    def cadence(self, report: dict[str, Any]) -> str:
        return cadence(Schedule.model_validate(report.get("schedule") or {}))

    def describe(self, report: dict[str, Any]) -> dict[str, Any]:
        """A report as the interface lists it: with its cadence and its last run."""

        end = self.clock()
        start = end - timedelta(seconds=window_seconds(report.get("period") or "24h"))
        return {
            **report,
            "cadence": self.cadence(report),
            "zone": self.zone(),
            # What the report covers if made now (the page's heading says so).
            "covers": {"start": utc_iso(start), "end": utc_iso(end)},
        }

    # Saving -------------------------------------------------------------------------------

    def create(self, payload: ReportPayload, by: str) -> dict[str, Any]:
        stored = payload.stored()
        created = self.store.create(stored, by, self.next_run(stored))
        self.sync()
        return created

    def update(self, report_id: str, payload: ReportPayload, by: str) -> dict[str, Any] | None:
        stored = payload.stored()
        saved = self.store.update(
            report_id, stored, by, self.next_run(stored), base_updated_at=payload.base_updated_at
        )
        self.sync()
        return saved

    def delete(self, report_id: str) -> bool:
        removed = self.store.delete(report_id)
        self.sync()
        return removed

    # Making and sending --------------------------------------------------------------------

    def period_text(self, run: dict[str, Any]) -> str:
        clock = pdf.Clock(self.zone())
        return t(
            "{start} to {end}",
            start=clock.text(run.get("period_start"), "%d %b %H:%M"),
            end=clock.text(run.get("period_end"), "%d %b %H:%M"),
        )

    def make(
        self, report: dict[str, Any], reader: Reader, *, trigger: str, by: str | None
    ) -> dict[str, Any]:
        """Read every section over the report's period, ending now, and keep the PDF. A failure
        is kept as a failed run with its reason, never raised (but a refused token, 401)."""

        made_at = reader.clock()
        reader, period, start, end = self.span(report, reader)
        run = self.store.start_run(
            report, trigger=trigger, by=by, period_start=start, period_end=end
        )
        try:
            items, problems = read_sections(
                reader, report.get("sections") or [], period, self.writer(report)
            )
            document = pdf.render(
                report,
                items,
                {
                    "start": start,
                    "end": end,
                    "made_at": made_at,
                    "zone": self.zone(),
                    "cadence": self.cadence(report),
                    "problems": problems,
                },
            )
        except Unauthorized as exc:
            self.store.finish_run(run["run_id"], status="failed", error=str(exc.detail))
            raise
        except Exception as exc:  # noqa: BLE001 - a report that cannot be made says why
            LOGGER.exception("Report %s not made", report.get("report_id"))
            return self.store.finish_run(
                run["run_id"],
                status="failed",
                error=t("The PDF could not be made: {error}", error=str(exc)[:300]),
            )
        summary = unread(problems) if problems else t("Every section read.")
        for item in items:
            written = item.get("assistant")
            if written and written.get("text"):
                self.store.keep_draft(report["report_id"], run["run_id"], written)
        return self.store.finish_run(
            run["run_id"], status="done", pdf=document, problems=problems, summary=summary
        )

    # Assistant sections -------------------------------------------------------------------

    def writer(self, report: dict[str, Any]) -> Callable[..., str]:
        """What writes the report's assistant sections: the model of ``report-write``."""

        def write(
            section_id: str,
            spec: helper.AssistantSpec,
            facts: dict[str, Any],
            start: datetime,
            end: datetime,
        ) -> str:
            clock = pdf.Clock(self.zone())
            words = t(
                "{start} to {end} ({zone})",
                start=clock.text(start, "%a %d %b %H:%M"),
                end=clock.text(end, "%a %d %b %H:%M"),
                zone=self.zone(),
            )
            return self.suite.ask_model(
                helper.WRITE_USE,
                helper.write_question(spec, facts, words),
                system=helper.WRITE_SYSTEM,
            )

        return write

    def last_written(self, report: dict[str, Any]) -> Callable[..., str]:
        """The text each assistant section was last written with (a file made on request never
        asks the model again: the PDFs are what the model wrote)."""

        def last(section_id: str, *_args: Any) -> str:
            found = self.store.last_draft(report["report_id"], section_id)
            if not found:
                raise ValueError(t("Not written yet: make the report once to write it."))
            return str(found["text"])

        return last

    def tune(
        self,
        report: dict[str, Any],
        section_id: str,
        feedback: str,
        by: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """A person's feedback on what the assistant wrote, turned by the model of
        ``report-tune`` into a proposal of the section's next requirements: nothing is saved
        until the editor applies it (``set_requirements``), because a small model can read the
        feedback wrong (2026-10-31: "worst" became "highest score")."""

        sections = list(report.get("sections") or [])
        index = next((i for i, s in enumerate(sections) if s.get("section_id") == section_id), None)
        if index is None or sections[index].get("kind") != "assistant":
            raise KeyError(section_id)
        spec = helper.AssistantSpec.model_validate(sections[index]["assistant"])
        draft = self.store.last_draft(report["report_id"], section_id, run_id=run_id)
        written = str((draft or {}).get("text") or "")
        answer = self.suite.ask_model(
            helper.TUNE_USE,
            helper.tune_question(spec.requirements, written, feedback),
            system=helper.TUNE_SYSTEM,
        )
        requirements = helper.clean_text(answer)[: helper.MAX_REQUIREMENTS].strip()
        if not requirements:
            raise ValueError(t("The model answered no requirements."))
        # A proposal: the editor reads it (and what it names of this period's data) and applies it.
        return {
            "requirements": requirements,
            "previous": spec.requirements,
            "feedback": feedback,
            "run_id": (draft or {}).get("run_id"),
            "warnings": helper.requirement_problems(requirements),
        }

    def set_requirements(
        self,
        report: dict[str, Any],
        section_id: str,
        requirements: str,
        by: str,
        *,
        feedback: str = "",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Save new requirements as the section's next version (by hand, by feedback, or going
        back to an older one)."""

        sections = [dict(s) for s in report.get("sections") or []]
        section = next(s for s in sections if s.get("section_id") == section_id)
        spec = helper.AssistantSpec.model_validate(section["assistant"])
        versions = self.store.assistant_versions(report["report_id"], section_id)
        if not versions:  # the first version is what the section started with
            self.store.keep_version(
                report["report_id"], section_id, 1, spec.requirements, "", None, by
            )
            versions = self.store.assistant_versions(report["report_id"], section_id)
        number = max(v["version"] for v in versions) + 1
        self.store.keep_version(
            report["report_id"], section_id, number, requirements, feedback, run_id, by
        )
        section["assistant"] = {
            **spec.model_dump(),
            "requirements": requirements,
            "version": number,
        }
        payload = ReportPayload.model_validate(
            {
                **{k: report[k] for k in ReportPayload.model_fields if k in report},
                "sections": sections,
            }
        )
        self.update(report["report_id"], payload, by)
        return {
            "version": number,
            "requirements": requirements,
            "previous": spec.requirements,
            "versions": self.store.assistant_versions(report["report_id"], section_id),
        }

    # Other formats ----------------------------------------------------------------------

    def read_now(self, report: dict[str, Any], reader: Reader) -> tuple[document.Document, list]:
        """The report read now over its period, as the document every format writes."""

        made_at = reader.clock()
        reader, period, start, end = self.span(report, reader)
        items, problems = read_sections(
            reader, report.get("sections") or [], period, self.last_written(report)
        )
        info = {
            "start": start,
            "end": end,
            "made_at": made_at,
            "zone": self.zone(),
            "cadence": self.cadence(report),
            "problems": problems,
        }
        return document.build(report, items, info), items

    def export(self, report: dict[str, Any], reader: Reader, form: str) -> tuple[bytes, str, str]:
        """The report read now as a Word, HTML or Markdown file: its bytes, media type and
        file name. These are made when asked and kept nowhere (the PDFs are the record)."""

        made, items = self.read_now(report, reader)
        stem = document.file_stem(report, reader.clock(), self.zone())
        if form == "docx":
            return docx.render(made, self.zone(), reader.clock()), docx.MEDIA_TYPE, f"{stem}.docx"
        if form == "html":
            page = html.render(made, self.zone())
            return page.encode("utf-8"), html.MEDIA_TYPE, f"{stem}.html"
        if form == "md":
            texts = [
                item["section"].get("text") or ""
                for item in items
                if item["section"].get("kind") == "text"
            ]
            return text.render(made, texts).encode("utf-8"), text.MEDIA_TYPE, f"{stem}.md"
        raise ValueError(form)

    def page(self, report: dict[str, Any], reader: Reader) -> str:
        """The report read now as the page a public link shows."""

        made, _items = self.read_now(report, reader)
        return html.render(made, self.zone(), live=True)

    def pdf_url(self, run: dict[str, Any]) -> str:
        return f"{self.root}/api/reports/{run['report_id']}/runs/{run['run_id']}/pdf"

    def send(
        self, report: dict[str, Any], reader: Reader, *, trigger: str, by: str | None
    ) -> dict[str, Any]:
        """Make the report and send it to its recipients; the run says how many it reached."""

        with self._lock:
            run = self.make(report, reader, trigger=trigger, by=by)
        page = f"{self.root}/reports/{report['report_id']}?run={run['run_id']}"
        if run["status"] != "done":
            self.suite.failed(report, run, page)
            self.suite.runs([run], self.root)
            return run
        url = self.pdf_url(run)
        delivered = self.suite.deliver(report, run, url, self.period_text(run))
        recipients = list(report.get("recipients") or [])
        self.store.delivered(run["run_id"], recipients, delivered)
        run = self.store.run(run["run_id"]) or run
        self.suite.sent(report, run, delivered, url)
        self.suite.runs([run], self.root)
        return run

    # The schedule -------------------------------------------------------------------------

    def due(self, reader: Callable[[], Reader | None]) -> list[dict[str, Any]]:
        """Send every report whose time came; the next send is set first, so a report that
        fails is not made again at once. A send missed while the server was down is made
        once, now."""

        now = self.clock()
        sent = []
        due = self.store.due(now)
        if not due:
            return sent
        found = reader()
        for report in due:
            schedule = Schedule.model_validate(report.get("schedule") or {})
            self.store.set_next_run(report["report_id"], next_run(schedule, now, self.zone()))
            if found is None:
                LOGGER.warning("Report %s not sent: View has no app key", report["report_id"])
                continue
            try:
                sent.append(self.send(report, found, trigger="schedule", by=None))
            except Unauthorized:
                LOGGER.warning(
                    "Report %s not sent: PlantCraft refused View's token", report["report_id"]
                )
        if due:
            self.sync()
        return sent

    def sync(self) -> None:
        """PlantCraft's list of View's schedules, and the coming sends on Desk's calendar."""

        if not self.suite.connected:
            return
        reports = self.store.list()
        scheduled = [report for report in reports if report.get("next_run_at")]
        self.suite.schedules(
            [{**report, "cadence": self.cadence(report)} for report in scheduled], self.root
        )
        now = self.clock()
        horizon = now + timedelta(days=CALENDAR_DAYS)
        zone = self.zone()
        self.suite.calendar(
            [
                {
                    "report": report,
                    "at": runs_between(
                        Schedule.model_validate(report.get("schedule") or {}),
                        now,
                        horizon,
                        zone,
                        limit=40,
                    ),
                    "url": f"{self.root}/reports/{report['report_id']}",
                }
                for report in scheduled
            ]
        )

    def resume(self) -> None:
        """At start: runs a stopped server left running fail, and every next send is set
        again from now (the time zone or the clock may have changed)."""

        self.store.fail_unfinished()
        for report in self.store.list():
            stored = self.store.get(report["report_id"]) or {}
            if not stored:
                continue
            wanted = self.next_run(stored)
            current = stored.get("next_run_at")
            if wanted is None and current:
                self.store.set_next_run(report["report_id"], None)
            elif wanted is not None and not current:
                self.store.set_next_run(report["report_id"], wanted)
        self.sync()


class ReportScheduler:
    """A thread that sends the reports due, every ``every`` seconds, in one process only (a file
    lease in the data folder: a second server waits as a standby)."""

    def __init__(
        self,
        service: ReportService,
        reader: Callable[[], Reader | None],
        lease: Any,
        *,
        every: float = 30.0,
    ):
        self.service = service
        self.reader = reader
        self.lease = lease
        self.every = every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._resumed = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="view-reports", daemon=True)
        self._thread.start()

    def tick(self) -> list[dict[str, Any]]:
        if not self.lease.acquire():
            return []
        if not self._resumed:
            self._resumed = True
            self.service.resume()
        return self.service.due(self.reader)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the scheduler never stops
                LOGGER.exception("Report scheduler tick failed")
            self._stop.wait(self.every)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.lease.release()
