"""The widget test page: every widget of Desk and of the installed apps at
every size it allows, in the light and the dark theme. A widget whose content spills out of its
card (taller or wider than the card gives it) fails here."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import expect

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS", "")

# Each card's body against what it draws; a card's title may be cut with an ellipsis on purpose.
SPILLS = """() => [...document.querySelectorAll('.pc-wg-gallery-cell')].flatMap((cell) => {
  const body = cell.querySelector('.pc-wg-body');
  if (!body) return [];
  const tall = body.scrollHeight - body.clientHeight;
  const wide = body.scrollWidth - body.clientWidth;
  const card = cell.querySelector('.pc-wg-card').getBoundingClientRect();
  const box = cell.querySelector(':scope > div').getBoundingClientRect();
  const bad = [];
  if (tall > 1) bad.push(`${tall}px too tall`);
  if (wide > 1) bad.push(`${wide}px too wide`);
  if (Math.abs(card.height - box.height) > 1) bad.push('card not the size of its cell');
  return bad.length ? [`${cell.dataset.widget} ${cell.dataset.size}: ${bad.join(', ')}`] : [];
})"""

# How much of each card's body is left empty (reported, not failed: an empty list is short).
SPARE = """() => Object.fromEntries([...document.querySelectorAll('.pc-wg-gallery-cell')].map((cell) => {
  const body = cell.querySelector('.pc-wg-body');
  const top = body.getBoundingClientRect().top;
  const used = Math.max(0, ...[...body.querySelectorAll('*')].map((node) => node.getBoundingClientRect().bottom - top));
  return [`${cell.dataset.widget} ${cell.dataset.size}`, Math.round(100 - (100 * Math.min(used, body.clientHeight)) / Math.max(1, body.clientHeight))];
}))"""


def _seed(page) -> list[tuple[str, dict]]:
    """Actions in every column, some late, and a full checklist: the lists fill their cards.
    Returns what to take away after (the other journeys share the server)."""

    today = datetime.now().astimezone().date()
    made: list[tuple[str, dict]] = []
    for index, (status, due) in enumerate(
        [("open", -2), ("open", 0), ("open", 1), ("open", 3), ("open", None), ("in_progress", 0),
         ("in_progress", 5), ("blocked", -1), ("open", 9), ("in_progress", None)]
    ):  # fmt: skip
        body = {
            "title": f"Gallery action {index + 1}: check the valve positioner of FIC-10{index}",
            "description": "",
            "priority": ["high", "medium", "low"][index % 3],
            "owner": "admin",
            "due_at": (today + timedelta(days=due)).isoformat() if due is not None else None,
            "refs": [],
        }
        created = page.request.post("/api/actions", data=body)
        assert created.ok, created.text()
        action = created.json()
        made.append((f"/api/actions/{action['action_id']}", {**body, "status": "cancelled"}))
        if status != "open":
            moved = page.request.put(
                f"/api/actions/{action['action_id']}", data={**body, "status": status}
            )
            assert moved.ok, moved.text()
    for index in range(8):
        added = page.request.post(
            "/api/desk/todos",
            data={"title": f"Gallery item {index + 1}: read the night log", "my_day": True},
        )
        assert added.ok, added.text()
        made.append((f"/api/desk/todos/{added.json()['todo_id']}", {}))
    return made


def _clean(page, made: list[tuple[str, dict]]) -> None:
    for path, body in made:
        response = page.request.put(path, data=body) if body else page.request.delete(path)
        assert response.ok, response.text()


def test_every_widget_fits_every_size_it_allows(page):
    made = _seed(page)
    try:
        _check_gallery(page)
    finally:
        _clean(page, made)


def _check_gallery(page) -> None:
    page.goto("/widgets")
    expect(page.get_by_role("heading", name="Widgets", exact=True)).to_be_visible()
    cells = page.locator(".pc-wg-gallery-cell")
    expect(cells.first).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert cells.count() >= 30
    for theme in ("light", "dark"):
        page.evaluate(
            "(theme) => document.documentElement.setAttribute('data-theme', theme)", theme
        )
        page.wait_for_timeout(200)
        spills = page.evaluate(SPILLS)
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(SHOTS) / f"widgets-{theme}.png"), full_page=True)
            (Path(SHOTS) / "widgets-spare.json").write_text(
                json.dumps(page.evaluate(SPARE), indent=1)
            )
        assert not spills, f"Widgets spilling out of their cards ({theme}): {spills}"


def test_a_widget_is_added_from_the_window_at_a_size_and_only_moves(page):
    page.goto("/")
    page.get_by_role("button", name="Customize").click()
    page.get_by_role("button", name="Add a widget").click()
    dialog = page.get_by_role("dialog", name="Add a widget")
    expect(dialog.get_by_role("navigation", name="Apps")).to_be_visible()
    tile = dialog.locator(".pc-wg-tile", has_text="Quick note")
    tile.get_by_role("radio", name="Large").click()
    expect(tile.get_by_role("radio", name="Large")).to_have_attribute("aria-checked", "true")
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / "desk-add-widget.png"))
    tile.get_by_role("button", name="Add").click()
    expect(dialog).to_have_count(0)
    note = page.locator(".pc-wg-card", has_text="Quick note")
    expect(note).to_be_visible()
    # Fixed sizes: no corner to pull; the gear changes the size.
    expect(page.locator(".pc-cards .react-resizable-handle:visible")).to_have_count(0)
    note.get_by_role("button", name="Set up Quick note").click()
    settings = page.get_by_role("dialog", name="Widget settings")
    settings.get_by_role("radio", name="Small").click()
    settings.get_by_role("button", name="Apply").click()
    page.get_by_role("button", name="Done").click()
    page.get_by_role("textbox", name="Quick note").fill("Call the analyzer supplier at 14:00")
    page.wait_for_timeout(1200)
    page.reload()
    expect(page.get_by_role("textbox", name="Quick note")).to_have_value(
        "Call the analyzer supplier at 14:00"
    )
