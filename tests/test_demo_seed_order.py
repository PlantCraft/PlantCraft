"""The demo seed's order: the plant's data (Historian backfill, Analytics, alarm replay) runs on its
own thread beside the people, View and Documents, and still waits for the cast before alarms and
models. Each step is a stand-in that sleeps; no suite runs here."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from plantcraft import demo_seed

STEP = 0.25


class _Client:
    def post(self, path: str, *args: Any, **kwargs: Any) -> dict[str, str]:
        return {"token": "t"}


def _suite() -> demo_seed.Suite:
    suite = demo_seed.Suite(
        processcraft="http://plantcraft",
        apps={
            app: f"http://{app}"
            for app in (
                "histcraft",
                "linkcraft",
                "dashcraft",
                "alarmcraft",
                "modelcraft",
                "doccraft",
            )
        },
        admin="admin",
        password="pw",
        visitor_password="pw",
        demo_map=Path("map.json"),
    )
    suite.session = lambda *_args: _Client()  # type: ignore[method-assign]
    suite.app = lambda _session, app_id: _Client()  # type: ignore[method-assign]
    return suite


@pytest.fixture
def timeline(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, float]]:
    events: list[tuple[str, str, float]] = []
    lock = threading.Lock()
    began = time.monotonic()

    def slow(name: str, seconds: float, answer: Any = None):
        def run(*_args: Any, **_kwargs: Any) -> Any:
            with lock:
                events.append((name, "start", time.monotonic() - began))
            time.sleep(seconds)
            with lock:
                events.append((name, "end", time.monotonic() - began))
            return answer

        return run

    # The long jobs and the work that does not read the plant's data.
    for name, seconds in {
        "histcraft": STEP,
        "linkcraft": 0.0,
        "link_models": 0.0,
        "alarmcraft": STEP,
        "modelcraft": 0.0,
        "dashcraft": STEP / 2,
        "view_reports": 0.0,
        "view_trends": 0.0,
        "view_diagrams": 0.0,
        "doccraft": STEP,
        "groups": 0.0,
    }.items():
        monkeypatch.setattr(demo_seed, name, slow(name, seconds))
    monkeypatch.setattr(demo_seed, "people", slow("people", STEP, {}))
    for name in (
        "histcraft_lab",
        "histcraft_import",
        "histcraft_calc",
        "plant_map",
        "archive_signals",
        "retire_specialist",
        "actions",
        "follow_ups",
        "desk",
        "team_day",
    ):
        monkeypatch.setattr(demo_seed, name, slow(name, 0.0))
    monkeypatch.setattr(demo_seed, "_workspace", lambda: None)
    monkeypatch.setattr(demo_seed, "story_links", lambda *_a: demo_seed.Links())
    monkeypatch.setattr(demo_seed, "conversations", lambda *_a: [])
    monkeypatch.setattr(demo_seed, "Http", lambda *_a, **_k: _Client())
    return events


def _at(events: list[tuple[str, str, float]], name: str, edge: str) -> float:
    return next(at for step, kind, at in events if step == name and kind == edge)


def test_the_plant_data_runs_beside_the_people_and_view(timeline):
    began = time.monotonic()
    assert demo_seed.run(_suite()) == 0
    took = time.monotonic() - began
    # In a row: histcraft, people, dashcraft/2, alarmcraft, doccraft = 4.5 steps; side by side the
    # data chain (histcraft, then alarmcraft once the cast exists) takes about 2.
    assert took < 3.0 * STEP, took
    assert _at(timeline, "histcraft", "start") < _at(timeline, "people", "end")
    # Alarm rules and models name the cast: never before it exists.
    assert _at(timeline, "alarmcraft", "start") >= _at(timeline, "people", "end")
    assert _at(timeline, "modelcraft", "start") >= _at(timeline, "groups", "end")


def test_a_failure_in_the_data_chain_reaches_the_caller(timeline, monkeypatch):
    def broken(*_args: Any) -> None:
        raise RuntimeError("Historian down")

    monkeypatch.setattr(demo_seed, "histcraft", broken)
    with pytest.raises(RuntimeError, match="Historian down"):
        demo_seed.run(_suite())
