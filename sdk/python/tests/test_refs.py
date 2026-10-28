"""References of the suite (docs/app-standard.md, section 2)."""

from __future__ import annotations

import pytest

from plantcraft_sdk.refs import (
    Ref,
    RefError,
    asset_ref,
    format_ref,
    parse_ref,
    run_ref,
    signal_ref,
    split_signal_id,
    user_ref,
    valid_id,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("asset:u200-fic1001", Ref("asset", "u200-fic1001")),
        ("signal:pi:FIC1001.PV", Ref("signal", "FIC1001.PV", source="pi")),
        ("signal:opcua-1:ns=2;s=Loop:PV", Ref("signal", "ns=2;s=Loop:PV", source="opcua-1")),
        ("signal:scenario:FIC-101.PV", Ref("signal", "FIC-101.PV", source="scenario")),
        ("signal:2-pi:FIC1001.PV", Ref("signal", "FIC1001.PV", source="2-pi")),
        # PI tags keep their spaces and backslashes: refs are never percent-encoded.
        ("signal:pi:Unit 2\\FIC 101.PV", Ref("signal", "Unit 2\\FIC 101.PV", source="pi")),
        ("signal:pi:a/b%20c", Ref("signal", "a/b%20c", source="pi")),
        # Bare tags (ids before signals named their source), read until API v1 is frozen.
        ("signal:FIC1001.PV", Ref("signal", "FIC1001.PV")),
        ("signal:pv", Ref("signal", "pv")),
        ("signal:FIC:101", Ref("signal", "FIC:101")),
        ("user:jonathan", Ref("user", "jonathan")),
        ("run:linkcraft/2026-10-19-0600", Ref("run", "2026-10-19-0600", app="linkcraft")),
    ],
)
def test_parse_and_format_round_trip(text, expected):
    assert parse_ref(text) == expected
    assert str(expected) == text
    assert format_ref(expected.kind, expected.id, source=expected.source, app=expected.app) == text


def test_helpers():
    assert asset_ref("u200-fic1001") == "asset:u200-fic1001"
    assert signal_ref("FIC1001.PV", "pi") == "signal:pi:FIC1001.PV"
    assert signal_ref("FIC1001.PV") == "signal:FIC1001.PV"
    # An API v1 signal id makes its reference as it is.
    assert signal_ref("pi:FIC1001.PV") == "signal:pi:FIC1001.PV"
    assert parse_ref("signal:pi:FIC1001.PV").signal_id == "pi:FIC1001.PV"
    assert parse_ref("signal:FIC1001.PV").signal_id == "FIC1001.PV"
    assert split_signal_id("scenario:FIC-101.PV") == ("scenario", "FIC-101.PV")
    assert split_signal_id("FIC:101") == (None, "FIC:101")
    assert valid_id("Unit 2\\FIC 101.PV") and not valid_id(" padded") and not valid_id("a\tb")
    with pytest.raises(RefError):
        _ = parse_ref("asset:x").signal_id
    assert user_ref("jonathan") == "user:jonathan"
    assert run_ref("linkcraft", "r1") == "run:linkcraft/r1"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "asset",
        "asset:",
        "loop:FIC-101",
        "asset: padded",
        "asset:a\nb",
        "signal:",
        "run:linkcraft",
        "run:CPM/r1",
        "run:linkcraft/",
        "run:linkcraft/has space",
        "user:" + "x" * 301,
        None,
        42,
    ],
)
def test_bad_references_are_refused(text):
    with pytest.raises(RefError):
        parse_ref(text)


def test_bad_formats_are_refused():
    with pytest.raises(RefError):
        format_ref("loop", "x")
    with pytest.raises(RefError):
        format_ref("run", "r1")
    with pytest.raises(RefError):
        format_ref("signal", "x", source="Not A Source")
    with pytest.raises(RefError):
        format_ref("asset", "x", app="linkcraft")
