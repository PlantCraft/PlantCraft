"""Days until a falling indicator reaches its limit (A18): engine.days_to_limit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from linkcraft.engine.days_to_limit import days_to_limit

START = datetime(2026, 10, 17, tzinfo=UTC)


def _line(values):
    return [(START + timedelta(days=day), value) for day, value in enumerate(values)]


def test_a_steady_fall_gives_the_days_left():
    # 2 points a day down from 90: 64 on day 13, so 14 days to 50... after the last point 7.
    found = days_to_limit(_line([90 - 2 * day for day in range(14)]), 50)
    assert found["slope_per_day"] == -2.0 and found["r2"] == 1.0
    assert found["now"] == 64.0 and found["days"] == 7.0
    # Already below the limit: now.
    assert days_to_limit(_line([60 - 2 * day for day in range(10)]), 50)["days"] == 0.0


def test_no_forecast_when_flat_rising_noisy_or_short():
    assert days_to_limit(_line([80] * 14), 50) is None
    assert days_to_limit(_line([60 + day for day in range(14)]), 50) is None
    assert days_to_limit(_line([80, 40, 85, 45, 82, 41, 84, 43, 80, 44]), 50) is None
    assert days_to_limit(_line([90, 80, 70]), 50) is None
    # Falling so slowly that the limit is more than a year away.
    assert days_to_limit(_line([90 - 0.01 * day for day in range(14)]), 50) is None
    # A rising indicator toward an upper limit.
    assert days_to_limit(_line([10 + day for day in range(10)]), 30, falling=False)["days"] == 11.0


def test_the_api_and_the_widget(client, analysed):
    answer = client.get("/link/api/loop-days-to-limit?until=2026-10-02T00:00:00Z")
    assert answer.status_code == 200 and isinstance(answer.json(), list)
    widget = client.get("/link/api/widgets/closest-to-limit").json()
    assert widget["kind"] == "list"
