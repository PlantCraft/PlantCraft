"""Calculated points and totalizers: formulas checked, inputs validated, evaluated by the collector."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

import pytest

from histcraft.archive.store import ArchiveStore
from histcraft.catalog.expressions import FormulaError, parse
from histcraft.catalog.models import CatalogError, PointIn, PointPatch, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.calc import CalcReader, Total, accumulate, period_start
from histcraft.collector.service import Collector
from tests.conftest import database, make_settings


def ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_a_formula_reads_points_and_evaluates_safely():
    formula = parse("= [plant:FI-100.PV] * 3.6 + max([plant:A], 2)")
    assert formula.signals == ["plant:FI-100.PV", "plant:A"]
    assert formula.evaluate([1.0, 5.0]) == pytest.approx(8.6)
    assert parse("if([plant:A] > 2, 1, 0) + ([plant:B] == 3)").evaluate([3.0, 3.0]) == 2.0
    # The same point twice is one input.
    assert parse("[plant:A] - [plant:A]").signals == ["plant:A"]
    assert math.isnan(parse("[plant:A] / 0").evaluate([1.0]))
    assert math.isnan(parse("sqrt([plant:A])").evaluate([-1.0]))
    assert math.isnan(parse("[plant:A] ** 1000").evaluate([1e10]))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "3 + 4",
        "[plant:A] + __import__('os')",
        "[plant:A].real",
        "open([plant:A])",
        "[plant:A] + 'x'",
        "[plant:A] + x",
        "[plant:A] if [plant:B] else 0",
        "lambda: [plant:A]",
        "[plant:A] + [Plant:B]",
        "1 + total([plant:A])",
        'total([plant:A], per="week")',
        "max([plant:A])",
    ],
)
def test_anything_but_a_formula_is_refused(text):
    with pytest.raises(FormulaError):
        parse(text)


def test_a_totalizer_is_the_whole_formula():
    formula = parse('total([plant:FI-100.PV], per="h", reset="day")')
    assert formula.total and formula.per_seconds == 3600 and formula.reset == "day"
    assert not parse("[plant:A]").total


def test_a_totalizer_integrates_and_restarts_each_period():
    formula = parse('total([plant:F], per="h", reset="day")')
    start = ms("2026-10-23T23:00:00")
    total = Total(period_start(start, "day"), 0.0)
    # 100 m³/h for one hour: 100 m³.
    accumulate(total, formula, start, 100.0)
    assert accumulate(total, formula, start + 3_600_000 - 1, 100.0) == pytest.approx(100.0, 1e-3)
    # Past midnight the total restarts, counting only the part after midnight.
    after = accumulate(total, formula, start + 3_600_000 + 360_000, 100.0)
    assert after == pytest.approx(10.0, 1e-3)
    assert period_start(ms("2026-10-23T12:34:56"), "month") == ms("2026-10-01T00:00:00")
    assert period_start(ms("2026-10-23T12:34:56"), "hour") == ms("2026-10-23T12:00:00")
    assert period_start(ms("2026-10-23T12:34:56"), "none") == 0


@pytest.fixture
def catalog(tmp_path):
    store = CatalogStore(database(tmp_path, "config"))
    store.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://plant:4840"), create=True
    )
    store.add_points(
        [
            PointIn(tag="F", source_id="plant", address="ns=2;s=F"),
            PointIn(tag="T", source_id="plant", address="ns=2;s=T"),
            PointIn(tag="MODE", source_id="plant", address="ns=2;s=MODE", kind="text"),
            PointIn(tag="ONDEMAND", source_id="plant", address="ns=2;s=O", mode="source"),
        ]
    )
    return store


def add(catalog, tag, formula, **fields):
    return catalog.add_points([PointIn(tag=tag, source_id="calc", address=formula, **fields)])


def test_a_calculated_point_needs_archived_number_inputs(catalog):
    assert add(catalog, "F-NM3", "[plant:F] * 3.6")["added"] == ["calc:F-NM3"]
    source = next(item for item in catalog.sources() if item["id"] == "calc")
    assert source["kind"] == "calc" and source["default_mode"] == "archive"
    assert catalog.point("calc:F-NM3")["quality_reported"]
    reasons = {
        tag: add(catalog, tag, formula)["skipped"][0]["reason"]
        for tag, formula in {
            "A": "[plant:NOPE] + 1",
            "B": "[plant:MODE] + 1",
            "C": "[plant:ONDEMAND] + 1",
            "D": "[calc:D] + 1",
            "E": "[plant:F] +",
        }.items()
    }
    assert "not a signal" in reasons["A"]
    assert "is text" in reasons["B"]
    assert "not archived here" in reasons["C"]
    assert "its own signal" in reasons["D"]
    assert "not valid" in reasons["E"]
    skipped = add(catalog, "G", "[plant:F]", mode="source")["skipped"]
    assert "only in the archive" in skipped[0]["reason"]


def test_a_formula_can_change_but_never_loop(catalog):
    add(catalog, "A", "[plant:F] * 2")
    add(catalog, "B", "[calc:A] + [plant:T]")
    changed = catalog.update_point("calc:A", PointPatch(address="[plant:F] * 3"))
    assert changed["address"] == "[plant:F] * 3"
    with pytest.raises(CatalogError, match="reads itself"):
        catalog.update_point("calc:A", PointPatch(address="[calc:B] * 3"))
    with pytest.raises(CatalogError, match="Only a calculated signal"):
        catalog.update_point("plant:F", PointPatch(address="ns=2;s=G"))
    with pytest.raises(CatalogError, match="only in the archive"):
        catalog.update_point("calc:A", PointPatch(mode="both"))


def test_the_collector_evaluates_with_the_worst_quality_of_the_inputs(tmp_path, catalog):
    add(catalog, "SUM", "[plant:F] + [plant:T]")
    add(catalog, "TOTAL", 'total([plant:F], per="s")')
    collector = Collector(make_settings(tmp_path), catalog, ArchiveStore(database(tmp_path)))
    collector.reload()
    reader = CalcReader(collector)
    states = {state.point["signal"]: state for state in collector.points.values()}

    def read():
        return asyncio.run(reader.read(["[plant:F] + [plant:T]", 'total([plant:F], per="s")']))

    # Nothing read yet: no value, a gap.
    assert not read()["[plant:F] + [plant:T]"].good
    states["plant:F"].status, states["plant:F"].last = "ok", (0, 2.0)
    states["plant:T"].status, states["plant:T"].last = "ok", (0, 3.0)
    reading = read()["[plant:F] + [plant:T]"]
    assert (reading.good, reading.value, reading.quality) == (True, 5.0, "good")
    states["plant:T"].status = "uncertain"
    assert read()["[plant:F] + [plant:T]"].quality == "uncertain"
    states["plant:T"].status = "disconnected"
    gap = read()["[plant:F] + [plant:T]"]
    assert not gap.good and "plant:T" in gap.detail
    # The totalizer runs on F alone: 2 per second.
    first = read()['total([plant:F], per="s")']
    total = collector.totals['total([plant:F], per="s")']
    total.last = (total.last[0] - 10_000, 2.0)
    later = read()['total([plant:F], per="s")']
    assert later.value - first.value == pytest.approx(20.0, abs=0.1)
