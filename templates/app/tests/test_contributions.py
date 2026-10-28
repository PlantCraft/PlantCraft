"""What StarterCraft adds to PlantCraft (``app.toml [contributes]``, ``starter.suite``): the
follow-ups on Desk's calendar and in a person's to-do, the summary from a model, and what a
``#starter_note:<id>`` names."""

from __future__ import annotations

from plantcraft_sdk import apptest

from tests.conftest import client_for, note


def test_a_follow_up_goes_to_the_calendar_and_to_the_persons_todo(fake, client):
    body = note(follow_up="2026-11-03", follow_up_by="operator")
    note_id = client.post("/api/notes", json=body).json()["note_id"]
    [item] = fake.links.calendar[("starter", "follow-ups")]
    assert item["start"].startswith("2026-11-03") and item["audience"] == "user:operator"
    assert item["url"] == f"/starter/notes/{note_id}"
    todo = fake.links.todos[("starter", f"note:{note_id}")]
    assert todo["kind"] == "follow-up" and todo["for"] == "user:operator"


def test_the_todo_closes_when_the_note_no_longer_asks_or_goes(fake, client):
    note_id = client.post(
        "/api/notes", json=note(follow_up="2026-11-03", follow_up_by="operator")
    ).json()["note_id"]
    assert client.put(f"/api/notes/{note_id}", json=note()).status_code == 200
    assert ("starter", f"note:{note_id}") not in fake.links.todos
    assert fake.links.calendar[("starter", "follow-ups")] == []
    again = client.post(
        "/api/notes", json=note(follow_up="2026-11-04", follow_up_by="operator")
    ).json()["note_id"]
    assert client.delete(f"/api/notes/{again}").status_code == 204
    assert not fake.links.todos and fake.links.calendar[("starter", "follow-ups")] == []


def test_a_note_without_a_follow_up_sends_no_todo(fake, client):
    client.post("/api/notes", json=note())
    assert not fake.links.todos


def test_the_summary_comes_from_the_model_plantcraft_gives_the_use(fake, client):
    note_id = client.post("/api/notes", json=note()).json()["note_id"]
    fake.links.llm_answer = "The valve sticks at low opening."
    answer = client.post(f"/api/notes/{note_id}/summary")
    assert (
        answer.status_code == 200 and answer.json()["summary"] == "The valve sticks at low opening."
    )
    [call] = fake.links.llm_calls
    assert call["use"] == "summary" and "Valve sticks" in call["messages"][-1]["content"]


def test_without_a_model_the_summary_says_so(fake, client):
    note_id = client.post("/api/notes", json=note()).json()["note_id"]
    fake.links.llm_answer = None  # off, as app.toml ships it
    answer = client.post(f"/api/notes/{note_id}/summary")
    assert answer.status_code == 409 and "Setup" in answer.json()["detail"]


def test_a_reference_names_the_note_for_whoever_reads_it(runtime, fake, client):
    note_id = client.post("/api/notes", json=note(follow_up="2026-11-03")).json()["note_id"]
    with client_for(runtime, fake, "operator") as operator:
        ref = operator.get(f"/api/refs/starter_note/{note_id}")
        assert operator.get("/api/refs/starter_note/nowhere").status_code == 404
    assert ref.status_code == 200
    assert ref.json() == {
        "title": note()["text"],
        "status": "follow-up",
        "url": f"/starter/notes/{note_id}",
    }


def test_the_widgets_answer_in_the_shapes_app_toml_declares(client):
    client.post("/api/notes", json=note())
    assert apptest.widget_problems(client, "") == []
    assert client.get("/api/widgets/count").json()["value"] == 1
