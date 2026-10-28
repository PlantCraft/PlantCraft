"""The library over HTTP: sending files, revisions, the original file, passages, folders and who
sees what, the search page and the reading queue (``api/routers/library.py``)."""

from __future__ import annotations

from tests.conftest import FILES, GUIDE, client_for, docx_bytes, guide, index, send

INCIDENT = (FILES / "incident.pdf").read_bytes()


def test_a_file_sent_is_queued_then_read_into_passages(client, runtime):
    doc = send(
        client,
        "INC-2026-007.pdf",
        INCIDENT,
        number="INC-2026-007",
        kind="Incident report",
        revision="0",
    )
    assert doc["current"]["status"] == "queued" and doc["title"] == "INC-2026-007"
    assert client.get("/api/queue").json()["queued"] == 1
    assert index(runtime) == 1
    read = client.get(f"/api/documents/{doc['doc_id']}").json()
    assert read["current"]["status"] == "indexed" and read["current"]["pages"] == 2
    assert read["can_edit"] and read["current"]["format"] == "pdf"
    # The tags found link the document to the plant's assets, as suggestions a person confirms.
    suggested = {a["asset_id"] for a in read["assets"] if a["source"] == "suggested"}
    passages = client.get(f"/api/documents/{doc['doc_id']}/passages").json()
    assert passages and passages[0]["page_from"] == 1
    page_two = client.get(f"/api/documents/{doc['doc_id']}/passages?page=2").json()
    assert page_two and all(p["page_from"] <= 2 <= p["page_to"] for p in page_two)
    assert suggested <= {"FIC-1001", "LIC-1010", "TIC-1104", "TIC-1209", "FIC-1210"}


def test_the_same_number_makes_a_new_revision_and_supersedes_the_old(client, runtime):
    first = guide(client, runtime, revision="A")
    second = send(
        client,
        "troubleshooting-b.md",
        GUIDE.replace("0.5 %", "1 %").encode(),
        number="DOC-TG-001",
        revision="B",
    )
    assert second["doc_id"] == first["doc_id"]
    index(runtime)
    doc = client.get(f"/api/documents/{first['doc_id']}").json()
    assert [r["revision"] for r in doc["revisions"]][:2] == ["B", "A"]
    assert doc["current"]["revision"] == "B" and doc["revisions"][1]["status"] == "superseded"
    found = client.post("/api/search", json={"query": "dead band steps"}).json()["passages"]
    assert found and all(p["revision"] == "B" for p in found)


def test_the_original_file_comes_back_as_sent_and_never_as_a_page(client, runtime):
    doc = send(client, "INC-2026-007.pdf", INCIDENT)
    answer = client.get(f"/api/documents/{doc['doc_id']}/file")
    assert answer.status_code == 200 and answer.content == INCIDENT
    assert answer.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in answer.headers["content-security-policy"]
    assert (
        client.get(f"/api/documents/{doc['doc_id']}/file?inline=true")
        .headers["content-disposition"]
        .startswith("inline;")
    )
    page = send(client, "x.html", b"<script>alert(1)</script>")
    shown = client.get(f"/api/documents/{page['doc_id']}/file?inline=true")
    assert shown.headers["content-disposition"].startswith("attachment;")
    assert shown.headers["content-type"].startswith("text/plain")


def test_a_file_the_library_does_not_take_is_refused_with_the_reason(client, runtime):
    assert (
        client.post("/api/documents", params={"filename": "a.pdf"}, content=b"").status_code == 422
    )
    refused = client.post("/api/documents", params={"filename": "tool.exe"}, content=b"MZ")
    assert refused.status_code == 422 and "PDF, Word" in refused.json()["detail"]
    broken = send(client, "broken.pdf", b"%PDF-1.7 nothing")
    index(runtime)
    current = client.get(f"/api/documents/{broken['doc_id']}").json()["current"]
    assert current["status"] == "failed" and current["error"]


def test_a_file_larger_than_the_limit_is_refused(tmp_path, fake):
    from tests.conftest import make_runtime

    runtime = make_runtime(tmp_path, fake, max_file_mb=1)
    try:
        with client_for(runtime, fake) as client:
            big = client.post(
                "/api/documents", params={"filename": "big.txt"}, content=b"x" * (2 * 2**20)
            )
            assert big.status_code == 413
    finally:
        runtime.shutdown()


def test_editors_change_documents_and_viewers_only_read(fake, client, runtime):
    doc = guide(client, runtime)
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get(f"/api/documents/{doc['doc_id']}").json()["can_edit"] is False
        assert (
            operator.post(
                "/api/documents", params={"filename": "a.md"}, content=b"text"
            ).status_code
            == 403
        )
        assert (
            operator.patch(f"/api/documents/{doc['doc_id']}", json={"title": "Mine"}).status_code
            == 403
        )
        assert operator.delete(f"/api/documents/{doc['doc_id']}").status_code == 403
        assert operator.post("/api/search", json={"query": "stiction"}).json()["passages"]
    with client_for(runtime, fake, "outsider") as outsider:
        assert outsider.get("/api/documents").status_code == 403
    changed = client.patch(
        f"/api/documents/{doc['doc_id']}", json={"title": "Loop guide", "unit": "U-200"}
    )
    assert changed.json()["title"] == "Loop guide"
    assert (
        client.patch(f"/api/documents/{doc['doc_id']}", json={"kind": "Novel"}).status_code == 422
    )
    assert client.delete(f"/api/documents/{doc['doc_id']}").status_code == 204
    assert client.get(f"/api/documents/{doc['doc_id']}").status_code == 404
    assert client.post("/api/search", json={"query": "stiction"}).json()["passages"] == []
    assert any(entry["action"] == "doccraft.document.delete" for entry in fake.audit_log)


def test_a_folder_kept_for_a_group_is_invisible_to_everyone_else(fake, client, runtime):
    folder = client.post(
        "/api/folders",
        json={
            "name": "Process control",
            "viewers": ["group:process-engineering"],
            "editors": ["user:engineer"],
        },
    ).json()
    doc = guide(client, runtime, folder=folder["folder_id"])
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get(f"/api/documents/{doc['doc_id']}").status_code == 404
        assert operator.get(f"/api/documents/{doc['doc_id']}/file").status_code == 404
        assert all(
            f["folder_id"] != folder["folder_id"] for f in operator.get("/api/folders").json()
        )
        assert operator.get("/api/documents").json() == []
        assert operator.post("/api/search", json={"query": "stiction"}).json()["passages"] == []
        # Nor its counts: the reading widget and the queue count what this person sees.
        reading = operator.get("/api/widgets/reading").json()["items"]
        assert reading[0]["detail"] == "0"
        assert operator.get("/api/queue").json()["passages"] == 0
    assert client.get("/api/widgets/reading").json()["items"][0]["detail"] != "0"
    with client_for(runtime, fake, "admin") as admin:
        assert admin.get(f"/api/documents/{doc['doc_id']}").status_code == 200
    # Only the folder's editors send to it; a folder with documents is not deleted.
    assert client.delete(f"/api/folders/{folder['folder_id']}").status_code == 409
    assert client.post("/api/folders", json={"name": "process control"}).status_code == 409
    assert client.post("/api/folders", json={"name": "General"}).status_code == 422
    assert (
        client.post("/api/folders", json={"name": "X", "viewers": ["everyone"]}).status_code == 422
    )


def test_a_document_is_linked_to_assets_by_a_person_and_found_by_them(client, runtime):
    doc = send(
        client, "start-up.docx", docx_bytes("Start-up", "Open the valve slowly and watch the flow.")
    )
    index(runtime)
    linked = client.put(
        f"/api/documents/{doc['doc_id']}/assets", json={"assets": ["asset:FIC-1001", "FIC-1001"]}
    )
    assert [a["asset_id"] for a in linked.json()["assets"] if a["source"] == "manual"] == [
        "FIC-1001"
    ]
    assert [d["doc_id"] for d in client.get("/api/documents?asset=asset:FIC-1001").json()] == [
        doc["doc_id"]
    ]
    assert client.get("/api/documents?asset=TIC-1104").json() == []
    assert (
        client.put(
            f"/api/documents/{doc['doc_id']}/assets", json={"assets": ["bad id!"]}
        ).status_code
        == 422
    )


def test_search_mixes_words_and_meaning_and_ranks_the_asset_asked_about(client, runtime):
    guide(client, runtime)
    answer = client.post(
        "/api/search", json={"query": "why does FIC-1001 cycle with a saw-tooth output?"}
    ).json()
    top = answer["passages"][0]
    assert top["section"].endswith("4.1 Valve stiction") and top["ref"].startswith("doc:")
    assert set(top["found_by"]) == {"words", "meaning"} and "FIC-1001" in top["assets"]
    assert top["url"].startswith("/doc/documents/")
    drift = client.post("/api/search", json={"query": "retune", "asset": "TIC-1209"}).json()[
        "passages"
    ]
    assert drift[0]["section"].endswith("4.2 Sensor drift")
    assert (
        client.post("/api/search", json={"query": "stiction", "kind": "Datasheet"}).json()[
            "passages"
        ]
        == []
    )
    assert client.post("/api/search", json={"query": ""}).status_code == 422


def test_the_queue_and_the_widgets_count_what_the_person_sees(client, runtime):
    guide(client, runtime)
    send(client, "later.md", b"# Later\n\nNot read yet, about TIC-1104 and its thermowell.")
    queue = client.get("/api/queue").json()
    assert queue["queued"] == 1 and queue["embedder"] == "hash-384"
    assert client.get("/api/widgets/count").json()["value"] == 2
    assert client.get("/api/widgets/latest").json()["items"]
    assert client.get("/api/widgets/reading").json()["items"][1]["detail"] == "1"
    assert client.get("/api/widgets/nope").status_code == 404


def test_the_count_says_how_many_are_ready_for_search_and_being_read(client, runtime):
    empty = client.get("/api/widgets/count").json()
    assert empty == {"kind": "number", "value": 0, "label": "documents", "href": "/doc/documents"}
    guide(client, runtime)
    assert client.get("/api/widgets/count").json()["label"] == "documents, all ready for search"
    send(client, "later.md", b"# Later\n\nNot read yet.")
    broken = send(client, "broken.pdf", b"%PDF-1.7 nothing")
    runtime.store.set_status(broken["current"]["rev_id"], "failed", "unreadable")
    count = client.get("/api/widgets/count").json()
    assert count["value"] == 3
    details = [item["detail"] for item in client.get("/api/widgets/unlinked").json()["items"]]
    assert "No tag found" in details and "0 tags found" not in details
    assert count["label"] == ("documents · 1 ready for search · 1 being read · 1 could not be read")


def test_documents_are_read_again_when_the_meaning_model_changes(client, runtime):
    doc = guide(client, runtime)
    assert runtime.store.requeue_other_embedder("hash-384") == 0
    assert runtime.store.requeue_other_embedder("multilingual-e5-small") == 1
    assert client.get(f"/api/documents/{doc['doc_id']}").json()["current"]["status"] == "queued"
    assert index(runtime) == 1


def test_an_unpinned_or_unreachable_model_builds_the_image_without_it(tmp_path):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "deploy" / "fetch_model.py"
    spec = importlib.util.spec_from_file_location("fetch_model", path)
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    lock = tmp_path / "embedding-model.lock"
    lock.write_text("# sha256  file  url\nunpinned  model.onnx  https://example.invalid/m.onnx\n")
    assert fetch.main(str(lock), str(tmp_path / "models")) == 0
    assert list((tmp_path / "models").iterdir()) == []
    # A pinned model the build machine cannot reach: built without it, no partial file kept.
    lock.write_text(f"{'0' * 64}  model.onnx  http://127.0.0.1:9/m.onnx\n")
    assert fetch.main(str(lock), str(tmp_path / "offline")) == 0
    assert list((tmp_path / "offline").iterdir()) == []


def test_a_folder_that_no_longer_exists_keeps_its_documents_for_administrators():
    """The same rule as View's folders (platform review I1, 2026-10-27)."""

    from doccraft.library.access import Permissions

    person = Permissions(username="engineer", admin=False, editor=True, groups=set())
    admin = Permissions(username="admin", admin=True, editor=True, groups=set())
    assert not person.sees_folder("gone") and not person.edits_folder("gone")
    assert admin.sees_folder("gone") and admin.edits_folder("gone")
    assert person.sees_folder("") and person.edits_folder("")
