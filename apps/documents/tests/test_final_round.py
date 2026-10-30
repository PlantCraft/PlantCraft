"""The final review round: a document's description, the latest documents
with when, the reading queue in the suite's Queue, search words carried to the passage, and a
Word file shown as a page."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from plantcraft_sdk.server.queue import FORMAT

from tests.conftest import docx_bytes, guide, index, send


def test_a_document_has_a_description_that_the_search_finds(client, runtime):
    doc = send(
        client,
        "DOC-U100-NOTE-001 Notes.md",
        b"# Notes\n\nThe furnace draft is set by hand.",
        number="DOC-U100-NOTE-001",
        title="Notes",
        description="Shift handover notes for the crude heater",
    )
    assert doc["description"] == "Shift handover notes for the crude heater"
    index(runtime)
    changed = client.patch(
        f"/api/documents/{doc['doc_id']}", json={"description": "Heater shift notes"}
    ).json()
    assert changed["description"] == "Heater shift notes"
    listed = client.get("/api/documents").json()
    assert listed[0]["description"] == "Heater shift notes"
    # Its words count as the title's: a search by them finds its passages.
    hits = client.post("/api/search", json={"query": "shift notes"}).json()["passages"]
    assert hits and hits[0]["doc_id"] == doc["doc_id"]
    too_long = client.patch(f"/api/documents/{doc['doc_id']}", json={"description": "x" * 1001})
    assert too_long.status_code == 422


def test_a_passage_found_opens_with_the_words_of_the_search(client, runtime):
    guide(client, runtime)
    hits = client.post("/api/search", json={"query": "valve stiction"}).json()["passages"]
    url = urlparse(hits[0]["url"])
    assert url.path.endswith(f"/documents/{hits[0]['doc_id']}")
    query = parse_qs(url.query)
    assert query["passage"] == [str(hits[0]["passage_id"])] and query["q"] == ["valve stiction"]
    # The assistant's search gives the same links, numbered for its citations.
    tool = client.post(
        "/api/assistant/tools/search_documents", json={"query": "valve stiction"}
    ).json()
    first = tool["passages"][0]
    assert first["cite"] == 1 and "q=valve%20stiction" in first["url"]


def test_the_latest_documents_say_when(client, runtime):
    guide(client, runtime)
    latest = client.get("/api/widgets/latest").json()["items"][0]
    assert latest["detail"].endswith("just now") and " · " in latest["detail"]


def test_the_reading_queue_is_in_the_suite_format(client, runtime):
    guide(client, runtime)
    later = send(client, "later.md", b"# Later\n\nNot read yet.")
    queue = client.get("/api/queue").json()
    assert queue["format"] == FORMAT and queue["url"] == "documents"
    assert queue["now"]["queued"] == 1 and queue["now"]["running"] == 0
    by_status = {item["status"]: item for item in queue["items"]}
    assert by_status["queued"]["url"] == f"/doc/documents/{later['doc_id']}"
    # A file read in the last day stays, done.
    assert by_status["done"]["finished_at"]


def test_a_word_file_shows_as_a_page_with_its_text_escaped(client, runtime):
    data = docx_bytes("Start-up", "Open <b>FV-1003</b> slowly & check the flow.")
    doc = send(client, "procedure.docx", data, title="Start-up procedure")
    index(runtime)
    page = client.get(f"/api/documents/{doc['doc_id']}/view").json()
    assert "<h2>Start-up</h2>" in page["html"]
    assert "&lt;b&gt;FV-1003&lt;/b&gt; slowly &amp; check" in page["html"]
    assert "<b>" not in page["html"]
    markdown = guide(client, runtime)
    assert client.get(f"/api/documents/{markdown['doc_id']}/view").status_code == 404
