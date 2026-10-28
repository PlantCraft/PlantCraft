"""People, groups and notifications through the client, against FakePlantCraft."""

from __future__ import annotations

import pytest

from plantcraft_sdk.client import Forbidden, PlantCraftClient, PlantCraftError
from plantcraft_sdk.contract import ContractError
from plantcraft_sdk.people import check_notification, recipient
from plantcraft_sdk.testing import FakePlantCraft


def _service(fake: FakePlantCraft) -> PlantCraftClient:
    client = fake.client("engineer")
    grant = client.service_token("linkcraft", "test-app-key")
    return client.with_token(grant["token"], app="linkcraft")


def test_people_and_groups_are_listed_without_contact_details():
    fake = FakePlantCraft()
    client = fake.client("engineer")
    people = {person["username"]: person for person in client.people()}
    assert people["engineer"]["groups"] == ["process-engineering"]
    assert "email" not in people["engineer"]
    groups = {group["id"]: group for group in client.groups()}
    assert groups["operations"]["members"] == ["operator"]


def test_an_app_notifies_people_and_groups():
    fake = FakePlantCraft()
    receipt = _service(fake).notify(
        [recipient("group", "process-engineering"), "user:operator", "user:ghost"],
        "FIC-101 flow low",
        priority="high",
        url="/link/loops/fic-101",
    )
    assert receipt == {
        "delivered": ["engineer", "admin", "operator"],
        "email_queued": 0,
        "unknown": ["user:ghost"],
    }
    assert fake.notifications[0]["app"] == "linkcraft"
    assert fake.notifications[0]["title"] == "FIC-101 flow low"
    # One thread per key in Messages' Notifications, with a category and buttons (SDK 0.25.0).
    _service(fake).notify(
        ["user:operator"],
        "FIC-101 HI",
        key="alarm:12:3",
        category="alarm",
        actions=[{"label": "Acknowledge", "href": "/alarm/alarms/12"}],
    )
    sent = fake.notifications[-1]
    assert (sent["key"], sent["category"]) == ("alarm:12:3", "alarm")
    assert sent["actions"] == [
        {"label": "Acknowledge", "href": "/alarm/alarms/12", "method": "GET"}
    ]


def test_a_button_runs_a_call_and_the_app_settles_the_thread():
    """SDK 0.53.0, docs/quick-access.md: a POST button acts in the app as the person; the app
    settles the thread for everyone when it is done."""

    fake = FakePlantCraft()
    app = _service(fake)
    app.notify(
        ["user:operator"],
        "FIC-101 HI",
        key="alarm:12:3",
        actions=[{"label": "Acknowledge", "href": "/link/api/alarms/12/ack", "method": "POST"}],
    )
    assert fake.notifications[-1]["actions"][0]["method"] == "POST"
    settled = app.resolve_notification("alarm:12:3", "Acknowledged by Operator")
    assert settled["key"] == "alarm:12:3" and settled["note"] == "Acknowledged by Operator"
    assert fake.resolved_notifications == {("linkcraft", "alarm:12:3"): "Acknowledged by Operator"}
    with pytest.raises(Forbidden):
        fake.client("engineer").resolve_notification("alarm:12:3")
    with pytest.raises(ContractError):
        check_notification(
            {
                "recipients": ["user:a"],
                "title": "x",
                "actions": [{"label": "Go", "href": "/x", "method": "DELETE"}],
            }
        )


def test_only_a_service_token_notifies_and_bodies_are_checked():
    fake = FakePlantCraft()
    with pytest.raises(Forbidden):
        fake.client("engineer").notify(["user:operator"], "x")
    with pytest.raises(PlantCraftError):
        _service(fake).notify(["user:operator"], "x", url="https://example.com")
    with pytest.raises(ContractError):
        check_notification({"recipients": [], "title": "x"})
    with pytest.raises(ContractError):
        recipient("team", "x")
    with pytest.raises(ContractError):
        check_notification({"recipients": ["user:a"], "title": "x", "category": "news"})
    with pytest.raises(ContractError):
        check_notification(
            {
                "recipients": ["user:a"],
                "title": "x",
                "actions": [{"label": "Go", "href": "https://x"}],
            }
        )
