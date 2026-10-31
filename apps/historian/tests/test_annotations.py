"""Notes on a signal at an instant or over an interval, told to PlantCraft as events (H8)."""

from __future__ import annotations

from histcraft.catalog.models import PointIn, SourceIn
from tests.conftest import client_for

NOTES = "/hist/api/v1/annotations"


def _signal(runtime, tag="FI-101"):
    runtime.catalog.save_source(
        SourceIn(id="plant", name="plant", endpoint="opc.tcp://127.0.0.1:4999"), create=True
    )
    runtime.catalog.add_points([PointIn(tag=tag, source_id="plant", low=0, high=10)])
    return f"plant:{tag}"


def test_a_note_is_kept_read_by_window_and_answers_its_event(client, runtime):
    signal = _signal(runtime)
    made = client.post(
        NOTES,
        json={
            "signal": signal,
            "at": "2026-10-31T14:00:00Z",
            "end": "2026-10-31T15:30:00Z",
            "text": "  Pump B on manual  ",
        },
    )
    assert made.status_code == 201, made.text
    note = made.json()
    assert (note["text"], note["author"], note["end"]) == (
        "Pump B on manual",
        "admin",
        "2026-10-31T15:30:00+00:00",
    )
    event = note["event"]
    assert event["kind"] == "histcraft.annotation.added" and event["app"] == "histcraft"
    assert event["subject"] == f"signal:{signal}" and event["payload"]["annotation"] == note["id"]
    instant = client.post(
        NOTES, json={"signal": signal, "at": "2026-10-31T18:00:00+00:00", "text": "Recalibrated"}
    ).json()
    assert instant["end"] is None

    def read(start, end, **more):
        params = {"start": start, "end": end, **more}
        return [item["text"] for item in client.get(NOTES, params=params).json()["notes"]]

    # an interval that overlaps the window counts; the instant only inside it
    assert read("2026-10-31T15:00:00Z", "2026-10-31T16:00:00Z") == ["Pump B on manual"]
    assert read("2026-10-31T13:00:00Z", "2026-10-31T19:00:00Z", signal=signal) == [
        "Pump B on manual",
        "Recalibrated",
    ]
    assert read("2026-10-31T16:00:00Z", "2026-10-31T17:00:00Z") == []


def test_notes_are_checked_and_removed_by_their_author_or_an_administrator(client, runtime, fake):
    signal = _signal(runtime)
    bad = [
        {"signal": "plant:NOPE", "at": "2026-10-31T14:00:00Z", "text": "x"},
        {"signal": signal, "at": "yesterday", "text": "x"},
        {"signal": signal, "at": "2026-10-31T14:00:00Z", "text": "   "},
        {
            "signal": signal,
            "at": "2026-10-31T14:00:00Z",
            "end": "2026-10-31T13:00:00Z",
            "text": "x",
        },
    ]
    assert [client.post(NOTES, json=body).status_code for body in bad] == [404, 422, 422, 422]
    with (
        client_for(runtime, fake, "engineer") as engineer,
        client_for(runtime, fake, "operator") as operator,
    ):
        note = engineer.post(
            NOTES, json={"signal": signal, "at": "2026-10-31T14:00:00Z", "text": "Mine"}
        ).json()
        other = client.post(
            NOTES, json={"signal": signal, "at": "2026-10-31T14:00:00Z", "text": "Admin's"}
        ).json()
        assert (
            operator.post(
                NOTES, json={"signal": signal, "at": "2026-10-31T14:00:00Z", "text": "x"}
            ).status_code
            == 403
        )
        assert operator.get(NOTES, params={"signal": signal}).status_code == 200
        assert engineer.delete(f"{NOTES}/{other['id']}").status_code == 403
        assert engineer.delete(f"{NOTES}/{note['id']}").status_code == 204
        assert client.delete(f"{NOTES}/{other['id']}").status_code == 204
        assert client.delete(f"{NOTES}/{other['id']}").status_code == 404
