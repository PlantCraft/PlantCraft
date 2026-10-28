"""A schedule's calendar (``linkcraft.engine.recurrence``): every N minutes on weekdays between two
times, several times a day, chosen weekdays, a day or a weekday of the month, a first and a last
day, in the schedule's time zone across daylight saving changes."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from linkcraft.engine.recurrence import Recurrence, describe, next_after

SAO_PAULO = "America/Sao_Paulo"  # UTC-3, no daylight saving
BERLIN = "Europe/Berlin"


def runs(rule: Recurrence, zone: str, after: datetime, count: int = 5) -> list[str]:
    found = []
    moment = after
    for _ in range(count):
        following = next_after(rule, zone, moment)
        if following is None:
            break
        found.append(following.isoformat())
        moment = following
    return found


def test_every_15_minutes_on_weekdays_between_two_times():
    rule = Recurrence(
        freq="minutes", every=15, weekdays=[0, 1, 2, 3, 4], between=("06:00", "18:00")
    )
    # Friday 2026-10-23 17:40 local (20:40 UTC): 17:45, 18:00, then Monday 06:00.
    after = datetime(2026, 10, 23, 20, 40, tzinfo=UTC)
    assert runs(rule, SAO_PAULO, after, 4) == [
        "2026-10-23T20:45:00+00:00",
        "2026-10-23T21:00:00+00:00",
        "2026-10-26T09:00:00+00:00",
        "2026-10-26T09:15:00+00:00",
    ]
    assert describe(rule) == "Every 15 minutes, Mon to Fri, 06:00 to 18:00"


def test_every_day_at_two_times_and_every_2_days():
    rule = Recurrence(freq="days", times=["18:00", "06:00"])
    after = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)  # 09:00 local
    assert runs(rule, SAO_PAULO, after, 3) == [
        "2026-10-25T21:00:00+00:00",
        "2026-10-26T09:00:00+00:00",
        "2026-10-26T21:00:00+00:00",
    ]
    assert describe(rule) == "Every day at 06:00 and 18:00"
    other = Recurrence(freq="days", every=2, times=["06:00"], start=date(2026, 10, 25))
    assert runs(other, SAO_PAULO, after, 2) == [
        "2026-10-27T09:00:00+00:00",
        "2026-10-29T09:00:00+00:00",
    ]


def test_weekly_on_chosen_days_and_every_2_weeks():
    rule = Recurrence(freq="weeks", weekdays=[0, 2], times=["08:00"])
    after = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)  # a Sunday
    assert runs(rule, SAO_PAULO, after, 3) == [
        "2026-10-26T11:00:00+00:00",
        "2026-10-28T11:00:00+00:00",
        "2026-11-02T11:00:00+00:00",
    ]
    assert describe(rule) == "Every week on Mon, Wed at 08:00"
    fortnight = Recurrence(
        freq="weeks", every=2, weekdays=[4], times=["08:00"], start=date(2026, 10, 19)
    )
    assert runs(fortnight, SAO_PAULO, after, 2) == [
        "2026-11-06T11:00:00+00:00",
        "2026-11-20T11:00:00+00:00",
    ]


def test_monthly_on_a_day_the_last_day_and_the_first_monday():
    after = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    first = Recurrence(freq="months", month_day=1, times=["06:00"])
    assert runs(first, SAO_PAULO, after, 2) == [
        "2026-11-01T09:00:00+00:00",
        "2026-12-01T09:00:00+00:00",
    ]
    last = Recurrence(freq="months", month_day=-1, times=["23:00"])
    assert runs(last, SAO_PAULO, after, 2)[1] == "2026-12-01T02:00:00+00:00"  # Nov 30, 23:00
    monday = Recurrence(freq="months", month_weekday={"n": 1, "weekday": 0}, times=["06:00"])
    assert runs(monday, SAO_PAULO, after, 2) == [
        "2026-11-02T09:00:00+00:00",
        "2026-12-07T09:00:00+00:00",
    ]
    assert describe(monday) == "Every month on the first Mon at 06:00"
    # Day 31 runs on the last day of a shorter month.
    late = Recurrence(freq="months", month_day=31, times=["06:00"])
    assert runs(late, SAO_PAULO, after, 2)[1] == "2026-11-30T09:00:00+00:00"


def test_a_first_and_a_last_day():
    rule = Recurrence(freq="days", times=["06:00"], start=date(2026, 11, 2), end=date(2026, 11, 3))
    after = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    assert runs(rule, SAO_PAULO, after) == [
        "2026-11-02T09:00:00+00:00",
        "2026-11-03T09:00:00+00:00",
    ]
    assert describe(rule).endswith(", from 2026-11-02, until 2026-11-03")


def test_wall_clock_times_hold_across_daylight_saving():
    rule = Recurrence(freq="days", times=["06:00"])
    # Berlin leaves summer time on 2026-10-25: 06:00 is 04:00 UTC before, 05:00 UTC after.
    after = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)
    assert runs(rule, BERLIN, after, 2) == [
        "2026-10-24T04:00:00+00:00",
        "2026-10-25T05:00:00+00:00",
    ]


@pytest.mark.parametrize(
    "fields",
    [
        {"freq": "weeks", "times": ["08:00"]},  # no weekday
        {"freq": "months", "times": ["08:00"]},  # no day of the month
        {"freq": "days", "times": ["25:00"]},
        {"freq": "minutes", "between": ("18:00", "06:00")},
        {"freq": "days", "times": ["08:00"], "start": "2026-11-02", "end": "2026-11-01"},
        {"freq": "hours", "every": 30},
    ],
)
def test_rules_that_cannot_run_are_refused(fields):
    with pytest.raises(ValidationError):
        Recurrence(**fields)


def test_local_time_is_the_installation_s_zone_and_follows_it():
    from linkcraft.engine.zones import use_installation_zone, zone_of

    rule = Recurrence(freq="days", times=["06:00"])
    after = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    try:
        use_installation_zone(lambda: SAO_PAULO)
        assert str(zone_of("local")) == SAO_PAULO and str(zone_of(None)) == SAO_PAULO
        assert next_after(rule, "local", after).isoformat() == "2026-10-26T09:00:00+00:00"
        use_installation_zone(lambda: BERLIN)  # the installation moved: so does "local"
        assert next_after(rule, "local", after).isoformat() == "2026-10-26T05:00:00+00:00"
        assert str(zone_of("Etc/GMT+3")) == "Etc/GMT+3"

        def away() -> str:
            raise OSError("PlantCraft is away")

        use_installation_zone(away)
        assert str(zone_of("local")) == "UTC"
    finally:
        use_installation_zone(lambda: "UTC")
