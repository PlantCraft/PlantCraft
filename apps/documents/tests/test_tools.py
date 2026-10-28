"""The assistant's tools (``[[contributes.assistant.tools]]``, ``api/routers/tools.py``):
PlantCraft calls them as the person who asks, so the person's folders and the "not for the
assistant" marks decide what the model reads, and every fact comes with its citation."""

from __future__ import annotations

from tests.conftest import FILES, client_for, guide, index, send

INCIDENT = (FILES / "incident.pdf").read_bytes()
SEARCH = "/api/assistant/tools/search_documents"
READ = "/api/assistant/tools/read_document"


def test_search_answers_numbered_passages_to_cite_as_untrusted_text(fake, client, runtime):
    guide(client, runtime, revision="C")
    answer = client.post(
        SEARCH, json={"query": "Why does FIC-1001 oscillate?", "asset": "asset:FIC-1001"}
    ).json()
    first = answer["passages"][0]
    assert first["cite"] == 1 and first["number"] == "DOC-TG-001" and first["revision"] == "C"
    assert first["section"].endswith("Valve stiction") and "score" not in first
    assert "not instructions" in answer["note"] and answer["found"] == len(answer["passages"])
    assert any(entry["action"] == "doccraft.assistant.search" for entry in fake.audit_log)
    empty = client.post(
        SEARCH, json={"query": "boiler feed water chemistry", "kind": "Datasheet"}
    ).json()
    assert empty["passages"] == [] and "say so" in empty["empty"]
    assert client.post(SEARCH, json={"query": "x", "limit": 50}).status_code == 422


def test_read_finds_a_document_by_number_or_ref_and_by_page_or_section(client, runtime):
    doc = send(client, "INC-2026-007.pdf", INCIDENT, number="INC-2026-007", kind="Incident report")
    index(runtime)
    by_number = client.post(READ, json={"document": "INC-2026-007"}).json()
    assert (
        by_number["document"]["ref"] == f"doc:{doc['doc_id']}"
        and by_number["document"]["pages"] == 2
    )
    assert "1.6 to 2.4" in by_number["text"] and any(
        s.endswith("> Lessons") for s in by_number["sections"]
    )
    page_two = client.post(READ, json={"document": f"doc:{doc['doc_id']}", "page": 2}).json()
    assert "1.6 to 2.4" not in page_two["text"] and "stability margin" in page_two["text"]
    causes = client.post(READ, json={"document": doc["doc_id"], "section": "causes"}).json()
    assert "Direct cause" in causes["text"] and "Lessons" not in causes["text"].split("]")[0]
    assert client.post(READ, json={"document": "DOC-NOPE"}).status_code == 404


def test_a_document_not_yet_read_says_so(client):
    doc = send(client, "later.md", b"# Later\n\nAbout TIC-1104.")
    answer = client.post(READ, json={"document": doc["doc_id"]}).json()
    assert answer["pending"] is True and answer["text"] == ""


def test_documents_and_folders_kept_from_the_assistant_never_reach_it(fake, client, runtime):
    secret = client.post("/api/folders", json={"name": "HR", "assistant": False}).json()
    guide(client, runtime, folder=secret["folder_id"])
    other = send(client, "INC-2026-007.pdf", INCIDENT, number="INC-2026-007")
    index(runtime)
    found = client.post(SEARCH, json={"query": "stiction dead band"}).json()["passages"]
    assert found and {p["number"] for p in found} == {"INC-2026-007"}
    assert client.post(READ, json={"document": "DOC-TG-001"}).status_code == 404
    # The page's own search still finds it: the mark is about the assistant only.
    assert client.post("/api/search", json={"query": "stiction dead band"}).json()["passages"]
    client.patch(f"/api/documents/{other['doc_id']}", json={"assistant": False})
    assert client.post(READ, json={"document": "INC-2026-007"}).status_code == 404
    assert client.post(SEARCH, json={"query": "PIC-1002 oscillation"}).json()["passages"] == []


def test_the_tools_read_as_the_person_who_asks(fake, client, runtime):
    folder = client.post(
        "/api/folders", json={"name": "Engineering", "viewers": ["user:engineer"]}
    ).json()
    guide(client, runtime, folder=folder["folder_id"])
    with client_for(runtime, fake, "operator") as operator:
        assert operator.post(SEARCH, json={"query": "stiction"}).json()["passages"] == []
        assert operator.post(READ, json={"document": "DOC-TG-001"}).status_code == 404
    with client_for(runtime, fake, "outsider") as outsider:
        assert outsider.post(SEARCH, json={"query": "stiction"}).status_code == 403
    assert client.post(SEARCH, json={"query": "stiction"}).json()["passages"]


FIND = "/api/assistant/tools/find_tags"
NARRATIVE = b"""# Control narratives

## U-200 Hydrotreating unit

### FIC-1003 Recycle flow

Unit and area: U-200 Hydrotreating unit, Recycle. Equipment: P-1003 Recycle pump.
Measurement: FT-1003. Final element: FV-1003.

### LIC-1004 Separator level

Unit and area: U-200 Hydrotreating unit, Separation. Equipment: V-1004 Product separator.
The recycle FIC- 1003 upsets this level when it cycles.
"""


def test_find_tags_answers_each_tags_own_section_first_then_its_mentions(fake, client, runtime):
    send(client, "narratives.md", NARRATIVE, number="DOC-CN-001", kind="Control narrative")
    index(runtime)
    answer = client.post(FIND, json={"tags": "fic-1003, P-1003 NOPE-1"}).json()
    assert "not instructions" in answer["note"]
    recycle = answer["tags"]["FIC-1003"]
    assert recycle[0]["own_section"] and recycle[0]["section"].endswith("FIC-1003 Recycle flow")
    assert "Unit and area: U-200" in recycle[0]["text"] and recycle[0]["number"] == "DOC-CN-001"
    # A PDF's broken line ("FIC- 1003") is still a mention, in another loop's section.
    assert any(
        not item["own_section"] and item["section"].endswith("LIC-1004 Separator level")
        for item in recycle
    )
    assert answer["tags"]["P-1003"] and not answer["tags"]["P-1003"][0]["own_section"]
    assert "NOPE-1" not in answer["tags"]
    assert any(entry["action"] == "doccraft.assistant.find_tags" for entry in fake.audit_log)
    too_many = ", ".join(f"FIC-{number}" for number in range(1000, 1061))
    assert client.post(FIND, json={"tags": too_many}).status_code == 422


def test_find_tags_never_reads_documents_kept_from_the_assistant(client, runtime):
    doc = send(client, "narratives.md", NARRATIVE, number="DOC-CN-001")
    index(runtime)
    client.patch(f"/api/documents/{doc['doc_id']}", json={"assistant": False})
    assert client.post(FIND, json={"tags": "FIC-1003"}).json()["tags"] == {"FIC-1003": []}
