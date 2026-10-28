"""plantcraft_sdk.desk: what an app puts in Desk, checked the same way here and in PlantCraft."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from plantcraft_sdk.desk import FeedIn, TodoIn


def test_a_calendar_item_is_whole_days_or_instants_and_ends_after_it_starts():
    days = {"id": "1", "title": "Review", "start": "2026-11-03", "all_day": True}
    assert FeedIn.model_validate({"items": [days]}).items[0].audience == "everyone"
    at = {"id": "2", "title": "Review", "start": "2026-11-03T09:00:00-03:00"}
    assert FeedIn.model_validate({"items": [at]}).items[0].all_day is False
    for bad in (
        {**days, "all_day": False},
        {**at, "all_day": True},
        {**days, "end": "2026-11-01"},
        {**days, "audience": "user:"},
        {**days, "colour": "red"},
    ):
        with pytest.raises(ValidationError):
            FeedIn.model_validate({"items": [bad]})
    with pytest.raises(ValidationError):
        FeedIn.model_validate({"items": [days, days]})


def test_a_to_do_is_for_a_person_or_a_group_and_keeps_its_for_field_name():
    todo = TodoIn.model_validate({"key": "k", "kind": "review", "title": "x", "for": "group:a"})
    assert todo.as_body() == {"key": "k", "kind": "review", "title": "x", "for": "group:a",
                              "detail": ""}  # fmt: skip
    for bad in ("everyone", "user:", "team:a"):
        with pytest.raises(ValidationError):
            TodoIn.model_validate({"key": "k", "kind": "review", "title": "x", "for": bad})
