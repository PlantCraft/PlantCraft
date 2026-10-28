"""The main journey in a real browser: sign-in, then a document sent, read, opened and found."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests.conftest import docx_bytes

try:
    from playwright.sync_api import expect
except ImportError:
    if os.environ.get("DOCCRAFT_E2E_REQUIRED") == "1":
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)


def _shot(page, screenshots, name):
    if screenshots:
        page.wait_for_timeout(800)
        page.screenshot(path=str(screenshots / f"{name}.png"), full_page=True)


INCIDENT = Path(__file__).resolve().parents[1] / "files" / "incident.pdf"


def test_a_browser_without_a_token_is_sent_to_sign_in(anonymous, app_url):
    anonymous.goto(f"{app_url}/doc/")
    assert re.search(r"/login\?next=/doc/", anonymous.url), anonymous.url


def test_send_a_document_read_it_and_find_it(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/doc/")
    expect(page.get_by_role("heading", name="Overview")).to_be_visible()
    expect(page.get_by_label("Search or ask the documents")).to_be_visible()
    expect(page.get_by_text("No document yet.")).to_be_visible()
    # No button at the top of the Overview (final round, 2026-10-27): the library is in the menu.
    expect(page.get_by_role("button", name="Send files")).to_have_count(0)
    expect(page.get_by_role("link", name="Open the library")).to_have_count(0)
    _shot(page, screenshots, "1-empty")

    # Sent from the library, which says what it reads; the document is read there.
    page.goto(f"{app_url}/doc/documents")
    expect(page.get_by_text("Files read: PDF, Word (.docx)", exact=False).first).to_be_visible()
    page.locator("input[type=file]").set_input_files(
        {
            "name": "INC-2026-007 PIC-1002 separator pressure oscillation.pdf",
            "mimeType": "application/pdf",
            "buffer": INCIDENT.read_bytes(),
        }
    )
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Number")).to_have_value("INC-2026-007")
    dialog.get_by_label("Kind").select_option("Incident report")
    dialog.get_by_label("Description").fill("The separator pressure cycling of October")
    dialog.get_by_role("button", name="Send").click()
    expect(page).to_have_url(re.compile(r"/doc/documents$"))
    row = page.get_by_role("row", name=re.compile("INC-2026-007"))
    expect(row.get_by_text("Read", exact=True)).to_be_visible(timeout=20000)
    _shot(page, screenshots, "2-sent")

    expect(row.get_by_text("The separator pressure cycling of October")).to_be_visible()
    page.get_by_role("link", name="INC-2026-007").click()
    expect(page.get_by_role("heading", name="Causes")).to_be_visible()
    expect(page.get_by_text("raised from 1.6 to 2.4", exact=False)).to_be_visible()
    _shot(page, screenshots, "3-document")

    # The Overview's search box opens the search with the question.
    page.goto(f"{app_url}/doc/")
    expect(page.get_by_text("documents, all ready for search")).to_be_visible()
    page.get_by_label("Search or ask the documents").fill(
        "why does the separator pressure oscillate"
    )
    page.get_by_label("Search or ask the documents").press("Enter")
    expect(page).to_have_url(re.compile(r"/doc/search\?q="))
    hit = page.locator(".hit").first
    expect(hit).to_contain_text("INC-2026-007")
    # The words of the search in bold in the passage, and again where it opens.
    expect(hit.locator("mark").first).to_be_visible()
    _shot(page, screenshots, "4-search")
    hit.get_by_role("link").first.click()
    expect(page).to_have_url(re.compile(r"passage=\d+&q="))
    expect(page.locator(".passage-marked mark").first).to_be_visible()
    _shot(page, screenshots, "5-passage")


def test_a_word_file_is_shown_as_a_page(signed_in, app_url, screenshots):
    page = signed_in
    page.goto(f"{app_url}/doc/documents")
    page.locator("input[type=file]").set_input_files(
        {
            "name": "DOC-U100-SOP-002 Feed pump start-up.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": docx_bytes("Start-up", "Open FV-1003 slowly and check the flow on FIC-1003."),
        }
    )
    page.get_by_role("dialog").get_by_role("button", name="Send").click()
    row = page.get_by_role("row", name=re.compile("DOC-U100-SOP-002"))
    expect(row.get_by_text("Read", exact=True)).to_be_visible(timeout=20000)
    page.get_by_role("link", name="DOC-U100-SOP-002").click()
    page.get_by_role("link", name="Open the document").click()
    expect(page.locator(".doc-page h2", has_text="Start-up")).to_be_visible()
    expect(page.locator(".doc-page")).to_contain_text("Open FV-1003 slowly")
    _shot(page, screenshots, "6-word")


def test_the_library_keeps_its_old_links(signed_in, app_url):
    page = signed_in
    page.goto(f"{app_url}/doc/documents")
    expect(page.get_by_role("heading", name="Documents", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"^All")).first).to_be_visible()
