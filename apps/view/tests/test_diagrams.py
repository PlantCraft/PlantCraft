"""Diagrams: saved, versioned, filed in folders, and read as one batch for live view and playback."""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest
from plantcraft_sdk.asset_scope import forget

from dashcraft.diagrams.model import DiagramPayload, Limits
from dashcraft.diagrams.read import judge, read_diagram
from dashcraft.query.cards import Reader
from tests.conftest import client_for
from tests.plant import NOW, publish_loop_health


def unit(**fields) -> dict:
    """A small unit: tank, pump, control valve, a controller bubble, values, a line and a text."""

    return {
        "name": "Feed section",
        "elements": [
            {
                "id": "tk1",
                "type": "symbol",
                "symbol": "vessel.tank",
                "x": 100,
                "y": 100,
                "w": 80,
                "h": 120,
                "label": "TK-1",
                "asset_id": "lic-102",
                "level": {"item": {"asset_id": "lic-102", "role": "pv"}, "min": 0, "max": 100},
            },
            {
                "id": "p1",
                "type": "symbol",
                "symbol": "pump.centrifugal",
                "x": 260,
                "y": 200,
                "running": {"item": {"asset_id": "p-201", "role": "flow"}, "above": 1},
            },
            {
                "id": "fic",
                "type": "symbol",
                "symbol": "instrument.bubble",
                "x": 400,
                "y": 80,
                "w": 40,
                "h": 40,
                "label": "FIC-101",
                "state": {"item": {"asset_id": "fic-101", "result": "linkcraft.loop_health"}},
            },
            {
                "id": "pv",
                "type": "value",
                "x": 400,
                "y": 130,
                "label": "PV",
                "item": {"asset_id": "fic-101", "role": "pv"},
                "limits": {"high_warning": 1e9},
            },
            {
                "id": "l1",
                "type": "line",
                "start": {"element": "tk1", "port": "out"},
                "end": {"element": "p1", "port": "in"},
                "points": [[140, 240], [266, 232]],
                "medium": "water",
                "flow": {"item": {"signal_id": "fake:P-201.FLOW"}},
            },
            {"id": "t1", "type": "text", "x": 20, "y": 30, "text": "Unit 100 feed", "size": 18},
        ],
        **fields,
    }


def test_a_diagram_is_saved_versioned_and_listed(client):
    created = client.post("/dash/api/diagrams", json=unit())
    assert created.status_code == 201, created.text
    body = created.json()
    diagram_id = body["diagram_id"]
    assert body["element_count"] == 6 and body["can_edit"] and body["width"] == 1600
    listed = client.get("/dash/api/diagrams").json()
    assert [item["diagram_id"] for item in listed] == [diagram_id]
    assert "elements" not in listed[0]
    again = client.put(
        f"/dash/api/diagrams/{diagram_id}",
        json={**unit(name="Feed"), "base_updated_at": body["updated_at"]},
    )
    assert again.status_code == 200, again.text
    stale = client.put(
        f"/dash/api/diagrams/{diagram_id}",
        json={**unit(), "base_updated_at": body["updated_at"]},
    )
    assert stale.status_code == 409 and stale.json()["current"]["name"] == "Feed"
    versions = client.get(f"/dash/api/diagrams/{diagram_id}/versions").json()
    assert [item["version"] for item in versions] == [2, 1]
    first = client.get(f"/dash/api/diagrams/{diagram_id}/versions/1").json()
    assert first["diagram"]["name"] == "Feed section"
    assert client.delete(f"/dash/api/diagrams/{diagram_id}").status_code == 204
    assert client.get(f"/dash/api/diagrams/{diagram_id}").status_code == 404


def test_viewers_open_diagrams_and_only_editors_draw_them(client, runtime, fake):
    diagram_id = client.post("/dash/api/diagrams", json=unit()).json()["diagram_id"]
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get(f"/dash/api/diagrams/{diagram_id}").json()["can_edit"] is False
        assert operator.post("/dash/api/diagrams", json=unit()).status_code == 403
        assert operator.put(f"/dash/api/diagrams/{diagram_id}", json=unit()).status_code == 403
        assert operator.delete(f"/dash/api/diagrams/{diagram_id}").status_code == 403
    with client_for(runtime, fake, "outsider") as outsider:
        assert outsider.get("/dash/api/diagrams").status_code == 403
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get("/dash/api/diagrams").status_code == 401


def test_a_closed_folder_hides_its_diagrams(client, runtime, fake):
    folder = client.post(
        "/dash/api/folders", json={"name": "Engineering", "viewers": ["user:engineer"]}
    )
    assert folder.status_code == 201, folder.text
    folder_id = folder.json()["folder_id"]
    diagram_id = client.post("/dash/api/diagrams", json=unit(folder_id=folder_id)).json()[
        "diagram_id"
    ]
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get("/dash/api/diagrams").json() == []
        assert operator.get(f"/dash/api/diagrams/{diagram_id}").status_code == 404
        assert operator.get(f"/dash/api/diagrams/{diagram_id}/data").status_code == 404
    # A folder that still files a diagram is not deleted.
    assert client.delete(f"/dash/api/folders/{folder_id}").status_code == 409


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"elements": [{"id": "a", "type": "line", "points": [[0, 0]]}]}, "two ends"),
        (
            {
                "elements": [
                    {"id": "a", "type": "line", "start": {"element": "x"}, "points": [[1, 1]]}
                ]
            },
            "not a symbol",
        ),
        (
            {"elements": [{"id": "a", "type": "text", "text": "x"}] * 2},
            "same id",
        ),
        ({"refresh_seconds": 7}, "Refresh"),
        ({"elements": [{"id": "a", "type": "symbol", "symbol": "../etc"}]}, "pattern"),
        ({"elements": [{"id": "a", "type": "gauge"}]}, "tag"),
        (
            {
                "elements": [
                    {
                        "id": "a",
                        "type": "value",
                        "item": {"signal_id": "fake:FIC-101.PV"},
                        "limits": {"low_alarm": 10, "high_alarm": 5},
                    }
                ]
            },
            "Limits go",
        ),
    ],
)
def test_a_diagram_that_cannot_be_drawn_is_refused_with_a_reason(client, change, words):
    answer = client.post("/dash/api/diagrams", json={**unit(), **change})
    assert answer.status_code == 422
    assert words in answer.text


def test_the_data_reads_every_binding_and_the_window(client, fake):
    publish_loop_health(fake)
    diagram_id = client.post("/dash/api/diagrams", json=unit()).json()["diagram_id"]
    data = client.get(f"/dash/api/diagrams/{diagram_id}/data", params={"window": "2h"})
    assert data.status_code == 200, data.text
    body = data.json()
    rows = {(row["element"], row["slot"]): row for row in body["bindings"]}
    assert set(rows) == {
        ("tk1", "level"),
        ("p1", "running"),
        ("fic", "state"),
        ("pv", "value"),
        ("l1", "flow"),
    }
    level = rows[("tk1", "level")]
    assert level["error"] is None and level["value"] is not None
    assert 0 <= level["fraction"] <= 1
    assert rows[("fic", "state")]["state"] == "warning"
    assert rows[("fic", "state")]["summary"] == "Oscillating, period 4 min"
    assert rows[("pv", "value")]["state"] == "ok" and rows[("pv", "value")]["unit"]
    assert rows[("p1", "running")]["on"] in (True, False)
    assert body["range"]["live"] is True
    # One series per signal, on the window's grid, for playback.
    series = body["series"]
    assert set(series) == {"fake:LIC-102.PV", "fake:P-201.FLOW", "fake:FIC-101.PV"}
    assert all(len(line["t"]) == len(line["v"]) > 10 for line in series.values())


def test_a_past_window_takes_its_values_from_the_series(client):
    diagram_id = client.post("/dash/api/diagrams", json=unit()).json()["diagram_id"]
    end = (NOW - timedelta(hours=3)).isoformat()
    body = client.get(
        f"/dash/api/diagrams/{diagram_id}/data", params={"window": "1h", "end": end}
    ).json()
    assert body["range"]["live"] is False and body["range"]["end"].startswith("2026-10-01T09:00")
    level = next(row for row in body["bindings"] if row["slot"] == "level")
    assert level["value"] is not None and level["at"] <= body["range"]["end"]
    result = next(row for row in body["bindings"] if row["slot"] == "state")
    assert result["history"] is False


def test_bad_bindings_grey_out_and_the_rest_still_draws(client):
    broken = unit()
    broken["elements"].append(
        {
            "id": "gone",
            "type": "value",
            "x": 0,
            "y": 0,
            "item": {"asset_id": "fic-109", "role": "pv"},
        }
    )
    broken["elements"].append(
        {
            "id": "norole",
            "type": "value",
            "x": 0,
            "y": 0,
            "item": {"asset_id": "p-201", "role": "level"},
        }
    )
    broken["elements"].append(
        {
            "id": "noasset",
            "type": "symbol",
            "symbol": "valve.gate",
            "state": {"item": {"asset_id": "nowhere", "role": "pv"}},
        }
    )
    diagram_id = client.post("/dash/api/diagrams", json=broken).json()["diagram_id"]
    body = client.get(f"/dash/api/diagrams/{diagram_id}/data").json()
    rows = {row["element"]: row for row in body["bindings"]}
    for element in ("gone", "norole", "noasset"):
        assert rows[element]["error"] and rows[element]["state"] == "unknown"
    assert rows["pv"]["error"] is None and rows["pv"]["value"] is not None


def test_a_person_limited_to_part_of_the_plant_reads_as_themselves(client, runtime, fake):
    forget()
    diagram_id = client.post("/dash/api/diagrams", json=unit()).json()["diagram_id"]
    from fastapi.testclient import TestClient

    from dashcraft.api.app import create_app

    limited = TestClient(create_app(runtime), raise_server_exceptions=False)
    limited.headers["Authorization"] = f"Bearer {fake.token('operator', assets=['lic-102'])}"
    with limited:
        body = limited.get(f"/dash/api/diagrams/{diagram_id}/data").json()
    rows = {row["element"]: row for row in body["bindings"]}
    assert rows["tk1"]["error"] is None and rows["tk1"]["value"] is not None
    assert rows["pv"]["value"] is None and rows["pv"]["error"]
    forget()


def test_an_editor_previews_a_drawing_before_saving(client, runtime, fake):
    body = client.post("/dash/api/diagrams/preview", json={"diagram": unit()})
    assert body.status_code == 200, body.text
    assert len(body.json()["bindings"]) == 5
    with client_for(runtime, fake, "operator") as operator:
        assert (
            operator.post("/dash/api/diagrams/preview", json={"diagram": unit()}).status_code == 403
        )


def test_the_editor_lists_an_assets_roles(client):
    roles = client.get("/dash/api/diagram-assets/fic-101/signals").json()
    assert {"role": "pv", "signal": "fake:FIC-101.PV"} in roles
    assert client.get("/dash/api/diagram-assets/nowhere/signals").json() == []


def test_limits_and_slots_judge_a_value():
    limits = Limits(low_alarm=0, low_warning=10, high_warning=80, high_alarm=90)
    assert [limits.state(v) for v in (-1, 5, 50, 85, 95)] == [
        "alarm",
        "warning",
        "ok",
        "warning",
        "alarm",
    ]
    assert limits.state(float("nan")) == "unknown" and limits.state("AUTO") == "unknown"
    assert judge("level", {"min": 0, "max": 50}, {"value": 100})["fraction"] == 1.0
    assert judge("running", {"above": 1}, {"value": 0.2})["on"] is False
    assert judge("value", {}, {"value": 3, "stale": True})["state"] == "unknown"


def test_a_value_older_than_the_stale_limit_is_unknown(runtime, fake):
    reader, _ = runtime.dashboard_reader(None)
    diagram = DiagramPayload.model_validate(unit()).stored()
    fresh = read_diagram(reader, diagram, "1h")
    stale = read_diagram(reader, diagram, "1h", stale_seconds=-1)
    level = lambda data: next(row for row in data["bindings"] if row["slot"] == "level")  # noqa: E731
    assert level(fresh)["stale"] is False and level(fresh)["state"] == "ok"
    assert level(stale)["stale"] is True and level(stale)["state"] == "unknown"


def _paged() -> dict:
    """The unit on two pages: the tank and pump with their line on the first, the controller,
    its value and the text on the second, and a text on the first that opens the second."""

    body = unit()
    for element in body["elements"]:
        element["page"] = "feed" if element["id"] in ("tk1", "p1", "l1") else "ctl"
    body["elements"].append(
        {
            "id": "go",
            "type": "text",
            "x": 10,
            "y": 10,
            "text": "Control ›",
            "page": "feed",
            "link": {"kind": "page", "target": "ctl"},
        }
    )
    return {**body, "pages": [{"id": "feed", "name": "Feed"}, {"id": "ctl", "name": "Control"}]}


def test_a_diagram_has_pages_and_each_page_reads_only_its_own(client, fake):
    publish_loop_health(fake)
    saved = client.post("/dash/api/diagrams", json=_paged())
    assert saved.status_code == 201, saved.text
    diagram_id = saved.json()["diagram_id"]
    full = client.get(f"/dash/api/diagrams/{diagram_id}").json()
    assert [page["name"] for page in full["pages"]] == ["Feed", "Control"]

    def read(page):
        params = {"window": "1h", **({"page": page} if page else {})}
        rows = client.get(f"/dash/api/diagrams/{diagram_id}/data", params=params).json()["bindings"]
        return {row["element"] for row in rows}

    assert read("feed") == {"tk1", "p1", "l1"}
    assert read("ctl") == {"fic", "pv"}
    assert read(None) == {"tk1", "p1", "l1", "fic", "pv"}


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (
            lambda body: body["elements"][0].update(page="nowhere"),
            "a page the process display does not have",
        ),
        (lambda body: body["elements"][-1]["link"].update(target="nowhere"), "opens a page"),
        (lambda body: body["elements"][1].update(page="ctl"), "not a symbol on its page"),
        (lambda body: body["pages"].append({"id": "feed", "name": "Again"}), "same id"),
    ],
)
def test_pages_that_do_not_hold_together_are_refused(client, change, words):
    body = _paged()
    change(body)
    refused = client.post("/dash/api/diagrams", json=body)
    assert refused.status_code == 422 and words in refused.text, refused.text


def test_an_element_without_a_page_is_on_the_first():
    body = _paged()
    body["elements"][0]["page"] = ""
    stored = DiagramPayload.model_validate(body).stored()
    assert stored["elements"][0]["page"] == "feed"


def test_an_area_link_names_a_part_of_the_drawing() -> None:
    from pydantic import ValidationError

    from dashcraft.diagrams.model import Link

    assert Link(kind="area", target=" 1600, 0, 1600,900 ").target == "1600, 0, 1600,900"
    for bad in ("", "1600,0,1600", "a,b,c,d", "0,0,0,900", "-5,0,10,10"):
        with pytest.raises(ValidationError):
            Link(kind="area", target=bad)


def test_a_large_page_names_its_parts_as_tabs() -> None:
    from pydantic import ValidationError

    from dashcraft.diagrams.model import DiagramPayload

    made = DiagramPayload(
        name="Plant",
        width=3200,
        height=900,
        parts=[{"id": "a", "name": "Feed", "area": "0,0,1600,900"}],
    )
    assert made.stored()["parts"] == [{"id": "a", "name": "Feed", "area": "0,0,1600,900"}]
    for parts in (
        [{"id": "a", "name": "Feed", "area": "0,0,0,900"}],
        [{"id": "a", "name": "A", "area": "0,0,1,1"}, {"id": "a", "name": "B", "area": "0,0,1,1"}],
    ):
        with pytest.raises(ValidationError):
            DiagramPayload(name="Plant", parts=parts)


class _SlowPlant:
    """PlantCraft answering every read after ``delay`` seconds, counting reads in flight."""

    def __init__(self, delay: float = 0.02):
        self.delay, self.flying, self.most = delay, 0, 0
        self.lock = threading.Lock()

    def _wait(self) -> None:
        with self.lock:
            self.flying += 1
            self.most = max(self.most, self.flying)
        time.sleep(self.delay)
        with self.lock:
            self.flying -= 1

    def signal(self, signal_id):
        self._wait()
        return {"id": signal_id, "name": signal_id, "unit": "%"}

    def value(self, signal_id, agg, window):
        self._wait()
        return {"value": float(signal_id.rsplit("-", 1)[1]), "at": None}

    def results(self, subjects, kind):
        self._wait()
        return [{"status": "ok", "score": 90, "at": None}]

    def series_many(self, signals, start, end, step):
        return {"series": [], "errors": []}


def test_a_large_display_reads_its_bindings_side_by_side():
    count = 60
    elements = [
        {"type": "value", "id": f"v{n}", "item": {"signal_id": f"sim:TI-{n}"}} for n in range(count)
    ] + [
        {
            "type": "value",
            "id": "health",
            "item": {"signal_id": "sim:TI-0", "result": "linkcraft.loop_health"},
        }
    ]
    plant = _SlowPlant()
    started = time.monotonic()
    data = read_diagram(Reader(plant), {"elements": elements}, "1h")
    seconds = time.monotonic() - started
    values = [row["value"] for row in data["bindings"][:count]]
    assert values == [float(n) for n in range(count)]  # in drawing order
    assert data["bindings"][-1]["state"] == "ok"
    # 121 reads of 20 ms one after another take 2.4 s; side by side they take a fraction of it.
    assert plant.most > 1 and seconds < 1.2


class _BatchPlant(_SlowPlant):
    """Answers the newest points and the results of many subjects in one read each."""

    def __init__(self):
        super().__init__(delay=0)
        self.calls: list[str] = []

    def value(self, signal_id, agg, window):
        self.calls.append("value")
        return super().value(signal_id, agg, window)

    def asset(self, asset_id):
        return {"id": asset_id, "name": asset_id.upper()}

    def results(self, subjects, kind):
        self.calls.append("results")
        return [
            {"subject": subject, "status": "ok", "score": 90, "at": None} for subject in subjects
        ]

    def series_many(self, signals, start, end, step):
        self.calls.append(f"series step={step}")
        quiet = {"sim:TI-3"}  # nothing in the last two minutes: asked on its own
        return {
            "series": [
                {"signal": signal, "t": ["2026-10-30T20:00:00Z"], "v": [float(signal[7:]) + 0.5]}
                for signal in signals
                if signal not in quiet and step is None
            ],
            "errors": [],
        }


def test_a_display_reads_values_now_and_results_in_one_batch_each():
    elements = [
        {"type": "value", "id": f"v{n}", "item": {"signal_id": f"sim:TI-{n}"}} for n in range(6)
    ] + [
        {
            "type": "value",
            "id": f"h{n}",
            "item": {"asset_id": f"loop-{n}", "result": "linkcraft.loop_health"},
        }
        for n in range(4)
    ]
    plant = _BatchPlant()
    data = read_diagram(Reader(plant), {"elements": elements}, "1h")
    values = [row["value"] for row in data["bindings"][:6]]
    assert values == [0.5, 1.5, 2.5, 3.0, 4.5, 5.5]  # TI-3 from its own last value
    assert [row["state"] for row in data["bindings"][6:]] == ["ok"] * 4
    assert plant.calls.count("value") == 1 and plant.calls.count("results") == 1
    assert "series step=None" in plant.calls
