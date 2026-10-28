"""Every number point has a range: the server's, a person's, or one suggested (round 8 D2)."""

from __future__ import annotations

import math

import numpy as np

from histcraft.api.routers.data import signal_shape
from histcraft.archive.store import ArchiveStore, now_ms
from histcraft.catalog import ranges
from histcraft.catalog.models import PointIn, PointPatch, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.service import Collector
from histcraft.db import Database
from tests.conftest import make_settings

HOUR_MS = 3_600_000


def test_suggest_pads_the_first_day_and_rounds_outward():
    assert ranges.suggest([20.0, 80.0]) == (14.0, 86.0)
    # A value never below 0 keeps a range from 0.
    assert ranges.suggest([0.5, 10.0]) == (0.0, 11.0)
    assert ranges.suggest([-5.0, 5.0]) == (-6.0, 6.0)
    # A flat first day still gets a width.
    low, high = ranges.suggest([50.0, 50.0])
    assert low < 50.0 < high
    assert ranges.suggest([0.0]) == (0.0, 0.5)
    assert ranges.suggest([math.nan]) is None
    assert ranges.suggest([]) is None
    # No float noise from the rounding.
    assert ranges.suggest([0.1, 0.3]) == (0.08, 0.32)


def _stores(tmp_path):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    archive = ArchiveStore(Database(settings.archive_target))
    catalog.save_source(
        SourceIn(id="plant", name="plant", endpoint="opc.tcp://127.0.0.1:4999"), create=True
    )
    return settings, catalog, archive


def test_where_a_range_comes_from(tmp_path):
    _, catalog, _ = _stores(tmp_path)
    catalog.add_points(
        [
            PointIn(tag="SRV", source_id="plant", low=0, high=100),
            PointIn(tag="NONE", source_id="plant"),
        ]
    )
    assert catalog.point("plant:SRV")["range_origin"] == "source"
    assert catalog.point("plant:NONE")["range_origin"] == ""
    edited = catalog.update_point("plant:NONE", PointPatch(low=0, high=50))
    assert edited["range_origin"] == "edited"
    assert edited["deviation"] == 0.1  # 0.2 % of the range a person gave
    cleared = catalog.update_point("plant:NONE", PointPatch(low=None, high=None))
    assert cleared["range_origin"] == ""


def test_housekeeping_suggests_a_range_after_a_day_and_a_person_confirms_it(tmp_path):
    settings, catalog, archive = _stores(tmp_path)
    catalog.add_points(
        [
            PointIn(tag="NEW", source_id="plant"),
            PointIn(tag="OLD", source_id="plant"),
            PointIn(tag="SRV", source_id="plant", low=0, high=1000),
            PointIn(tag="SP", source_id="plant", step=True),
        ]
    )
    ids = {tag: catalog.point(f"plant:{tag}")["id"] for tag in ("NEW", "OLD", "SRV", "SP")}
    now = now_ms()
    day = [(now - 30 * HOUR_MS + hour * HOUR_MS, 20.0 + hour) for hour in range(30)]
    archive.append(
        {
            ids["NEW"]: ("number", [(now - HOUR_MS, 5.0), (now, 6.0)]),
            ids["OLD"]: ("number", day),
            ids["SRV"]: ("number", day),
            ids["SP"]: ("number", day),
        }
    )
    done = Collector(settings, catalog, archive).housekeeping(force=True)
    assert done["suggested_ranges"] == 1
    old = catalog.point("plant:OLD")
    # The first day only (20 to 44), not the hours after it.
    assert (old["low"], old["high"], old["range_origin"]) == (17.0, 47.0, "suggested")
    assert old["deviation"] == np.float64(0.06)  # the compression follows the suggestion
    assert catalog.point("plant:NEW")["range_origin"] == ""
    assert catalog.point("plant:SRV")["high"] == 1000
    assert catalog.point("plant:SP")["range_origin"] == ""
    # Other apps judge data by low and high: an unconfirmed suggestion is not given to them.
    assert (signal_shape(old)["low"], signal_shape(old)["high"]) == (None, None)
    assert signal_shape(catalog.point("plant:SRV"))["high"] == 1000
    # Saving the suggestion as it is confirms it; it is never suggested over again.
    confirmed = catalog.update_point("plant:OLD", PointPatch(low=old["low"], high=old["high"]))
    assert confirmed["range_origin"] == "edited"
    assert catalog.suggest_ranges({ids["OLD"]: (0.0, 1.0)}) == 0
