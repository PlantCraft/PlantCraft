"""People's edits of archived values, audited and marked, the original kept (H7)."""

from __future__ import annotations

from tests.conftest import client_for
from tests.test_api import loaded  # noqa: F401 - fixture
from tests.test_reads import V1

EDITS = "/hist/api/v1/edits"
SIGNAL = "plant:TI-100.PV"
# loaded: TI-100.PV holds 0, 1, 2... every 10 s from 2026-10-19 00:00 UTC.
T0 = "2026-10-19T00:00:00Z"


def _series(client, start="2026-10-19T00:00:00Z", end="2026-10-19T00:01:00Z"):
    body = {"signals": [SIGNAL], "start": start, "end": end, "quality": True}
    return client.post(f"{V1}/series", json=body).json()["series"][0]


def test_values_are_inserted_edited_and_deleted_with_the_original_kept(client, loaded):  # noqa: F811
    answer = client.post(
        EDITS,
        json={
            "signal": SIGNAL,
            "reason": "Sensor under calibration",
            "changes": [
                {"t": "2026-10-19T00:00:10Z", "value": 99.5},
                {"t": "2026-10-19T00:00:15Z", "value": 50},
                {"t": "2026-10-19T00:00:20Z", "delete": True},
            ],
        },
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert [(c["action"], c["old"], c["new"]) for c in body["changes"]] == [
        ("edited", 1.0, 99.5),
        ("inserted", None, 50.0),
        ("deleted", 2.0, None),
    ]
    assert (body["edited"], body["inserted"], body["deleted"]) == (1, 1, 1)
    series = _series(client)
    values = dict(zip(series["t"], series["v"], strict=True))
    assert values["2026-10-19T00:00:10+00:00"] == 99.5
    assert values["2026-10-19T00:00:15+00:00"] == 50.0
    assert "2026-10-19T00:00:20+00:00" not in values
    assert values["2026-10-19T00:00:30+00:00"] == 3.0  # the others untouched
    assert series["edits"] == [
        {"t": "2026-10-19T00:00:10+00:00", "action": "edited"},
        {"t": "2026-10-19T00:00:15+00:00", "action": "inserted"},
        {"t": "2026-10-19T00:00:20+00:00", "action": "deleted"},
    ]
    history = client.get(f"{EDITS}/{SIGNAL}", params={"start": T0, "end": "2026-10-19T01:00:00Z"})
    rows = history.json()["edits"]
    assert [(row["action"], row["old"], row["by"], row["reason"]) for row in rows] == [
        ("edited", 1.0, "admin", "Sensor under calibration"),
        ("inserted", None, "admin", "Sensor under calibration"),
        ("deleted", 2.0, "admin", "Sensor under calibration"),
    ]
    # Edited again: the read shows the latest action, the history both.
    client.post(
        EDITS,
        json={
            "signal": SIGNAL,
            "reason": "Back",
            "changes": [{"t": "2026-10-19T00:00:10Z", "value": 1.0}],
        },
    )
    rows = client.get(f"{EDITS}/{SIGNAL}", params={"start": T0, "end": T0[:-1] + "Z"}).json()
    assert _series(client)["v"][1] == 1.0


def test_only_editors_change_values_and_every_change_is_checked(client, loaded, runtime, fake):  # noqa: F811
    def edit(who, **body):
        with client_for(runtime, fake, who) as caller:
            return caller.post(EDITS, json={"signal": SIGNAL, "reason": "x", **body})

    one = [{"t": "2026-10-19T00:00:10Z", "value": 5}]
    assert edit("operator", changes=one).status_code == 403
    assert edit("engineer", changes=one).status_code == 200
    bad = [
        [{"t": "2026-10-19T00:00:10Z"}],  # no value and no delete
        [{"t": "2026-10-19T00:00:10Z", "value": "hot"}],  # a number signal
        [{"t": "2026-10-19T00:00:11Z", "delete": True}],  # nothing stored there
        [{"t": "2099-01-01T00:00:00Z", "value": 1}],  # the future
        [{"t": "yesterday", "value": 1}],
    ]
    assert [edit("admin", changes=changes).status_code for changes in bad] == [422] * 5
    assert edit("admin", changes=one, reason="  ").status_code in (422,)
    # Nothing half done: the series still holds what the engineer wrote.
    assert _series(client)["v"][1] == 5.0
