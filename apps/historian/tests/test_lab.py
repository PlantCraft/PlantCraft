"""Laboratory results stored at their sampling time, with their other times (``/api/v1/lab``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import client_for

LAB = "/hist/api/v1/lab"


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_late_result_is_stored_at_its_sampling_time(client, runtime):
    now = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    sampled, received = now - timedelta(hours=6), now - timedelta(hours=4)
    body = {
        "results": [
            {
                "signal": "laboratory:VISC-101",
                "sampled_at": _stamp(sampled),
                "received_at": _stamp(received),
                "value": 412.0,
                "unit": "cP",
                "name": "Viscosity, reactor outlet",
            },
            {"signal": "plant:VISC-101", "sampled_at": _stamp(sampled), "value": 1},
            {"signal": "laboratory:VISC-101", "sampled_at": "yesterday", "value": 1},
            {
                "signal": "laboratory:VISC-101",
                "sampled_at": _stamp(sampled),
                "received_at": _stamp(sampled - timedelta(hours=1)),
                "value": 1,
            },
        ]
    }
    answer = client.post(LAB, json=body).json()
    assert answer["written"] == 1
    assert [error["status"] for error in answer["errors"]] == [422, 422, 422]
    # The value is a signal at the sampling time, uncertain until approved.
    series = client.post(
        "/hist/api/v1/series",
        json={
            "signals": ["laboratory:VISC-101"],
            "start": _stamp(now - timedelta(hours=8)),
            "end": _stamp(now),
        },
    ).json()["series"][0]
    assert series["v"] == [412.0] and series["t"][0].startswith(sampled.strftime("%Y-%m-%dT%H:%M"))
    point = client.get("/hist/api/points/laboratory:VISC-101").json()
    assert point["unit"] == "cP"
    found = client.get(f"{LAB}/laboratory:VISC-101").json()["samples"]
    assert len(found) == 1 and found[0]["status"] == "entered" and found[0]["writes"] == 1
    assert found[0]["received_at"].startswith(received.strftime("%Y-%m-%dT%H:%M"))
    assert found[0]["delay_hours"] >= 6
    point_id = int(runtime.catalog.point("laboratory:VISC-101")["id"])
    assert runtime.archive.qualities(point_id, 0, 2**62)[-1][1] == "uncertain"

    # Approved later with a retest value: the same sample, its value replaced, good.
    approved = now - timedelta(hours=1)
    again = {
        "results": [
            {
                "signal": "laboratory:VISC-101",
                "sampled_at": _stamp(sampled),
                "received_at": _stamp(received),
                "approved_at": _stamp(approved),
                "value": 418.5,
            }
        ]
    }
    assert client.post(LAB, json=again).json() == {"written": 1, "errors": []}
    found = client.get(f"{LAB}/laboratory:VISC-101").json()["samples"]
    assert [(item["value"], item["status"], item["writes"]) for item in found] == [
        (418.5, "approved", 2)
    ]
    assert runtime.archive.qualities(point_id, 0, 2**62)[-1][1] == "good"


def test_a_late_result_does_not_hide_a_newer_one(client, runtime):
    now = datetime.now(timezone.utc).replace(microsecond=0, second=0)

    def write(hours: float, value: float) -> None:
        body = {
            "results": [
                {
                    "signal": "laboratory:DENS-1",
                    "sampled_at": _stamp(now - timedelta(hours=hours)),
                    "value": value,
                }
            ]
        }
        assert client.post(LAB, json=body).json()["written"] == 1

    write(2, 0.81)
    write(10, 0.79)  # yesterday's sample, arriving now
    point_id = int(runtime.catalog.point("laboratory:DENS-1")["id"])
    assert runtime.archive.snapshots([point_id])[point_id]["value"] == 0.81


def test_only_editors_write_results(runtime, fake):
    viewer = client_for(runtime, fake, "ana")
    body = {
        "results": [{"signal": "laboratory:X", "sampled_at": "2026-10-31T00:00:00Z", "value": 1}]
    }
    assert viewer.post(LAB, json=body).status_code == 403
