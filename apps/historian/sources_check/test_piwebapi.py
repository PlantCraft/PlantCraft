"""PI Web API: the kit's server read as Historian reads PI (mode source), and its failures."""

from __future__ import annotations

import pytest
from simcraft.testkit.piwebapi import USER, PiWebApi

from histcraft.sources.history import open_source

pytestmark = pytest.mark.slow


def _source(pi: PiWebApi, **options) -> dict:
    return {
        "id": "pi",
        "name": "Plant PI",
        "kind": "pi_web_api",
        "endpoint": pi.base_url,
        "namespace_uri": "",
        "username": USER[0],
        "options": {"server": "pisrv", "auth_type": "basic", "timeout_seconds": 5, **options},
    }


def test_recorded_values_and_states_match_the_plant(series):
    start = min(item.times[0] for item in series.values())
    end = max(item.times[-1] for item in series.values())
    with PiWebApi(series) as pi:
        reader = open_source(_source(pi, page_size=50), USER[1])
        assert reader.test()
        found = reader.browse("FIC-101.*")["variables"]
        assert {item["tag"] for item in found} == {t for t in series if t.startswith("FIC-101.")}
        read = reader.recorded(list(series), start, end)
        assert pi.methods.keys() == {"GET"}
    for tag, published in series.items():
        assert not isinstance(read[tag], str), (tag, read[tag])
        times, values = read[tag]
        assert list(times) == published.times, tag
        if published.kind == "text":
            assert list(values) == published.values, tag
        else:
            assert list(values) == pytest.approx(published.values, rel=1e-12), tag


def test_a_burst_of_503_is_retried_and_a_slow_server_is_named(series):
    tag = "PIC-102.PV"
    window = (series[tag].times[0], series[tag].times[-1])
    with PiWebApi(series) as pi:
        pi.fail_next["recorded"] = 2
        times, _ = open_source(_source(pi, retries=3), USER[1]).recorded([tag], *window)[tag]
        assert list(times) == series[tag].times
        pi.delay_seconds = 3
        answer = open_source(_source(pi, retries=0, timeout_seconds=1), USER[1]).recorded(
            [tag], *window
        )[tag]
        assert isinstance(answer, str) and answer  # an error for the tag, not an exception


def test_a_wrong_password_is_refused_by_the_test(series):
    with PiWebApi(series) as pi, pytest.raises(Exception, match="(?i)auth|401|denied"):
        open_source(_source(pi), "wrong").test()
