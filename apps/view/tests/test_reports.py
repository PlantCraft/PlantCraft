"""Reports: the contract, the schedule, the PDF, the routes and what the suite hears of a send."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from dashcraft.reports import pdf
from dashcraft.reports.model import ReportPayload, Schedule, Section
from dashcraft.reports.schedule import cadence, next_run, runs_between
from tests.conftest import client_for, make_runtime
from tests.plant import NOW


def stat(card_id: str = "c1", **fields) -> dict:
    return {
        "card_id": card_id,
        "kind": "stat",
        "title": "Feed",
        "items": [{"signal_id": "fake:FIC-101.PV"}],
        "agg": "mean",
        **fields,
    }


def report(**fields) -> dict:
    return {
        "name": "Daily unit report",
        "description": "Feed and pump over the day.",
        "period": "24h",
        "schedule": {"every": "day", "at": "06:00"},
        "recipients": ["user:operator"],
        "sections": [
            {"section_id": "intro", "kind": "text", "title": "Summary", "text": "The **feed**."},
            {"section_id": "s1", "kind": "card", "card": stat()},
            {
                "section_id": "s2",
                "kind": "card",
                "card": {
                    "card_id": "c2",
                    "kind": "trend",
                    "title": "Feed trend",
                    "items": [{"signal_id": "fake:FIC-101.PV"}, {"signal_id": "fake:FIC-101.SP"}],
                },
            },
            {"section_id": "brk", "kind": "break"},
            {
                "section_id": "ev",
                "kind": "events",
                "title": "Reports sent",
                "events": {"kinds": ["dashcraft.report.sent"]},
            },
        ],
        **fields,
    }


# The contract -------------------------------------------------------------------------


def test_a_report_names_its_signals_not_variables():
    with pytest.raises(ValidationError, match="not a variable"):
        Section.model_validate(
            {
                "section_id": "s",
                "kind": "card",
                "card": stat(items=[{"asset_id": "$loop", "role": "pv"}]),
            }
        )


def test_sections_say_what_they_need():
    with pytest.raises(ValidationError, match="text of the cell"):
        Section.model_validate({"section_id": "s", "kind": "text"})
    with pytest.raises(ValidationError, match="needs its panel"):
        Section.model_validate({"section_id": "s", "kind": "card"})
    with pytest.raises(ValidationError, match="Pick the events"):
        Section.model_validate({"section_id": "s", "kind": "events"})
    with pytest.raises(ValidationError, match="app>.<event"):
        Section.model_validate(
            {"section_id": "s", "kind": "events", "events": {"kinds": ["alarm raised"]}}
        )
    page = Section.model_validate({"section_id": "s", "kind": "break", "width": "half"})
    assert page.width == "full"


def test_the_report_rules():
    with pytest.raises(ValidationError, match="at least one hour"):
        ReportPayload.model_validate(report(period="30m"))
    with pytest.raises(ValidationError, match="user:<username>"):
        ReportPayload.model_validate(report(recipients=["operator"]))
    with pytest.raises(ValidationError, match="same id"):
        ReportPayload.model_validate(report(sections=[{"section_id": "a", "kind": "break"}] * 2))
    with pytest.raises(ValidationError, match="hours and minutes"):
        ReportPayload.model_validate(report(schedule={"every": "day", "at": "6h"}))


# The schedule -------------------------------------------------------------------------


def test_next_send_is_on_the_plant_clock():
    daily = Schedule(every="day", at="06:00")
    after = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    # 06:00 in São Paulo (UTC-3) is 09:00 UTC, the next day.
    assert next_run(daily, after, "America/Sao_Paulo") == datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
    assert next_run(daily, datetime(2026, 10, 1, 8, 0, tzinfo=UTC), "America/Sao_Paulo") == (
        datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    )
    weekly = Schedule(every="week", weekday="mon", at="07:30")
    assert next_run(weekly, after, "UTC") == datetime(2026, 10, 5, 7, 30, tzinfo=UTC)
    monthly = Schedule(every="month", day=1, at="00:00")
    assert next_run(monthly, after, "UTC") == datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    assert next_run(Schedule(), after, "UTC") is None


def test_summer_time_keeps_the_wall_clock_hour():
    daily = Schedule(every="day", at="06:00")
    sends = runs_between(
        daily,
        datetime(2026, 10, 23, 0, 0, tzinfo=UTC),
        datetime(2026, 10, 27, 0, 0, tzinfo=UTC),
        "Europe/Berlin",
    )
    # Berlin leaves summer time on 25 October: 04:00 UTC before, 05:00 UTC after.
    assert [moment.hour for moment in sends] == [4, 4, 5, 5]


def test_cadence_in_words():
    assert cadence(Schedule(every="week", weekday="fri", at="17:00")) == "Every Friday at 17:00"
    assert cadence(Schedule()) == "Not scheduled"


# The PDF -------------------------------------------------------------------------------


def test_text_from_people_is_escaped_in_the_pdf():
    assert pdf.inline("<b>&</b> **bold**") == "&lt;b&gt;&amp;&lt;/b&gt; <b>bold</b>"
    document = pdf.render(
        {"name": "A <report> & more", "description": "<script>"},
        [
            {
                "section": {"kind": "text", "title": "<h1>", "text": "# Title\n- one\n1. two"},
                "data": None,
                "error": None,
            }
        ],
        {"start": NOW - timedelta(days=1), "end": NOW, "made_at": NOW, "zone": "Nowhere/City"},
    )
    assert document.startswith(b"%PDF")


def test_a_line_of_another_unit_reads_on_a_right_axis():
    from dashcraft.dashboards.model import Card

    card = Card.model_validate({**stat(), "kind": "trend"})
    at = [(NOW - timedelta(minutes=10 - n)).isoformat() for n in range(10)]
    data = {
        "lines": [
            {"label": "PV", "unit": "bar", "t": at, "v": [38 + n % 2 for n in range(10)]},
            {"label": "OP", "unit": "%", "t": at, "v": [50 + n for n in range(10)]},
        ],
        "range": {"start": at[0], "end": at[-1]},
    }
    _, lines = pdf.trend_drawing(card, data, 400, pdf.Clock("UTC"))
    assert [line["_right"] for line in lines] == [False, True]


def test_ticks_are_round_numbers():
    assert pdf.nice_ticks(46.5, 53.5) == [46.0, 48.0, 50.0, 52.0, 54.0]
    assert pdf.nice_ticks(5, 5)[0] < 5 < pdf.nice_ticks(5, 5)[-1]
    assert pdf.number_text(1234.5) == "1,234"
    assert pdf.number_text(None) == "–"


# The routes ----------------------------------------------------------------------------


def test_editors_make_reports_viewers_read_them(runtime, fake):
    with client_for(runtime, fake, "engineer") as editor:
        created = editor.post("/dash/api/reports", json=report())
        assert created.status_code == 201, created.text
        item = created.json()
        assert item["cadence"] == "Every day at 06:00"
        assert item["next_run_at"] == "2026-10-02T06:00:00.000Z"
        assert item["section_count"] == 5 and item["can_edit"]
        # What it covers if made now, on the server's clock (the plant's).
        assert item["covers"] == {
            "start": "2026-09-30T12:00:00.000Z",
            "end": "2026-10-01T12:00:00.000Z",
        }
    with client_for(runtime, fake, "operator") as viewer:
        listed = viewer.get("/dash/api/reports").json()
        assert [found["name"] for found in listed] == ["Daily unit report"]
        assert listed[0]["can_edit"] is False
        assert viewer.post("/dash/api/reports", json=report()).status_code == 403
        rid = listed[0]["report_id"]
        assert viewer.post(f"/dash/api/reports/{rid}/send").status_code == 403
        section = viewer.get(f"/dash/api/reports/{rid}/sections/s1").json()
        assert section["data"]["rows"][0]["value"] is not None
        made = viewer.post(f"/dash/api/reports/{rid}/pdf")
        assert made.status_code == 201 and made.json()["status"] == "done"
        answer = viewer.get(f"/dash/api/reports/{rid}/runs/{made.json()['run_id']}/pdf")
        assert answer.headers["content-type"] == "application/pdf"
        assert answer.content.startswith(b"%PDF")
        assert "inline" in answer.headers["content-disposition"]
    with client_for(runtime, fake, "outsider") as outsider:
        assert outsider.get("/dash/api/reports").status_code == 403


def test_send_now_notifies_the_recipients_and_tells_the_suite(client, runtime, fake):
    rid = client.post("/dash/api/reports", json=report()).json()["report_id"]
    sent = client.post(f"/dash/api/reports/{rid}/send")
    assert sent.status_code == 201, sent.text
    run = sent.json()
    assert run["status"] == "done" and run["delivered"] == 1
    assert run["recipients"] == ["user:operator"]
    note = fake.notifications[-1]
    assert note["app"] == "dashcraft" and note["delivered"] == ["operator"]
    assert note["url"] == f"/dash/api/reports/{rid}/runs/{run['run_id']}/pdf"
    assert note["key"] == f"report:{rid}"
    kinds = [event["kind"] for event in fake.links.events]
    assert "dashcraft.report.sent" in kinds
    assert ("dashcraft", run["run_id"]) in fake.links.runs
    runs = client.get(f"/dash/api/reports/{rid}/runs").json()
    assert [item["trigger"] for item in runs] == ["send"]


def test_send_needs_recipients(client):
    rid = client.post("/dash/api/reports", json=report(recipients=[])).json()["report_id"]
    answer = client.post(f"/dash/api/reports/{rid}/send")
    assert answer.status_code == 422 and "goes to" in answer.json()["detail"]


def test_a_due_report_is_sent_once_and_its_next_send_set(tmp_path, fake):
    clock = {"now": NOW}
    runtime = make_runtime(tmp_path, fake)
    runtime.report_service.clock = lambda: clock["now"]
    try:
        with client_for(runtime, fake, "engineer") as client:
            rid = client.post("/dash/api/reports", json=report()).json()["report_id"]
            assert runtime.report_scheduler.tick() == []
            clock["now"] = NOW + timedelta(hours=19)  # 07:00 the next day
            sent = runtime.report_scheduler.tick()
            assert [run["trigger"] for run in sent] == ["schedule"]
            assert runtime.report_scheduler.tick() == []
            saved = client.get(f"/dash/api/reports/{rid}").json()
            assert saved["next_run_at"] == "2026-10-03T06:00:00.000Z"
            assert saved["last_run"]["trigger"] == "schedule"
            schedules = fake.links.schedules.get("dashcraft") or []
            assert [item["id"] for item in schedules] == [rid]
            feed = fake.links.calendar.get(("dashcraft", "reports")) or []
            assert feed and feed[0]["audience"] == "user:operator"
    finally:
        runtime.shutdown()


def test_saving_conflicts_and_copies(client):
    created = client.post("/dash/api/reports", json=report()).json()
    rid = created["report_id"]
    first = client.put(
        f"/dash/api/reports/{rid}",
        json=report(name="Renamed", base_updated_at=created["updated_at"]),
    )
    assert first.status_code == 200 and first.json()["name"] == "Renamed"
    stale = client.put(
        f"/dash/api/reports/{rid}", json=report(base_updated_at=created["updated_at"])
    )
    assert stale.status_code == 409
    copy = client.post(f"/dash/api/reports/{rid}/copy").json()
    assert copy["name"] == "Renamed (copy)" and copy["next_run_at"] is None
    assert client.delete(f"/dash/api/reports/{copy['report_id']}").status_code == 204
    assert client.get(f"/dash/api/reports/{copy['report_id']}").status_code == 404


def test_a_folder_kept_for_others_hides_its_reports(runtime, fake):
    with client_for(runtime, fake, "admin") as admin:
        folder = admin.post(
            "/dash/api/folders", json={"name": "Shift leads", "viewers": ["user:engineer"]}
        ).json()
        admin.post("/dash/api/reports", json=report(folder_id=folder["folder_id"]))
        assert admin.delete(f"/dash/api/folders/{folder['folder_id']}").status_code == 409
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get("/dash/api/reports").json() == []


def test_preview_search_and_references(client):
    preview = client.post(
        "/dash/api/report-preview",
        json={"section": {"section_id": "s", "kind": "card", "card": stat()}, "period": "8h"},
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["window"] == "8h"
    rid = client.post("/dash/api/reports", json=report()).json()["report_id"]
    found = client.get("/dash/api/search", params={"q": "daily unit"}).json()["items"]
    assert any(item["type"] == "Report" for item in found)
    ref = client.get(f"/dash/api/refs/report/{rid}").json()
    assert ref == {
        "title": "Daily unit report",
        "status": "Every day at 06:00",
        "url": f"/dash/reports/{rid}",
    }
    widget = client.get("/dash/api/widgets/reports").json()
    assert widget["items"][0]["label"] == "Daily unit report"


def test_a_section_that_cannot_be_read_says_so_and_the_rest_is_made(client, fake):
    broken = report(
        sections=[
            {
                "section_id": "s1",
                "kind": "card",
                "card": stat(items=[{"signal_id": "fake:NOPE"}]),
            },
            {"section_id": "s2", "kind": "card", "card": stat("c2")},
        ]
    )
    rid = client.post("/dash/api/reports", json=broken).json()["report_id"]
    run = client.post(f"/dash/api/reports/{rid}/pdf").json()
    assert run["status"] == "done" and run["problems"] == 1
    assert run["summary"] == "1 section could not be read in full."


# Sections that count their events --------------------------------------------------------


def test_an_events_section_counts_by_subject_kind_severity_or_a_payload_field():
    spec = {"kinds": ["linkcraft.finding.opened"], "group_by": "payload.method_id"}
    assert Section.model_validate(
        {"section_id": "s", "kind": "events", "events": spec}
    ).events.group_by == ("payload.method_id")
    for wrong in ("payload", "payload.Bad-Key", "summary", "subject; drop"):
        with pytest.raises(ValidationError, match="Count events by"):
            Section.model_validate(
                {"section_id": "s", "kind": "events", "events": {**spec, "group_by": wrong}}
            )


def _findings(fake) -> None:
    from tests.plant import LINK_KEY

    linkcraft = fake.client(None, app="linkcraft", key=LINK_KEY)
    found = [
        ("asset:fic-101", "stiction_screening", "Possible valve stiction screening", "critical"),
        ("asset:fic-101", "stiction_screening", "Possible valve stiction screening", "warning"),
        ("asset:fic-101", "oscillation_autocorrelation", None, "warning"),
        ("asset:lic-102", "stiction_screening", "Possible valve stiction screening", "warning"),
    ]
    receipt = linkcraft.post_events(
        {
            "kind": "linkcraft.finding.opened",
            "subject": subject,
            "summary": f"{method} on {subject}",
            "severity": severity,
            "payload": {"method_id": method, **({"method_name": name} if name else {})},
        }
        for subject, method, name, severity in found
    )
    assert not receipt["errors"], receipt


def test_a_counting_section_ranks_its_groups_in_every_format(client, fake):
    _findings(fake)
    sections = [
        {
            "section_id": "by-loop",
            "kind": "events",
            "title": "Findings by loop",
            "events": {"kinds": ["linkcraft.finding.opened"], "group_by": "subject"},
        },
        {
            "section_id": "by-method",
            "kind": "events",
            "title": "Findings by method",
            "events": {
                "kinds": ["linkcraft.finding.opened"],
                "group_by": "payload.method_id",
                "limit": 1,
            },
        },
    ]
    rid = client.post("/dash/api/reports", json=report(sections=sections)).json()["report_id"]
    by_loop = client.get(f"/dash/api/reports/{rid}/sections/by-loop").json()["data"]
    assert by_loop["group_head"] == "About"
    assert [(g["label"], g["count"], g["share"]) for g in by_loop["groups"]] == [
        ("FIC-101", 3, 75.0),
        ("LIC-102", 1, 25.0),
    ]
    # The worst severity of a group colours it.
    assert by_loop["groups"][0]["severity"] == "critical"
    by_method = client.get(f"/dash/api/reports/{rid}/sections/by-method").json()["data"]
    assert by_method["group_head"] == "Method"
    # ``method_name`` names ``method_id``; one group listed of the two.
    assert [g["label"] for g in by_method["groups"]] == ["Possible valve stiction screening"]
    assert by_method["group_total"] == 2
    text = client.get(f"/dash/api/reports/{rid}/export/md").text
    assert "Most often: FIC-101, 3 of 4 (75%). 2 in all." in text
    assert "The 1 largest of 2 groups are listed." in text
    for form in ("docx", "html"):
        assert client.get(f"/dash/api/reports/{rid}/export/{form}").status_code == 200
    run = client.post(f"/dash/api/reports/{rid}/pdf").json()
    assert run["status"] == "done" and run["problems"] == 0
