import math

from plantcraft_sdk import apptest, widgets
from plantcraft_sdk.contributes import contributions

MANIFEST = {
    "app": {"id": "demo", "version": "1.0.0"},
    "contributes": {
        "widgets": [
            {"id": "count", "title": "Count", "size": "s", "kind": "number", "default": True},
            {
                "id": "one",
                "title": "One thing",
                "kind": "facts",
                "pick": "Thing",
                "sizes": [{"w": 4, "h": 2}, {"w": 6, "h": 3}],
            },
        ]
    },
}


def test_the_catalog_is_the_declared_widgets_in_the_persons_language():
    body = widgets.catalog(MANIFEST, lambda text: text.upper())
    assert body["version"] == widgets.WIDGETS_VERSION
    first, second = body["widgets"]
    assert first == {
        "id": "count",
        "title": "COUNT",
        "description": "",
        "size": "s",
        "kind": "number",
        "default": True,
    }
    assert second["pick"] == "THING" and second["multiple"] is True
    assert second["sizes"] == [{"w": 4, "h": 2}, {"w": 6, "h": 3}]
    assert widgets.ids(MANIFEST) == {"count", "one"}
    # The same tables are what PlantCraft's registry keeps.
    sent = contributions(MANIFEST)["contributes"]["widgets"]
    assert [item["kind"] for item in sent] == ["number", "facts"]


def test_the_shapes_drop_empty_fields_and_never_send_nan():
    assert widgets.number(None) == {"kind": "number", "value": None}
    assert widgets.number(math.nan, label="x")["value"] is None
    assert widgets.fact("Mean", math.inf) == {"label": "Mean", "value": None}
    listed = widgets.items([widgets.item("A", value=1)] * 30, href="/demo/a")
    assert len(listed["items"]) == widgets.MAX_ITEMS and "empty" not in listed
    parts = widgets.split([widgets.part("OK", 3, "ok"), widgets.part("Alarm", 1, "alarm")])
    assert parts["parts"][1] == {"label": "Alarm", "value": 1, "state": "alarm"}
    card = widgets.facts("Run", [widgets.fact("Assets", 4)], state="ok", status="Done")
    assert card["title"] == "Run" and card["status"] == "Done"
    assert widgets.options([widgets.option("a", "A")]) == {
        "options": [{"value": "a", "label": "A"}]
    }


def test_a_long_series_is_thinned_and_keeps_its_gaps_and_last_point():
    points = [(index * 1000, float(index)) for index in range(2000)] + [(2_000_000, None)]
    body = widgets.series(points, value=1.5, unit="bar")
    assert len(body["points"]) == widgets.MAX_POINTS
    assert body["points"][-1] == [2_000_000.0, None]
    assert widgets.series([(0, math.nan), (1, 2)])["points"][0] == [0.0, None]


def test_bars_columns_and_tiles_keep_their_limits():
    ranked = widgets.bars(
        [widgets.bar(f"Tag {n}", n, state="alarm") for n in range(15)] + [], target=6
    )
    assert ranked["kind"] == "bars" and len(ranked["bars"]) == widgets.MAX_BARS
    assert widgets.bar("Bad", math.nan) == {"label": "Bad", "value": None}
    counts = widgets.columns(
        [(n * 3_600_000, [n, None, math.nan]) for n in range(300)] + [(1.0, 5)],
        stacks=[widgets.stack("High", "alarm"), widgets.stack("Low")],
        step="hour",
        target=6,
    )
    assert len(counts["buckets"]) == widgets.MAX_BUCKETS
    assert counts["buckets"][-1] == [1.0, [5.0]]
    assert counts["buckets"][-2][1] == [299.0, None, None]
    assert counts["stacks"][1] == {"label": "Low"} and counts["step"] == "hour"
    assert "stacks" not in widgets.columns([(0, 1)])
    many = widgets.tiles(
        [
            widgets.group("A", [widgets.tile(f"L{n}", "ok") for n in range(1000)]),
            widgets.group("B", [widgets.tile(f"M{n}", "alarm") for n in range(800)]),
            widgets.group("C", [widgets.tile("X")]),
        ],
        label="loops",
    )
    assert [len(entry["tiles"]) for entry in many["groups"]] == [1000, 500]
    assert many["more"] == 301
    assert "more" not in widgets.tiles([widgets.group(None, [widgets.tile("x", "ok")])])


def test_served_widgets_must_be_declared_and_a_pick_needs_its_options(tmp_path):
    root = tmp_path / "demo"
    (root / "src" / "demo").mkdir(parents=True)
    (root / "app.toml").write_text("[app]\nid = 'demo'\n", encoding="utf-8")
    routes = [("GET", "/api/widgets"), ("GET", "/api/widgets/{widget_id}")]
    assert apptest.contribution_problems(root, "demo", routes) == [
        "widgets are served but none is declared in [[contributes.widgets]]"
    ]
    (root / "app.toml").write_text(
        "[app]\nid = 'demo'\n[[contributes.widgets]]\nid = 'one'\ntitle = 'One'\npick = 'Thing'\n",
        encoding="utf-8",
    )
    assert apptest.contribution_problems(root, "demo", routes) == [
        "widget 'one' has a pick but no route serves its options"
    ]
    routes.append(("GET", "/api/widgets/{widget_id}/options"))
    assert apptest.contribution_problems(root, "demo", routes) == []


def test_ago_says_how_long_ago_or_how_soon():
    from datetime import UTC, datetime

    def t(text, **values):
        return text.format(**values)

    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    assert widgets.ago("2026-10-25T11:55:00Z", t, now) == "5 min ago"
    assert widgets.ago("2026-10-25T14:30:00+00:00", t, now) == "in 2 h"
    assert widgets.ago(datetime(2026, 10, 22, 12, 0, tzinfo=UTC), t, now) == "3 d ago"
    assert widgets.ago("2026-10-25T12:00:20Z", t, now) == "just now"
    assert widgets.ago(None, t, now) is None
    assert widgets.ago("not a time", t, now) is None


def test_widget_problems_call_every_widget_in_its_declared_shape():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    api = FastAPI()

    @api.get("/demo/api/widgets")
    def listed():
        return widgets.catalog(MANIFEST)

    @api.get("/demo/api/widgets/{widget_id}/options")
    def choices(widget_id: str):
        return widgets.options([widgets.option("a", "A")])

    @api.get("/demo/api/widgets/{widget_id}")
    def data(widget_id: str, item: str | None = None):
        if widget_id == "count":
            return widgets.number(1, href="https://elsewhere.example/")
        if widget_id == "one":
            return widgets.items([]) if item == "a" else widgets.facts("A", [])
        raise HTTPException(404)

    problems = apptest.widget_problems(TestClient(api), "/demo")
    assert problems == [
        "widget 'count': link 'https://elsewhere.example/' is not on this host",
        "/demo/api/widgets/one?item=a: kind 'list', declared 'facts'",
    ]


def test_widget_problems_fail_a_list_row_whose_value_is_only_a_time():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    api = FastAPI()
    manifest = {"contributes": {"widgets": [{"id": "runs", "title": "Runs", "kind": "list"}]}}

    @api.get("/demo/api/widgets")
    def listed():
        return widgets.catalog(manifest)

    @api.get("/demo/api/widgets/{widget_id}")
    def data(widget_id: str):
        if widget_id != "runs":
            from fastapi import HTTPException

            raise HTTPException(404)
        return widgets.items(
            [
                widgets.item("A", value="5 h ago"),
                widgets.item("B", detail="Started 5 h ago", value="Health 30 %"),
            ]
        )

    problems = apptest.widget_problems(TestClient(api), "/demo")
    assert len(problems) == 1 and problems[0].startswith("widget 'runs': '5 h ago' alone")
