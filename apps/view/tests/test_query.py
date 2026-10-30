"""Cards read API v1 and turn every problem with one signal into words on that item."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from dashcraft.dashboards.model import CONTEXT, Card
from dashcraft.query.cache import TtlCache
from dashcraft.query.cards import Reader, read_card, read_trend, trend_step
from tests.plant import APP_KEY, NOW, make_fake, publish_loop_health


@pytest.fixture
def fake():
    return make_fake()


@pytest.fixture
def reader(fake):
    return Reader(fake.client(None, app="dashcraft", key=APP_KEY), clock=lambda: fake.now)


def card(kind="kpi", items=None, **fields):
    return Card.model_validate(
        {
            "card_id": "c",
            "kind": kind,
            "items": items or [{"signal_id": "fake:FIC-101.PV"}],
            **fields,
        }
    )


def test_a_kpi_reads_the_aggregation_over_its_window(reader):
    result = read_card(reader, card(agg="mean", window="1h"))
    row = result["rows"][0]
    assert row["label"] == "Feed flow" and row["unit"] == "m3/h" and row["error"] is None
    assert 45 < row["value"] < 55 and row["agg"] == "mean"


def test_asset_roles_and_the_dashboards_asset(reader):
    by_role = read_card(reader, card(items=[{"asset_id": "lic-102", "role": "pv"}]))
    assert by_role["rows"][0]["signal"] == "fake:LIC-102.PV"
    assert by_role["rows"][0]["label"] == "LIC-102 PV"
    on_context = card(items=[{"asset_id": CONTEXT, "role": "sp"}])
    assert read_card(reader, on_context, "fic-101")["rows"][0]["signal"] == "fake:FIC-101.SP"
    assert "Pick an asset" in read_card(reader, on_context)["rows"][0]["error"]


@pytest.mark.parametrize(
    ("item", "words"),
    [
        ({"asset_id": "nowhere", "role": "pv"}, "Asset nowhere not found."),
        ({"asset_id": "p-201", "role": "pv"}, "P-201 has no PV signal."),
        ({"signal_id": "NOPE"}, "Signal NOPE not found."),
        ({"asset_id": "fic-109", "role": "pv"}, "Signal fake:GONE.PV not found."),
    ],
)
def test_problems_with_one_item_become_its_error(reader, item, words):
    result = read_card(reader, card("bar", [{"signal_id": "fake:FIC-101.PV"}, item]))
    assert result["rows"][0]["error"] is None
    assert result["rows"][1]["error"] == words and result["rows"][1]["value"] is None


def test_a_dead_source_is_an_error_not_a_crash(fake, reader):
    fake.broken["fake:FIC-101.PV"] = "historian offline"
    for kind in ("kpi", "table", "trend"):
        result = read_card(reader, card(kind))
        rows = result.get("rows") or result.get("lines")
        assert "historian offline" in rows[0]["error"], kind


def test_text_signals_show_their_label(reader):
    result = read_card(reader, card(items=[{"asset_id": "p-201", "role": "state"}], agg="mean"))
    assert result["rows"][0]["value"] == "AUTO" and result["rows"][0]["agg"] == "last"
    assert result["rows"][0]["state"] == "none"
    table = read_card(reader, card("table", [{"signal_id": "fake:P-201.STATE"}]))
    assert table["rows"][0]["values"] == {"last": "AUTO"}
    trend = read_card(reader, card("trend", [{"signal_id": "fake:P-201.STATE"}]))
    assert "text signal" in trend["lines"][0]["error"]


def test_a_table_shows_last_mean_min_max_coloured_by_the_last(reader):
    result = read_card(reader, card("table", thresholds={"high_alarm": 10}, window="8h"))
    row = result["rows"][0]
    assert set(row["values"]) == {"last", "mean", "min", "max"}
    assert row["values"]["min"] <= row["values"]["mean"] <= row["values"]["max"]
    assert row["state"] == "alarm"


def test_a_trend_is_a_regular_grid_ending_now(reader):
    result = read_card(reader, card("trend", [{"signal_id": "fake:FIC-101.PV"}], window="8h"))
    line = result["lines"][0]
    assert result["range"]["step"] == 60 and result["range"]["shifted"] is False
    assert len(line["t"]) == 480 and len(line["v"]) == 480
    assert pd.Timestamp(result["range"]["end"]) == pd.Timestamp(NOW)


def test_the_window_override_wins(reader):
    result = read_card(reader, card("trend", window="8h"), window="1h")
    assert result["window"] == "1h" and result["range"]["step"] == 10


@pytest.mark.parametrize(
    ("seconds", "step"),
    [(60, 1), (3600, 10), (86400, 300), (7 * 86400, 1800), (366 * 86400, 86400)],
)
def test_trend_steps(seconds, step):
    assert trend_step(seconds) == step
    assert seconds / trend_step(seconds) <= 600


def test_a_recorded_file_moves_the_trend_to_its_last_sample():
    index = pd.date_range(NOW - timedelta(days=3, hours=2), NOW - timedelta(days=3), freq="10s")
    fake = make_fake(series={"fake:FIC-101.PV": pd.Series(50.0, index=index)}, recorded=False)
    reader = Reader(fake.client(None, app="dashcraft", key=APP_KEY), clock=lambda: fake.now)
    result = read_card(reader, card("trend", window="1h"))
    assert result["range"]["shifted"] is True
    assert pd.Timestamp(result["range"]["end"]) == index[-1]
    assert any(v == 50.0 for v in result["lines"][0]["v"])


def test_one_read_serves_every_viewer_while_cached(fake):
    reader = Reader(
        fake.client(None, app="dashcraft", key=APP_KEY),
        data_cache=TtlCache(10),
        meta_cache=TtlCache(60),
        clock=lambda: fake.now,
    )
    trend = card("trend", [{"signal_id": "fake:FIC-101.PV"}, {"signal_id": "fake:FIC-101.SP"}])
    read_card(reader, trend)
    read_card(reader, kpi_card := card())
    before = fake.requests
    for _ in range(20):
        read_card(reader, trend)
        read_card(reader, kpi_card)
    assert fake.requests == before


def test_the_cache_lets_expired_values_go_as_soon_as_another_is_stored():
    """A playback window per request kept thousands of megabyte series after their seconds: the
    View container reached its memory limit and the kernel stopped it (public demo, 2026-10-29)."""

    now = [0.0]
    cache = TtlCache(10, clock=lambda: now[0])
    for end in range(50):
        cache.get(("series", end), lambda: b"x" * 1000)
    assert len(cache) == 50
    now[0] = 11.0
    cache.get(("series", "new"), lambda: b"x")
    assert len(cache) == 1
    assert cache.get(("series", "new"), lambda: b"other") == b"x"


def test_viewers_asking_together_share_one_read():
    import threading

    cache, reads, started = TtlCache(10), [], threading.Event()

    def load():
        reads.append(1)
        started.set()
        threading.Event().wait(0.2)
        return "rows"

    first = threading.Thread(target=cache.get, args=("key", load))
    first.start()
    started.wait(2)
    others = [threading.Thread(target=cache.get, args=("key", load)) for _ in range(10)]
    for thread in [*others]:
        thread.start()
    for thread in [first, *others]:
        thread.join(5)
    assert len(reads) == 1 and cache.misses == 1


def test_app_results_show_the_producers_status_and_score(fake, reader):
    publish_loop_health(fake)
    health = {"asset_id": CONTEXT, "result": "linkcraft.loop_health"}
    row = read_card(reader, card(items=[health]), context="fic-101")["rows"][0]
    assert (row["value"], row["state"], row["unit"]) == (62.5, "warning", "/100")
    assert row["summary"] == "Oscillating, period 4 min" and row["error"] is None
    # An expired result is unknown, whatever it said: no green light left behind.
    stale = read_card(reader, card(items=[health]), context="lic-102")["rows"][0]
    assert stale["state"] == "unknown" and stale["stale"]
    # Limits never recolour another app's verdict.
    limited = card(items=[health], thresholds={"low_alarm": 90})
    assert read_card(reader, limited, context="fic-101")["rows"][0]["state"] == "warning"


def test_app_results_in_tables_and_bars_and_their_problems(fake, reader):
    publish_loop_health(fake)
    items = [
        {"asset_id": "fic-101", "result": "linkcraft.loop_health"},
        {"asset_id": "p-201", "result": "linkcraft.loop_health"},
        {"asset_id": "nope", "result": "linkcraft.loop_health"},
    ]
    rows = read_card(reader, card("table", items))["rows"]
    assert rows[0]["values"] == {"last": 62.5} and rows[0]["label"] == "FIC-101 loop health"
    assert "linkcraft has published no loop_health" in rows[1]["error"]
    assert "not found" in rows[2]["error"]
    bars = read_card(reader, card("bar", items))["rows"]
    assert [row["state"] for row in bars] == ["warning", "unknown", "unknown"]


@pytest.mark.parametrize(
    "item",
    [
        {"result": "linkcraft.loop_health"},
        {"asset_id": "fic-101", "role": "pv", "result": "linkcraft.loop_health"},
        {"asset_id": "fic-101", "signal_id": "fake:FIC-101.PV", "result": "linkcraft.loop_health"},
        {"asset_id": "fic-101", "result": "loop_health"},
        {"asset_id": "fic-101", "result": "CPM.health"},
    ],
)
def test_bad_result_items_are_refused(item):
    with pytest.raises(ValueError):
        card(items=[item])


def test_a_trend_draws_the_history_an_app_archives(reader):
    """LinkCraft archives FIC-101's loop health in HistCraft (a derived signal): a trend draws it
    from the number series, never the text (status) one, and says when there is none."""

    items = [
        {"asset_id": CONTEXT, "result": "linkcraft.loop_health"},
        {"asset_id": "lic-102", "result": "linkcraft.loop_health"},
        {"signal_id": "fake:FIC-101.PV", "result": "linkcraft.loop_health"},
    ]
    lines, _ = read_trend(reader, card("trend", items, window="8h"), "fic-101", "8h")
    health = lines[0]
    assert health["signal"] == "app-linkcraft:FIC-101.health" and health["unit"] == "/100"
    assert health["label"] == "loop health" and health["error"] is None
    assert len(health["v"]) > 10 and all(v is not None for v in health["v"])
    assert lines[1]["error"] == "linkcraft keeps no history of loop health here yet."
    assert lines[1]["label"] == "LIC-102 loop health"
    assert lines[2]["error"] and not lines[2]["v"]
    no_asset = read_trend(reader, card("trend", items[:1]), None, "1h")[0][0]
    assert no_asset["error"] == "Pick an asset at the top of the dashboard."


def test_a_setpoint_recorded_on_change_reaches_the_end_of_its_trend():
    """API v1's grid holds the last value in steps without samples (plantcraft-sdk 0.7.1), so
    a setpoint written only when it changes still draws up to now (gap G16, closed)."""

    changes = pd.Series([55.0, 58.0], index=[NOW - timedelta(hours=7), NOW - timedelta(minutes=20)])
    fake = make_fake(series={"fake:FIC-101.SP": changes}, recorded=False)
    reader = Reader(fake.client(None, app="dashcraft", key=APP_KEY), clock=lambda: fake.now)
    line = read_card(reader, card("trend", [{"signal_id": "fake:FIC-101.SP"}], window="1h"))[
        "lines"
    ][0]
    assert line["error"] is None and line["v"][-1] == 58.0


def test_a_sparkline_reads_its_value_and_its_line(reader):
    result = read_card(reader, card("spark", agg="last", window="1h"))
    assert result["rows"][0]["value"] is not None and result["rows"][0]["agg"] == "last"
    assert len(result["lines"]) == 1 and result["lines"][0]["t"]


def test_a_scatter_reads_both_signals_on_one_grid(reader):
    items = [{"signal_id": "fake:FIC-101.OP"}, {"signal_id": "fake:FIC-101.PV"}]
    result = read_card(reader, card("scatter", items=items, window="1h"))
    x, y = result["lines"]
    assert x["t"] and x["t"] == y["t"]


def test_a_text_card_reads_nothing(reader):
    note = Card.model_validate({"card_id": "c", "kind": "text", "items": [], "text": "Who to call"})
    result = read_card(reader, note)
    assert "rows" not in result and "lines" not in result


def test_every_signal_of_an_asset_comes_in_one_item(reader):
    """Round 7 (D5): role ``*`` reads all the asset's signals, PV, SP, OP first."""

    result = read_card(reader, card("table", [{"asset_id": "fic-101", "role": "*"}]))
    assert [row["role"] for row in result["rows"]] == ["pv", "sp", "op", "mode"]
    assert result["rows"][0]["label"] == "FIC-101 PV"
    only = read_card(
        reader, card("trend", [{"asset_id": "fic-101", "role": "*", "roles": ["sp", "pv"]}])
    )
    assert [line["role"] for line in only["lines"]] == ["sp", "pv"]
    missing = read_card(reader, card("kpi", [{"asset_id": "nope", "role": "*"}]))
    assert "not found" in missing["rows"][0]["error"]


def test_variables_fill_the_items(reader):
    loop = card("trend", [{"asset_id": "$loop", "role": "pv"}])
    one = read_card(reader, loop, values={"loop": ["lic-102"]})
    # One asset picked: the label leaves the asset out, as the dashboard's asset did.
    assert [line["label"] for line in one["lines"]] == ["PV"]
    both = read_card(reader, loop, values={"loop": ["fic-101", "lic-102"]})
    assert [line["signal"] for line in both["lines"]] == ["fake:FIC-101.PV", "fake:LIC-102.PV"]
    assert both["lines"][1]["label"] == "LIC-102 PV"
    none = read_card(reader, loop, values={}, labels={"loop": "Loop"})
    assert none["lines"][0]["error"] == "Pick Loop at the top of the dashboard."
    by_tag = card("kpi", [{"signal_id": "fake:${tag}.SP", "label": "${tag} set point"}])
    rows = read_card(reader, by_tag, values={"tag": ["FIC-101", "LIC-102"]})["rows"]
    assert [row["signal"] for row in rows] == ["fake:FIC-101.SP", "fake:LIC-102.SP"]
    assert [row["label"] for row in rows] == ["FIC-101 set point", "LIC-102 set point"]
    period = card("trend", window="$period")
    assert read_card(reader, period, values={"period": ["8h"]})["window"] == "8h"


def test_thresholds_and_overrides_colour_each_row(reader):
    steps = {"steps": [{}, {"value": 0, "level": "alarm"}]}
    found = read_card(
        reader,
        card(
            "table",
            [{"asset_id": "fic-101", "role": "pv"}, {"asset_id": "fic-101", "role": "sp"}],
            overrides=[{"match": {"by": "role", "value": "sp"}, "field": {"thresholds": steps}}],
        ),
    )
    assert [row["state"] for row in found["rows"]] == ["none", "alarm"]
