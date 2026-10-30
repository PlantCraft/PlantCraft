"""The CSV reader shared by imports and CSV sources: shapes, separators, times, and a report
that names the lines to fix (the platform says whether the file is right)."""

from __future__ import annotations

from datetime import datetime, timezone

from histcraft.sources.csv_table import read_table

NOW = int(datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp() * 1000)


def iso(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M")


def read(data: bytes, zone: str = "America/Sao_Paulo"):
    return read_table(data, zone, now_ms=NOW)


def test_a_wide_file_with_local_times():
    table = read(b"time,FI-101,state\n2026-10-01 08:00,1.5,open\n2026-10-01 09:00,,closed\n")
    assert (table.shape, table.times, table.rows, table.values) == ("wide", "local", 2, 3)
    assert [iso(ms) for ms in table.series["FI-101"].times] == ["2026-10-01T11:00"]
    assert table.series["state"].kind == "text"
    assert not table.errors and not table.warnings


def test_a_brazilian_excel_export():
    data = "Data;FI-101\n13/10/2026 08:00;1,5\n01/10/2026 09:00;2.250,25\n".encode("cp1252")
    table = read(data)
    assert (table.delimiter, table.decimal) == (";", ",")
    series = table.series["FI-101"]
    assert [iso(ms) for ms in series.times] == ["2026-10-01T12:00", "2026-10-13T11:00"]
    assert series.values == [2250.25, 1.5]
    assert "day/month" in table.warnings[0]["message"]


def test_iso_dates_are_never_read_as_day_first():
    data = b"time;A\n13/10/2026 08:00;1,5\n2026-10-01T09:00:00-03:00;2,5\n"
    times = read(data).series["A"].times
    assert [iso(ms) for ms in times] == ["2026-10-01T12:00", "2026-10-13T11:00"]


def test_a_long_file_with_qualities():
    data = (
        b"timestamp,tag,value,quality\n"
        b"2026-10-01T08:00:00Z,A,1,good\n"
        b"2026-10-01T09:00:00Z,A,2,bad\n"
        b"2026-10-01T10:00:00Z,A,3,\n"
        b"2026-10-01T08:00:00Z,B,3,\n"
    )
    table = read(data)
    assert table.shape == "long" and table.times == "offset"
    assert table.series["A"].values == [1.0, 2.0, 3.0]
    assert [(iso(ms), q) for ms, q in table.series["A"].qualities] == [
        ("2026-10-01T09:00", "bad"),
        ("2026-10-01T10:00", "good"),
    ]


def test_epoch_seconds_and_milliseconds():
    seconds = read(b"t,X\n1792800000,1\n").series["X"].times[0]
    millis = read(b"t,X\n1792800000000,1\n").series["X"].times[0]
    assert seconds == millis == 1792800000000


def test_errors_name_the_lines_to_fix():
    data = b"time,A,B\n2026-10-01 08:00,1,2\nyesterday,3,4\n2026-10-01 10:00,x,5\n"
    errors = {item["message"]: item["lines"] for item in read(data).errors}
    assert errors == {"Times that could not be read": [3], "Values in A that are not numbers": [4]}


def test_the_last_line_at_a_time_wins_and_is_reported():
    table = read(b"time,A\n2026-10-01 08:00,1\n2026-10-01 08:00,2\n")
    assert table.series["A"].values == [2.0]
    assert table.warnings[0]["lines"] == [2]


def test_a_file_that_cannot_be_imported():
    for data in (b"", b"time\n2026-10-01\n", b"time,A,A\n2026-10-01,1,2\n", b"time,,B\n2026,1,2\n"):
        assert read(data).errors, data


def test_times_ahead_are_reported():
    table = read(b"time,A\n2027-10-01 08:00,1\n")
    assert "a day ahead" in table.warnings[0]["message"]


def test_empty_markers_are_gaps_not_errors():
    table = read(b"time,A\n2026-10-01 08:00,N/A\n2026-10-01 09:00,#N/A\n2026-10-01 10:00,4\n")
    assert not table.errors and table.series["A"].values == [4.0]
