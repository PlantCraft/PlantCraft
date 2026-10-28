from datetime import UTC, datetime, timedelta

from simcraft.healthcheck import _source_is_fresh


def test_healthcheck_requires_a_recent_representative_source_timestamp() -> None:
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)

    assert _source_is_fresh(now - timedelta(seconds=30), now=now, maximum_age_seconds=60)
    assert _source_is_fresh(
        now.replace(tzinfo=None),
        now=now,
        maximum_age_seconds=60,
    )
    assert not _source_is_fresh(
        now - timedelta(seconds=61),
        now=now,
        maximum_age_seconds=60,
    )
    assert not _source_is_fresh(None, now=now, maximum_age_seconds=60)
