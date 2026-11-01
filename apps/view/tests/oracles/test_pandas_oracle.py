"""Oracle: what a card shows equals what pandas computes from the same samples.

A recorded file (gaps, irregular samples, a spike) is served by the fake as
PlantCraft serves a recorded file; every case reads it through a View
card and checks the number against pandas. The pass count is the
``[oracles] pandas_cases`` floor in ``tests/floors.toml``; a case is never
removed to raise it.
"""

from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dashcraft.dashboards.model import Card
from dashcraft.query.cards import Reader, read_card
from tests.plant import APP_KEY, NOW, make_fake

FLOORS = tomllib.loads((Path(__file__).parents[1] / "floors.toml").read_text(encoding="utf-8"))


def _recorded() -> pd.Series:
    rng = np.random.default_rng(7)
    index = pd.date_range(NOW - timedelta(hours=30), NOW, freq="10s", tz="UTC")
    values = 50 + 5 * np.sin(np.arange(len(index)) / 90) + rng.normal(0, 0.5, len(index))
    series = pd.Series(values, index=index)
    series.iloc[3000:3600] = np.nan  # a gap
    series.iloc[5000] = 400.0  # a spike
    keep = rng.random(len(series)) > 0.2  # irregular sampling
    return series[keep]


SAMPLES = _recorded()
CASES = [
    (agg, window)
    for window in ("15m", "1h", "8h", "24h")
    for agg in ("last", "mean", "min", "max", "std")
]


def _expected(agg: str, window: str) -> float:
    span = pd.Timedelta(window)
    end = SAMPLES.index.max()
    data = SAMPLES[(SAMPLES.index >= end - span) & (SAMPLES.index <= end)].dropna()
    return float(data.iloc[-1] if agg == "last" else getattr(data, agg)())


@pytest.fixture(scope="module")
def reader():
    fake = make_fake(series={"fake:FIC-101.PV": SAMPLES})
    return Reader(fake.client(None, app="dashcraft", key=APP_KEY), clock=lambda: fake.now)


def _card(agg: str, window: str) -> Card:
    items = [{"signal_id": "fake:FIC-101.PV"}]
    return Card(card_id="o", kind="kpi", items=items, agg=agg, window=window)


@pytest.mark.parametrize(("agg", "window"), CASES)
def test_kpi_values_match_pandas(reader, agg, window):
    value = read_card(reader, _card(agg, window))["rows"][0]["value"]
    assert value == pytest.approx(_expected(agg, window), rel=1e-9, abs=1e-9)


def test_trend_points_are_the_means_of_their_step(reader):
    card = Card(card_id="t", kind="trend", items=[{"signal_id": "fake:FIC-101.PV"}], window="8h")
    result = read_card(reader, card)
    line, step = result["lines"][0], result["range"]["step"]
    start = pd.Timestamp(result["range"]["start"])
    expected = SAMPLES[(SAMPLES.index >= start)].resample(f"{step}s", origin=start).mean()
    got = pd.Series(line["v"], index=pd.to_datetime(line["t"]), dtype=float)
    joined = pd.concat([got, expected], axis=1, join="inner").dropna()
    assert len(joined) > 400
    assert np.allclose(joined.iloc[:, 0], joined.iloc[:, 1])


def test_the_floor_counts_every_case():
    assert len(CASES) + 1 >= FLOORS["oracles"]["pandas_cases"]
