"""The central app clicked through in a real browser: sign-in, Desk, launcher, assets, people, keys, apps."""

from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import expect

from tests import app_packages
from tests.e2e.conftest import ADMIN_PASSWORD

# Desk's first page greets the person (Desk is the first screen).
GREETING = re.compile(r"^Good (morning|afternoon|evening)")

# Screenshots for the review of the Apps page, when the folder is given.
SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS")


def test_sign_in_opens_the_launcher(signed_out_page):
    page = signed_out_page
    page.goto("/")
    expect(page.get_by_role("heading", name="Sign in to PlantCraft")).to_be_visible()
    page.get_by_label("Username").fill("admin")
    page.get_by_label("Password").fill("wrong-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator(".form-error")).to_be_visible()
    page.get_by_label("Password").fill(ADMIN_PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name=GREETING)).to_be_visible()


def test_the_guided_tour_walks_the_platform_and_ends_on_the_apps(first_visit_page):
    page = first_visit_page
    page.goto("/")
    tour = page.get_by_role("dialog")
    expect(tour.get_by_role("heading", name="Welcome to PlantCraft")).to_be_visible()
    tour.get_by_role("button", name="Start the tour").click()
    expect(tour.get_by_role("heading", name="Desk: your day")).to_be_visible()
    visited = set()
    for _ in range(30):
        if tour.get_by_role("button", name="Finish").count():
            break
        tour.get_by_role("button", name="Next").click()
        page.wait_for_load_state("networkidle")
        visited.add(re.sub(r"^https?://[^/]+", "", page.url))
    expect(tour.get_by_role("heading", name="Now the apps")).to_be_visible()
    stops = {"/calendar", "/actions", "/assets", "/health", "/users", "/apps", "/admin"}
    assert stops <= visited, visited
    tour.get_by_role("button", name="Finish").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    # seen once: not again on the next visit, but always from the person's menu
    page.goto("/")
    expect(page.get_by_role("heading", name=GREETING)).to_be_visible()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.goto("/admin")
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.locator(".pcs-profile").click()
    page.get_by_role("menuitem", name="Take the tour").click()
    expect(
        page.get_by_role("dialog").get_by_role("heading", name="Welcome to PlantCraft")
    ).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_sign_in_returns_to_the_app_that_asked(signed_out_page):
    page = signed_out_page
    page.goto("/login?next=/help")
    page.get_by_label("Username").fill("admin")
    page.get_by_label("Password").fill(ADMIN_PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(re.compile(r"/help$"))
    expect(page.get_by_role("heading", name="Help", exact=True)).to_be_visible()


def test_desk_is_the_first_screen_and_its_pages_open(page):
    page.goto("/")
    expect(page.get_by_role("heading", name=GREETING)).to_be_visible()
    expect(page.locator(".pc-wg-card", has_text="Coming days")).to_be_visible()
    expect(page.locator(".pc-wg-card", has_text="My day")).to_be_visible()
    page.wait_for_load_state("networkidle")
    _shot(page, "desk-today.png")
    # My day's to-dos: added, ticked, still there after a reload.
    page.get_by_label("Add to My day").fill("E2E call the analyzer supplier")
    page.get_by_label("Add to My day").press("Enter")
    item = page.locator(".dk-check li", has_text="E2E call the analyzer supplier")
    expect(item).to_be_visible()
    item.get_by_role("checkbox").click()
    expect(
        page.locator(".dk-check li.dk-done", has_text="E2E call the analyzer supplier")
    ).to_be_visible()
    page.reload()
    expect(
        page.locator(".dk-check li.dk-done", has_text="E2E call the analyzer supplier")
    ).to_be_visible()
    # Customize is discreet; edit mode shows the grid's tools.
    page.get_by_role("button", name="Customize").click()
    expect(page.get_by_role("button", name="Add a widget")).to_be_visible()
    _shot(page, "desk-customize.png")
    page.get_by_role("button", name="Done").click()
    sidebar = page.locator(".pcs-sidebar")
    for name, path in [
        ("Calendar", "/calendar"),
        ("To-do", "/todo"),
    ]:
        sidebar.get_by_role("link", name=name, exact=True).click()
        expect(page).to_have_url(re.compile(f"{path}$"))
        expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
        page.wait_for_load_state("networkidle")
        _shot(page, f"desk-{name.lower()}.png")
    # Team is hidden until an administrator shows it; its page still opens.
    expect(sidebar.get_by_role("link", name="Team", exact=True)).to_have_count(0)
    page.goto("/team")
    expect(page.get_by_role("heading", name="Team", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    _shot(page, "desk-team.png")


def test_the_overview_shows_the_installation_and_the_launcher_comes_back(page):
    """PlantCraft's Overview answers "is the installation healthy?". The apps'
    widgets, what needs attention and the launcher left the default board for the catalog."""

    page.goto("/admin")
    board = page.locator(".pc-wg")
    for title in ("Apps online", "Data connections", "System", "Recent changes"):
        expect(board.locator(".pc-wg-card", has_text=title)).to_be_visible()
    expect(board.locator(".pc-wg-card")).to_have_count(4)
    system = board.locator('[data-widget="system"]')
    expect(system.get_by_text("Free disk")).to_be_visible()
    expect(system.get_by_text("Signed in today")).to_be_visible()
    # The audit log's changes (sign-ins left out), each opening Setup › Audit log.
    expect(board.locator('[data-widget="recent-changes"] a.pc-wg-more')).to_have_attribute(
        "href", "/setup/audit"
    )
    expect(page.get_by_role("navigation", name="Your apps")).to_have_count(0)
    page.get_by_role("button", name="Customize").click()
    page.get_by_role("button", name="Add a widget").click()
    page.get_by_role("dialog", name="Add a widget").get_by_role(
        "region", name="Your apps"
    ).get_by_role("button", name="Add").click()
    launcher = page.get_by_role("navigation", name="Your apps")
    card = launcher.get_by_role("link", name=re.compile(r"\bAnalytics\b"))
    expect(card).to_have_attribute("href", "/link/")
    # The widget shows each app as its mark and name; the version is in its tooltip.
    expect(card).to_have_attribute("title", re.compile(r"v0\.1\.0"))
    # Kept after a reload; "Restore the default" brings the installation's board back.
    page.get_by_role("button", name="Done").click()
    page.reload()
    expect(page.get_by_role("navigation", name="Your apps")).to_be_visible()
    page.get_by_role("button", name="Customize").click()
    page.get_by_role("button", name="Restore the default").click()
    page.get_by_role("button", name="Done").click()
    expect(page.get_by_role("navigation", name="Your apps")).to_have_count(0)
    expect(board.locator(".pc-wg-card")).to_have_count(4)


def test_assets_tree_opens_a_loop_with_its_signals(page):
    page.goto("/assets")
    expect(page.get_by_role("heading", name="Assets", exact=True)).to_be_visible()
    page.get_by_placeholder("Search assets by name or code").fill("FIC-101")
    page.locator(".as-tree a", has_text="FIC-101").first.click()
    expect(page).to_have_url(re.compile(r"/assets/FIC-101$"))
    expect(page.get_by_role("heading", name="Signals")).to_be_visible()


def test_admin_creates_a_person_and_an_app_key(page):
    page.goto("/admin")
    page.get_by_role("link", name="People", exact=True).click()
    expect(page).to_have_url(re.compile(r"/users$"))
    expect(page.get_by_role("heading", name="People", exact=True)).to_be_visible()
    page.get_by_role("button", name="New user").click()
    dialog = page.get_by_role("dialog", name="New user")
    dialog.get_by_label("Username").fill("e2e.viewer")
    dialog.get_by_label("Name", exact=True).fill("E2E Viewer")
    dialog.get_by_label("Initial password").fill("e2e-password-1")
    dialog.get_by_role("button", name="Create user").click()
    expect(page.get_by_text("E2E Viewer was created.")).to_be_visible()
    page.goto("/app-keys")
    expect(page).to_have_url(re.compile(r"/apps/keys$"))
    keys = page.locator(".ac-keys")
    keys.get_by_label("App", exact=True).fill("cpmcraft")
    keys.get_by_label("Label").fill("e2e")
    keys.get_by_role("button", name="Create key").click()
    expect(keys.locator(".ac-key-reveal code")).to_contain_text("pck_")
    expect(keys.locator("tbody tr", has_text="e2e")).to_be_visible()


def test_old_settings_addresses_move(page):
    page.goto("/settings/users")
    expect(page).to_have_url(re.compile(r"/users$"))
    page.goto("/settings")
    expect(page).to_have_url(re.compile(r"/admin$"))
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()


def test_the_user_menu_switches_the_theme_for_every_app(page):
    page.goto("/")
    page.locator(".pcs-profile").click()
    page.get_by_role("radio", name="Dark").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.locator(".pcs-profile").click()
    page.get_by_role("radio", name="System").click()
    expect(page.locator("html")).not_to_have_attribute("data-theme", "dark")


def _shot(page, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / name), full_page=True)


def test_admin_installs_an_app_from_a_signed_package(page, tmp_path):
    package = app_packages.build(
        tmp_path,
        Path(os.environ["E2E_PUBLISHER_KEY"]),
        app_id="hello",
        version="1.0.0",
        app={
            "name": "Hello",
            "publisher": "E2E Publisher",
            "summary": "Says hello to the operators.",
            "description": "A small test app for the browser journeys.",
        },
        permissions={"read": ["assets", "signals"], "write": ["audit"]},
    )
    page.goto("/apps")
    expect(page.get_by_role("heading", name="Apps", exact=True)).to_be_visible()
    expect(page.get_by_text("Installer running")).to_be_visible()
    page.get_by_label("App package file").set_input_files(str(package))
    preview = page.get_by_role("region", name=re.compile("Hello"))
    expect(preview.get_by_text("E2E Publisher")).to_be_visible()
    expect(preview.get_by_text("Says hello to the operators.")).to_be_visible()
    expect(preview.get_by_text("Never writes to the plant")).to_be_visible()
    expect(preview.get_by_text("Signature and SHA-256 checked")).to_be_visible()
    _shot(page, "apps-preview.png")
    preview.get_by_role("button", name="Install Hello").click()
    # The installed apps are a DataTable (@plantcraft/ui 0.13.0): the row naming the app.
    row = page.locator(".apps-installed tbody tr", has_text="Hello")
    expect(row).to_contain_text("1.0.0")
    expect(row).to_contain_text("Running", timeout=20_000)
    _shot(page, "apps-installed.png")


def test_unknown_address(page):
    page.goto("/loops")
    expect(page.get_by_text("This address does not exist")).to_be_visible()


def test_the_apps_open_from_the_name_and_the_menu_folds_from_the_corner(page):
    """@plantcraft/ui 0.28.0: the app's name at the top opens the apps (Desk first, PlantCraft
    last and current here); Help is in the person's menu; the person, the messages and the fold
    button share the bottom corner."""

    page.goto("/admin")
    sidebar = page.locator(".pcs-sidebar")
    # One Help for the suite, in the person's menu (ui 0.32.0), open at this app's guides.
    expect(sidebar.locator(".pcs-nav").get_by_role("link", name="Help")).to_have_count(0)
    sidebar.locator(".pcs-profile").click()
    help_link = page.get_by_role("menuitem", name="Help", exact=True)
    expect(help_link).to_have_attribute("href", "/help?app=processcraft")
    sidebar.locator(".pcs-profile").click()
    # Round 8 (owner, 2026-10-24/25): above the person the quick buttons, all alike, each opening
    # a panel (Messages, Notifications, Assistant, queues), then the fold button, last.
    expect(sidebar.locator(".pcs-sidebar-top .pcs-fold")).to_have_count(0)
    fold = sidebar.locator(".pcs-quick").get_by_role("button", name="Collapse the menu")
    expect(fold).to_be_visible()
    expect(sidebar.locator(".pcs-quick > :last-child")).to_have_attribute(
        "aria-label", "Collapse the menu"
    )
    order = sidebar.locator(".pcs-sidebar-bottom").locator(".pcs-quick-button, .pcs-profile")
    labels = [
        (order.nth(i).text_content() or "").strip() or order.nth(i).get_attribute("aria-label")
        for i in range(order.count())
    ]
    assert labels[:2] == ["Messages", "Notifications"] and "admin" in labels[-1].lower(), labels
    sizes = {
        (round(box["width"]), round(box["height"]))
        for box in (order.nth(i).bounding_box() for i in range(order.count() - 1))
    }
    assert len(sizes) == 1, sizes
    apps = sidebar.locator(".pcs-app-item")
    expect(apps).to_have_count(0)
    sidebar.get_by_role("button", name="Switch app").click()
    expect(apps.first).to_have_text("Desk")
    expect(apps.nth(1)).to_have_text("Analytics")
    # Apps installed by an earlier journey may follow Analytics; PlantCraft stays last, set apart.
    expect(apps.last).to_have_text("PlantCraft")
    expect(apps.last).to_have_attribute("aria-current", "page")
    expect(sidebar.locator(".pcs-switcher-pop hr + .pcs-app-item")).to_have_text("PlantCraft")
    # It floats over the page, as wide as its names: the sidebar never scrolls sideways.
    assert sidebar.evaluate("node => node.scrollWidth <= node.clientWidth")
    pop = sidebar.locator(".pcs-switcher-pop").bounding_box()
    brand = sidebar.get_by_role("button", name="Switch app").bounding_box()
    assert abs(pop["x"] - brand["x"]) <= 2 and pop["y"] >= brand["y"] + brand["height"], (
        pop,
        brand,
    )
    _shot(page, "sidebar-processcraft-expanded.png")
    page.keyboard.press("Escape")
    expect(apps).to_have_count(0)
    fold.click()
    expect(page.locator(".pcs-shell")).to_have_class(re.compile("pcs-collapsed"))
    # Folded, the fold button stays where it was clicked: the last of the quick buttons.
    expect(
        sidebar.locator(".pcs-quick").get_by_role("button", name="Expand the menu")
    ).to_be_visible()
    _shot(page, "sidebar-processcraft-collapsed.png")
    # The [ key folds and unfolds too.
    page.locator("main").click()
    page.keyboard.press("BracketLeft")
    expect(page.locator(".pcs-shell")).not_to_have_class(re.compile("pcs-collapsed"))
    # On a phone the sidebar is a drawer with its close button; the fold button is not drawn.
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Open menu").click()
    expect(sidebar.get_by_role("button", name="Close menu")).to_be_visible()
    expect(sidebar.locator(".pcs-fold")).to_be_hidden()
    sidebar.get_by_role("button", name="Switch app").click()
    expect(apps.first).to_be_visible()


def test_messages_open_over_the_page_and_close_back_to_it(page):
    # Messages and the Assistant cross every app; Messages opens over the page.
    page.goto("/assets")
    quick = page.locator(".pcs-quick")
    quick.get_by_role("link", name=re.compile(r"^Messages")).click()
    panel = page.get_by_role("dialog", name="Messages")
    expect(panel).to_be_visible()
    frame = page.frame_locator(".pc-messages-frame")
    expect(frame.get_by_role("heading", name="Messages", exact=True)).to_be_visible()
    # Only Messages inside: no sidebar of its own.
    expect(frame.locator(".pcs-sidebar")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"/assets$"))
    _shot(page, "messages-panel.png")
    # It comes out from the sidebar's edge, on the left (round 8).
    side = page.locator(".pcs-sidebar").bounding_box()
    box = panel.bounding_box()
    assert abs(box["x"] - (side["x"] + side["width"])) <= 2, (box, side)
    panel.get_by_role("button", name="Close").click()
    expect(panel).to_have_count(0)
    expect(page).to_have_url(re.compile(r"/assets$"))
    # Notifications have their own button and panel: Messages' notifications, no tabs.
    quick.get_by_role("link", name=re.compile(r"^Notifications")).click()
    notices = page.get_by_role("dialog", name="Notifications")
    expect(notices).to_be_visible()
    expect(frame.get_by_role("textbox", name="Search notifications")).to_be_visible()
    expect(frame.get_by_role("navigation", name="Messages")).to_be_hidden()
    expect(notices.get_by_role("link", name="Full page")).to_have_attribute(
        "href", "/messages/notifications"
    )
    # The same width as Messages' panel, and its button closes it again.
    assert abs(notices.bounding_box()["width"] - box["width"]) <= 2
    quick.get_by_role("link", name=re.compile(r"^Notifications")).click()
    expect(notices).to_have_count(0)
    # From one panel straight to another: the new one does not slide in.
    quick.get_by_role("link", name=re.compile(r"^Messages")).click()
    expect(panel).to_be_visible()
    quick.get_by_role("link", name=re.compile(r"^Notifications")).click()
    expect(notices).to_be_visible()
    queues = quick.locator(".pcs-queue-button")
    if queues.count():
        queues.click()
        queue_panel = page.get_by_role("dialog", name="Queues")
        expect(queue_panel).to_have_class(re.compile("pc-side-panel-still"))
        expect(notices).to_have_count(0)
        assert abs(queue_panel.bounding_box()["width"] - box["width"]) <= 2
        expect(queue_panel.get_by_role("link", name="Full page")).to_be_visible()
    # Going to another page closes the open panel.
    page.locator(".pcs-nav").get_by_role("link", name="Overview").click()
    expect(page).to_have_url(re.compile(r"/admin$"))
    expect(page.locator(".pc-side-panel")).to_have_count(0)
    page.goto("/assets")
    # The person's menu floats over the page beside the sidebar, wider than it.
    page.locator(".pcs-profile").click()
    menu = page.locator(".pcs-user-pop").bounding_box()
    assert menu["x"] >= side["x"] + side["width"] and menu["width"] > 300, (menu, side)
    page.keyboard.press("Escape")
    # Desk's menu no longer lists Messages; the full page stays.
    page.goto("/")
    desk_menu = page.locator(".pcs-nav")
    expect(desk_menu.get_by_role("link", name="Messages", exact=True)).to_have_count(0)
    page.goto("/messages")
    expect(page.get_by_role("heading", name="Messages", exact=True)).to_be_visible()
    # Two sections: the chats, and the notifications read like an email inbox.
    sections = page.get_by_role("navigation", name="Messages")
    sections.get_by_role("link", name=re.compile(r"^Notifications")).click()
    expect(page).to_have_url(re.compile(r"/messages/notifications$"))
    expect(page.get_by_role("button", name="Unread", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Your notifications")).to_be_visible()
    _shot(page, "messages-notifications.png")
    # The old inbox address opens them.
    page.goto("/inbox")
    expect(page).to_have_url(re.compile(r"/messages/notifications$"))
