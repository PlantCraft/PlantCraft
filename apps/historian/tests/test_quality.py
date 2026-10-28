"""Quality kept with values (G5): uncertain values archived and marked, changes kept, pruned."""

from __future__ import annotations

import math

from histcraft.archive.compression import Compressor
from histcraft.collector.reading import Reading
from histcraft.collector.service import PointState
from tests.test_archive import make

POINT = {"id": 1, "kind": "number", "deviation": 1.0, "max_seconds": 3600, "step": False}


def state() -> PointState:
    return PointState(dict(POINT), Compressor(deviation=1.0, max_seconds=3600))


def test_an_uncertain_value_is_archived_where_the_quality_changes():
    point = state()
    for i in range(5):
        point.take(Reading(i * 1000, 10.0, True))
    point.take(Reading(5000, 10.2, True, "UncertainLastUsableValue", "uncertain"))
    point.take(Reading(6000, 10.3, True, "UncertainLastUsableValue", "uncertain"))
    point.take(Reading(7000, 10.3, True))
    assert point.status == "ok"
    times = [at for at, _ in point.pending]
    # The value where it turned uncertain and where it came back are archived as read.
    assert 5000 in times and 7000 in times
    assert point.changes == [(5000, "uncertain"), (7000, "good")]


def test_a_bad_value_is_a_gap_marked_bad_once():
    point = state()
    point.take(Reading(0, 1.0, True))
    point.take(Reading(1000, None, False, "BadSensorFailure", "bad"))
    point.take(Reading(2000, None, False, "BadSensorFailure", "bad"))
    assert point.status == "bad"
    assert point.changes == [(1000, "bad")]
    assert math.isnan(point.pending[-1][1])


def test_a_source_without_quality_never_writes_a_change():
    point = state()
    for i in range(10):
        point.take(Reading(i * 1000, float(i), True))
    assert point.changes == []


def test_the_archive_answers_the_quality_in_effect_and_prunes_old_changes(tmp_path):
    archive = make(tmp_path)
    archive.put_qualities([(1, 1000, "uncertain"), (1, 5000, "good"), (1, 9000, "bad")])
    assert archive.qualities(1, 2000, 10_000) == [
        (1000, "uncertain"),
        (5000, "good"),
        (9000, "bad"),
    ]
    assert archive.qualities(1, 6000, 8000) == []
    archive.prune({1: 6000})
    # The change in effect at the cutoff stays: 5000 (good) is still known.
    assert archive.qualities(1, 0, 10_000) == [(5000, "good"), (9000, "bad")]
    archive.delete_points([1])
    assert archive.qualities(1, 0, 10_000) == []


def test_opc_ua_status_classes_become_qualities():
    from asyncua import ua

    from histcraft.collector.opcua import OpcUaReader

    reader = OpcUaReader({"endpoint": "opc.tcp://x"})

    def read(code: int, value: float = 5.0) -> Reading:
        data = ua.DataValue(
            ua.Variant(value, ua.VariantType.Double), StatusCode_=ua.StatusCode(code)
        )
        return reader._reading("ns=2;s=X", data, 1000)

    good = read(ua.StatusCodes.Good)
    uncertain = read(ua.StatusCodes.UncertainLastUsableValue)
    bad = read(ua.StatusCodes.BadSensorFailure)
    assert (good.good, good.quality) == (True, "good")
    assert (uncertain.good, uncertain.quality, uncertain.value) == (True, "uncertain", 5.0)
    assert (bad.good, bad.quality, bad.value) == (False, "bad", None)
