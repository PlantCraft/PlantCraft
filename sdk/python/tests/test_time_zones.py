"""The installation's time zone through API v1, and what "local" means in a schedule."""

from __future__ import annotations

from plantcraft_sdk.testing import FakePlantCraft
from plantcraft_sdk.utc import LOCAL, resolve_zone


def test_an_app_reads_the_installation_zone():
    fake = FakePlantCraft(time_zone="America/Sao_Paulo")
    client = fake.client("engineer")
    assert client.installation_time_zone() == "America/Sao_Paulo"
    fake.time_zone = "Europe/Berlin"
    # Cached for a minute: a schedule check every few seconds asks once.
    assert client.installation_time_zone() == "America/Sao_Paulo"


def test_local_is_the_installation_zone():
    assert resolve_zone(LOCAL, "America/Sao_Paulo").key == "America/Sao_Paulo"
    assert resolve_zone("", "America/Sao_Paulo").key == "America/Sao_Paulo"
    assert resolve_zone("Not/AZone", "America/Sao_Paulo").key == "America/Sao_Paulo"
    assert resolve_zone("Etc/GMT+3", "America/Sao_Paulo").key == "Etc/GMT+3"
    assert resolve_zone(LOCAL, "").key == "UTC"


def test_parse_instant_reads_iso_times_and_answers_none_for_the_rest():
    from datetime import datetime, timezone

    from plantcraft_sdk.utc import parse_instant

    assert parse_instant("2026-10-25T14:05:09.123Z") == datetime(
        2026, 10, 25, 14, 5, 9, 123000, tzinfo=timezone.utc
    )
    # Without an offset the time is UTC; with one it keeps it.
    assert parse_instant("2026-10-25T14:05").tzinfo == timezone.utc
    assert parse_instant("2026-10-25T11:05-03:00").utcoffset().total_seconds() == -3 * 3600
    assert parse_instant(datetime(2026, 10, 25)).tzinfo == timezone.utc  # noqa: DTZ001
    for junk in (None, "", "  ", "yesterday", 42, "2026-13-01"):
        assert parse_instant(junk) is None


def test_local_is_the_installation_s_zone_and_texts_are_written_on_its_clock():
    from plantcraft_sdk.utc import local_text, use_installation_zone, zone_of

    use_installation_zone(lambda: "America/Sao_Paulo")
    try:
        assert zone_of("local").key == "America/Sao_Paulo"
        assert zone_of(None).key == "America/Sao_Paulo"
        assert zone_of("UTC").key == "UTC"
        assert zone_of("Mars/Olympus").key == "America/Sao_Paulo"
        assert local_text("2026-10-27T03:00:00Z") == "2026-10-27 00:00"
        assert local_text("2026-10-27T03:00:00Z", "%H:%M", zone="UTC") == "03:00"
        assert local_text("") == "—"

        def away() -> str:
            raise OSError("PlantCraft away")

        use_installation_zone(away)
        assert zone_of("local").key == "UTC"
    finally:
        use_installation_zone(lambda: "UTC")
