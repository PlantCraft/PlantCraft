"""The DCS alarm list (L1): a CSV or Excel export read as a draft, compared with what earlier
imports made, and applied only after a person who edits rules reviewed it."""

from __future__ import annotations

import base64
import io
import zipfile

from alarmcraft.alarms import alarmlist
from tests.conftest import client_for

FIC = "plantcraft:CPM.Loops.FIC-1001.PV"
TIC = "plantcraft:CPM.Loops.TIC-1104.PV"
SIGNALS = [
    {"id": FIC, "name": "CPM.Loops.FIC-1001.PV"},
    {"id": TIC, "name": "CPM.Loops.TIC-1104.PV"},
]

LIST = (
    "Tag;Alarm type;Limit;EU;Priority;Deadband;On delay;Description;Cause;Consequence;Operator action\n"
    "FIC-1001.PV;PVHI;55,5;m3/h;2;0,5;10 s;Feed flow high;Valve stuck open;Flooding;Close FV-1001\n"
    "FIC-1001.PV;PVLO;10;m3/h;3;;00:01:00;Feed flow low;;;\n"
    "TIC-1104.PV;HH;180;degC;1;1;;Reactor temperature very high;;Runaway;Trip the feed\n"
)


def _file(text: str, name: str = "dcs.csv") -> dict:
    return {"filename": name, "content": base64.b64encode(text.encode("cp1252")).decode()}


def _xlsx(rows: list[list[str]]) -> bytes:
    strings: list[str] = []
    cells_xml = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            try:
                float(value)
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            except ValueError:
                strings.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        cells_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml",
                      f'<worksheet {ns}><sheetData>{"".join(cells_xml)}</sheetData></worksheet>')  # fmt: skip
        shared = "".join(f"<si><t>{text}</t></si>" for text in strings)
        book.writestr("xl/sharedStrings.xml", f"<sst {ns}>{shared}</sst>")
    return buffer.getvalue()


def test_a_csv_export_is_read_with_its_own_names_decimals_and_priorities():
    found = alarmlist.read(LIST.encode("cp1252"), "dcs.csv", SIGNALS)
    assert found.problems == []
    assert found.columns["kind"] == "Alarm type" and found.columns["action"] == "Operator action"
    hi, lo, hh = found.rows
    assert (hi.signal_id, hi.kind, hi.limit, hi.deadband) == (FIC, "high", 55.5, 0.5)
    assert (hi.priority, hi.on_delay_seconds, hi.unit) == ("high", 10.0, "m3/h")
    assert hi.external_id == "FIC-1001.PV/HI" and hi.action == "Close FV-1001"
    assert (lo.kind, lo.on_delay_seconds, lo.priority, lo.name) == (
        "low",
        60.0,
        "medium",
        "Feed flow low",
    )
    assert (hh.kind, hh.priority, hh.signal_id) == ("high_high", "critical", TIC)


def test_an_excel_export_is_read_like_the_csv():
    rows = [["Tag", "Type", "Limit", "Priority"], ["FIC-1001.PV", "HI", "55", "high"]]
    found = alarmlist.read(_xlsx(rows), "dcs.xlsx", SIGNALS)
    assert found.problems == [] and found.format == "xlsx"
    assert found.rows[0].limit == 55.0 and found.rows[0].kind == "high"


def test_bad_rows_are_listed_with_their_line_and_never_stop_the_others():
    text = (
        "tag,type,limit,priority\n"
        "FIC-1001.PV,HI,55,high\n"
        "FIC-1001.PV,ROC,5,high\n"        # a rate of change: not one Alarms imports
        "NOPE-1.PV,HI,1,high\n"           # no such signal
        "FIC-1001.PV,LO,,high\n"          # no limit
        "FIC-1001.PV,HI,60,high\n"        # the same alarm again
        "TIC-1104.PV,LL,5,urgentish\n"    # an unknown priority
        ",HI,5,high\n"
    )  # fmt: skip
    found = alarmlist.read(text.encode(), "dcs.csv", SIGNALS)
    assert [row.line for row in found.rows] == [2]
    lines = {problem["line"] for problem in found.problems}
    assert lines == {3, 4, 5, 6, 7, 8}
    assert any("ROC" in problem["message"] for problem in found.problems)
    assert alarmlist.read(b"just,some,columns\n1,2,3\n", "x.csv", SIGNALS).problems[0]["line"] == 0
    assert alarmlist.read(b"PK broken", "x.xlsx", SIGNALS).problems
    assert alarmlist.read(b"x", "x.pdf", SIGNALS).problems


def _read(client, text: str) -> dict:
    made = client.post("/api/alarm-list", json=_file(text))
    assert made.status_code == 201, made.text
    return made.json()


def test_a_list_is_a_draft_until_it_is_reviewed_and_applied(client):
    before = len(client.get("/api/rules").json())
    draft = _read(client, LIST)
    assert draft["state"] == "draft" and draft["counts"] == {
        "new": 3,
        "changed": 0,
        "removed": 0,
        "same": 0,
    }
    assert len(client.get("/api/rules").json()) == before  # nothing written yet

    applied = client.post(f"/api/alarm-list/{draft['import_id']}/apply",
                          json={"skip": ["FIC-1001.PV/LO"]}).json()  # fmt: skip
    assert applied["state"] == "applied"
    assert applied["result"]["created"] == 2 and applied["result"]["left_out"] == 1
    rules = {
        rule["external_id"]: rule
        for rule in client.get("/api/rules").json()
        if rule.get("external_id")
    }
    hi = rules["FIC-1001.PV/HI"]
    [condition] = hi["simple"]["conditions"]
    assert (
        condition["value"]["signal"] == FIC
        and condition["op"] == ">="
        and condition["limit"] == 55.5
    )
    assert hi["priority"] == "high" and hi["action"] == "Close FV-1001"
    again = client.post(f"/api/alarm-list/{draft['import_id']}/apply", json={})
    assert again.status_code == 409  # applied once only

    # The next export: one limit changed, the LO alarm still new, the HH gone from the list.
    edited = LIST.replace("55,5", "60").splitlines()
    second = _read(client, "\n".join(edited[:3]) + "\n")
    changes = {item["key"]: item for item in second["items"]}
    assert changes["FIC-1001.PV/HI"]["change"] == "changed"
    assert changes["FIC-1001.PV/HI"]["fields"] == ["limit"]
    assert changes["FIC-1001.PV/HI"]["before"]["limit"] == 55.5
    assert changes["FIC-1001.PV/LO"]["change"] == "new"
    assert changes["TIC-1104.PV/HH"]["change"] == "removed"
    client.post(f"/api/alarm-list/{second['import_id']}/apply", json={})
    rules = {
        rule["external_id"]: rule
        for rule in client.get("/api/rules").json()
        if rule.get("external_id")
    }
    assert rules["FIC-1001.PV/HI"]["simple"]["conditions"][0]["limit"] == 60
    assert rules["TIC-1104.PV/HH"]["enabled"] is False  # turned off, never deleted

    # The same file once more: nothing to do.
    third = _read(client, "\n".join(edited[:3]) + "\n")
    assert third["counts"] == {"new": 0, "changed": 0, "removed": 0, "same": 2}


def test_what_people_set_in_alarms_stays_and_a_later_edit_wins_over_a_stale_draft(client):
    first = _read(client, LIST)
    client.post(f"/api/alarm-list/{first['import_id']}/apply", json={})
    rule = next(
        r for r in client.get("/api/rules").json() if r.get("external_id") == "FIC-1001.PV/HI"
    )
    # Someone edits the rule in the editor (which does not send external_id) after a re-read.
    stale = _read(client, LIST.replace("55,5", "70"))
    body = {key: rule[key] for key in ("name", "enabled", "creates", "priority", "where", "editor",
                                       "simple", "owner", "notify", "cause", "consequence", "action")}  # fmt: skip
    body["notify"] = {**rule["notify"], "enabled": False}
    saved = client.put(
        f"/api/rules/{rule['rule_id']}", json={**body, "base_updated_at": rule["updated_at"]}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["external_id"] == "FIC-1001.PV/HI"
    result = client.post(f"/api/alarm-list/{stale['import_id']}/apply", json={}).json()["result"]
    assert result["changed"] == 0
    assert [item["key"] for item in result["not_applied"]] == ["FIC-1001.PV/HI"]
    # Read again, applied: the limit changes and the notify choice made in Alarms stays.
    fresh = _read(client, LIST.replace("55,5", "70"))
    client.post(f"/api/alarm-list/{fresh['import_id']}/apply", json={})
    after = client.get(f"/api/rules/{rule['rule_id']}").json()
    assert after["simple"]["conditions"][0]["limit"] == 70
    assert after["notify"]["enabled"] is False


def test_only_editors_import_and_a_draft_can_be_thrown_away(client, runtime, fake):
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.post("/api/alarm-list", json=_file(LIST)).status_code == 403
        assert viewer.get("/api/alarm-list/template.csv").status_code == 403
    template = client.get("/api/alarm-list/template.csv")
    assert template.status_code == 200 and template.text.startswith("tag,type,limit")
    draft = _read(client, LIST)
    assert (
        client.post(f"/api/alarm-list/{draft['import_id']}/discard").json()["state"] == "discarded"
    )
    assert client.post(f"/api/alarm-list/{draft['import_id']}/apply", json={}).status_code == 409
    listed = client.get("/api/alarm-list").json()
    assert listed[0]["import_id"] == draft["import_id"] and listed[0]["state"] == "discarded"
    assert client.get("/api/alarm-list/999").status_code == 404
    bad = client.post("/api/alarm-list", json={"filename": "x.csv", "content": "%%%"})
    assert bad.status_code == 422
