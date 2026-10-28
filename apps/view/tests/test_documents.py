"""Reports as documents (round 10): Markdown cells and their outline, the Word, HTML and Markdown
files, a report's public link, a report started from a dashboard, and General as no folder's name.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile

from plantcraft_sdk.server.store import Database

from dashcraft.dashboards.folders import FolderStore
from dashcraft.reports import markdown as md
from dashcraft.reports.model import Section
from dashcraft.reports.store import ReportStore
from tests.conftest import client_for, dashboard, kpi
from tests.test_reports import report

TEXT = (
    "The **feed** ran well.\n\n## Feed\n\n- one\n- two\n\n| A | B |\n|---|--:|\n| x | 1.5 |\n\n"
    "### Deeper\n\n> see [the site](https://example.com) and [no](javascript:alert(1))"
)


def _report(client, **fields) -> dict:
    body = report(**fields)
    body["sections"][0]["text"] = TEXT
    created = client.post("/dash/api/reports", json=body)
    assert created.status_code == 201, created.text
    return created.json()


# Markdown cells ---------------------------------------------------------------------------


def test_markdown_reads_headings_lists_tables_and_only_safe_links():
    blocks = md.parse(TEXT)
    assert [block.kind for block in blocks] == [
        "paragraph", "heading", "list", "table", "heading", "quote",
    ]  # fmt: skip
    assert [block.level for block in blocks if block.kind == "heading"] == [2, 3]
    assert blocks[3].align == ["left", "right"]
    links = [span for span in blocks[-1].spans if span.style == "link"]
    assert [span.href for span in links] == ["https://example.com"]
    outline = md.outline_of([md.parse("# A\n## A")])
    assert [(item.level, item.anchor) for item in outline] == [(1, "a"), (2, "a-2")]


def test_a_text_section_with_a_heading_field_becomes_one_cell():
    section = Section.model_validate(
        {"section_id": "s", "kind": "text", "title": "Summary", "text": "The day."}
    )
    assert section.title == "" and section.text == "# Summary\n\nThe day."


def test_saved_text_sections_move_to_cells_once(tmp_path):
    db = Database(tmp_path / "view.db")
    store = ReportStore(db)
    created = store.create(report(), "engineer", None)
    raw = json.dumps([{"section_id": "a", "kind": "text", "title": "Old", "text": "x"}])
    with db.connect() as connection:
        connection.execute("UPDATE reports SET sections_json = ?", (raw,))
        connection.execute("DELETE FROM sdk_migrations WHERE name LIKE 'ReportStore:%'")
        connection.commit()
    again = ReportStore(Database(tmp_path / "view.db"))
    assert again.get(created["report_id"])["sections"][0] == {
        "section_id": "a", "kind": "text", "title": "", "text": "# Old\n\nx",
    }  # fmt: skip


# Files ----------------------------------------------------------------------------------


def test_word_keeps_headings_tables_and_charts(client, fake):
    created = _report(client)
    answer = client.get(f"/dash/api/reports/{created['report_id']}/export/docx")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert re.search(r'filename="daily-unit-report-\d{4}-\d{2}-\d{2}\.docx"', answer.headers[
        "content-disposition"])  # fmt: skip
    package = zipfile.ZipFile(io.BytesIO(answer.content))
    body = package.read("word/document.xml").decode()
    assert '<w:pStyle w:val="Heading1"/>' in body and '<w:pStyle w:val="Heading3"/>' in body
    assert "<w:tbl>" in body and "Feed trend" in body
    assert any(name.startswith("word/media/") for name in package.namelist())
    assert "https://example.com" in package.read("word/_rels/document.xml.rels").decode()
    assert [row["action"] for row in fake.audit_log][-1] == "dashcraft.report.export"


def test_html_has_its_outline_and_interactive_charts(client):
    created = _report(client, name="Night </script><b>shift")
    page = client.get(f"/dash/api/reports/{created['report_id']}/export/html").text
    assert '<nav class="rc-outline"' in page and 'href="#feed"' in page and 'id="feed"' in page
    assert '<div class="rc-chart"' in page and "</script><b>" not in page
    data = re.search(r'<script type="application/json">(.*?)</script>', page).group(1)
    series = json.loads(data)["series"]
    assert series and len(series[0]["t"]) == len(series[0]["v"])
    assert "javascript:" not in page


def test_markdown_writes_the_cells_back_and_cards_as_values(client):
    created = _report(client)
    text = client.get(f"/dash/api/reports/{created['report_id']}/export/md").text
    assert text.startswith("# Daily unit report\n") and "\n### Feed\n" in text
    assert "| Feed flow (m3/h) |" in text
    assert client.get(f"/dash/api/reports/{created['report_id']}/export/odt").status_code == 404


def test_the_pdf_lists_its_headings_as_bookmarks(client):
    created = _report(client)
    run = client.post(f"/dash/api/reports/{created['report_id']}/pdf").json()
    document = client.get(f"/dash/api/reports/{created['report_id']}/runs/{run['run_id']}/pdf")
    assert b"/Outlines" in document.content and b"Deeper" in document.content


# The public link --------------------------------------------------------------------------


def test_a_report_link_opens_its_page_without_sign_in_until_revoked(runtime, fake, client):
    created = _report(client)
    base = f"/dash/api/reports/{created['report_id']}"
    share = client.post(f"{base}/shares", json={"label": "Shift"}).json()
    assert share["path"].startswith("/dash/share/report/")
    with client_for(runtime, fake, None) as anonymous:
        page = anonymous.get(share["path"])
        assert page.status_code == 200 and "Daily unit report" in page.text
        policy = page.headers["content-security-policy"]
        assert "default-src 'none'" in policy and "'unsafe-inline'; img-src" not in policy
        # Only the page's own script runs, by its hash (the charts draw under it).
        script = page.text.rsplit("<script>", 1)[1].split("</script>", 1)[0]
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        assert f"script-src 'sha256-{digest}'" in policy
        assert anonymous.get(base).status_code == 401
        listed = client.get("/dash/api/reports").json()
        assert listed[0]["public_links"] == 1
        # A dashboard's link never opens a report, nor a report's a dashboard.
        token = share["path"].rsplit("/", 1)[-1]
        assert anonymous.get(f"/dash/api/public/{token}").status_code == 404
        client.delete(f"{base}/shares/{share['share_id']}")
        assert anonymous.get(share["path"]).status_code == 404
        again = client.post(f"{base}/shares", json={}).json()
        client.delete(base)
        assert anonymous.get(again["path"]).status_code == 404


# A report from a dashboard ----------------------------------------------------------------


def test_a_dashboards_pair_has_its_pages_as_headings_and_its_cards_as_cells(client):
    pages = [{"page_id": "p1", "name": "Overview"}, {"page_id": "p2", "name": "Valves"}]
    cards = [
        {**kpi("k1"), "page_id": "p1", "width": 6, "y": 0},
        {**kpi("k2"), "page_id": "p2", "width": 12, "y": 0, "window": "8h"},
        {"card_id": "n1", "kind": "text", "title": "Note", "text": "Read me", "page_id": "p1",
         "y": 1},
    ]  # fmt: skip
    created = client.post(
        "/dash/api/dashboards", json=dashboard(description="Two pages.", pages=pages, cards=cards)
    ).json()
    pair = client.get(f"/dash/api/dashboards/{created['dashboard_id']}/as-report").json()
    kinds = [(section["kind"], section.get("text") or section.get("width")) for section in pair[
        "sections"]]  # fmt: skip
    assert kinds == [
        ("text", "Two pages."), ("text", "# Overview"), ("card", "half"),
        ("text", "## Note\n\nRead me"), ("text", "# Valves"), ("card", "full"),
    ]  # fmt: skip
    saved = client.post("/dash/api/reports", json={"name": "Pair", "sections": pair["sections"]})
    assert saved.status_code == 201, saved.text


# General ------------------------------------------------------------------------------------


def test_general_is_no_folders_name(client):
    for name in ("General", " general "):
        answer = client.post("/dash/api/folders", json={"name": name})
        assert answer.status_code == 422 and "another name" in answer.text


def test_a_folder_named_general_is_folded_into_general_once(tmp_path):
    db = Database(tmp_path / "view.db")
    FolderStore(db)
    with db.connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS dashboards (dashboard_id TEXT, folder_id TEXT);
            INSERT INTO dashboard_folders (folder_id, name, created_at, updated_at)
                VALUES ('open', 'General', 'x', 'x');
            INSERT INTO dashboard_folders (folder_id, name, viewers_json, created_at, updated_at)
                VALUES ('kept', 'general', '["group:ops"]', 'x', 'x');
            INSERT INTO dashboards VALUES ('d1', 'open');
            DELETE FROM sdk_migrations WHERE name LIKE 'FolderStore:%';
            """
        )
        connection.commit()
    folders = FolderStore(Database(tmp_path / "view.db"))
    assert [(item["folder_id"], item["name"]) for item in folders.list()] == [
        ("kept", "General (restricted)")
    ]
    with db.connect() as connection:
        assert connection.execute("SELECT folder_id FROM dashboards").fetchone()[0] == ""


def test_every_template_has_a_pair_that_saves(client):
    """The demo pairs reports with dashboards made from templates (Loop detail and its variable)."""

    for template in client.get("/dash/api/templates").json():
        created = client.post("/dash/api/dashboards", json=template["draft"])
        assert created.status_code == 201, created.text
        pair = client.get(f"/dash/api/dashboards/{created.json()['dashboard_id']}/as-report")
        assert pair.status_code == 200, pair.text
        sections = pair.json()["sections"]
        assert sections, template["draft"]["name"]
        body = {"name": f"{template['draft']['name']} pair", "sections": sections}
        saved = client.post("/dash/api/reports", json=body)
        assert saved.status_code == 201, saved.text
