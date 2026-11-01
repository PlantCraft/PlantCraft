"""Drawings sent, read, replaced and removed, and the licence the app runs under
(PlantCraft docs/app-package.md, section 8)."""

from __future__ import annotations

from plantcraft_sdk import licensing

from pidcraft.plantmap.sample.draw import draw_all
from tests.conftest import KEY, client_for, index, licence_body, licence_for, make_runtime, send


def _svg(n: int = 0) -> tuple[bytes, dict]:
    _, canvas, key = draw_all()[n]
    return canvas.svg().encode(), key


def test_a_drawing_is_sent_read_and_replaced_by_number(runtime, fake, client):
    data, key = _svg(0)
    first = send(client, "sheet.svg", data, number=key["sheet"], title="Feed", unit="U-100")
    assert first["status"] == "queued"
    assert index(runtime) == 1
    listed = client.get("/api/drawings").json()
    assert [(d["number"], d["status"], d["unit"]) for d in listed] == [
        (key["sheet"], "read", "U-100")
    ]
    assert listed[0]["diagrams"] == 1
    again = send(client, "sheet-rev-b.svg", data, number=key["sheet"])
    assert again["drawing_id"] == first["drawing_id"]
    index(runtime)
    one = client.get(f"/api/drawings/{first['drawing_id']}").json()
    assert one["filename"] == "sheet-rev-b.svg" and len(one["pages"]) == 1
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get("/api/drawings").status_code == 200
        assert operator.delete(f"/api/drawings/{first['drawing_id']}").status_code == 403
    assert client.delete(f"/api/drawings/{first['drawing_id']}").json() == {"deleted": True}
    assert client.get("/api/drawings").json() == []
    assert not list((runtime.settings.data_dir / "files").iterdir())


def test_a_file_that_is_no_drawing_is_refused(client):
    answer = client.post("/api/drawings", params={"filename": "a.txt"}, content=b"hello")
    assert answer.status_code == 422 and "PDF, SVG" in answer.json()["detail"]
    empty = client.post("/api/drawings", params={"filename": "a.svg"}, content=b"")
    assert empty.status_code == 422


def test_without_a_licence_the_api_answers_402_but_the_frame_opens(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake, licence=licence_for(None))
    try:
        with client_for(runtime, fake) as client:
            refused = client.get("/api/drawings")
            assert refused.status_code == 402
            assert refused.json()["license"]["status"] == "missing"
            assert client.get("/api/meta").status_code == 200
            assert client.get("/api/license").json()["status"] == "missing"
            assert client.get("/healthz").status_code == 200
    finally:
        runtime.shutdown()


def test_a_licence_of_another_app_or_ended_beyond_grace_stops_it(tmp_path, fake):
    for body in (licence_body(app="doccraft"), licence_body(expires="2026-01-02")):
        runtime = make_runtime(tmp_path, fake, licence=licence_for(licensing.issue(KEY, body)))
        try:
            with client_for(runtime, fake) as client:
                assert client.get("/api/drawings").status_code == 402
        finally:
            runtime.shutdown()


def test_a_licence_signed_by_another_key_is_refused(tmp_path, fake):
    other = licensing.issue(licensing.new_key(), licence_body())
    runtime = make_runtime(tmp_path, fake, licence=licence_for(other))
    try:
        with client_for(runtime, fake) as client:
            state = client.get("/api/license").json()
            assert state["status"] == "invalid" and "signature" in state["message"]
    finally:
        runtime.shutdown()


def test_the_licence_limits_how_many_drawings(tmp_path, fake):
    data = licensing.issue(KEY, licence_body(limits={"sheets": 1}))
    runtime = make_runtime(tmp_path, fake, licence=licence_for(data))
    try:
        with client_for(runtime, fake) as client:
            svg, key = _svg(0)
            send(client, "a.svg", svg, number=key["sheet"])
            other, other_key = _svg(1)
            over = client.post(
                "/api/drawings",
                params={"filename": "b.svg", "number": other_key["sheet"]},
                content=other,
            )
            assert over.status_code == 402 and "allows 1" in over.json()["detail"]
            # A new file of the same drawing is not a new drawing.
            send(client, "a2.svg", svg, number=key["sheet"])
    finally:
        runtime.shutdown()


def test_the_real_publisher_key_is_in_the_code():
    from pidcraft.licence import PUBLISHER_KEY

    key = licensing.load_public_key(PUBLISHER_KEY)
    assert key is not None
