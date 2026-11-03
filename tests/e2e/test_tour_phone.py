"""The guided tour on a phone: every step's Next can be tapped, and no page it opens is wider
than the screen. A page wider than a phone widens the browser's frame, and the tour's card used
to slide out of reach under the dimmed page (2026-11-01: the platform tour stopped on Apps)."""

from playwright.sync_api import expect

from plantcraft_sdk import e2e


def test_the_platform_tour_goes_to_the_end_on_a_phone(first_visit_phone):
    page = first_visit_phone
    page.goto("/")
    expect(
        page.get_by_role("dialog").get_by_role("heading", name="Welcome to PlantCraft")
    ).to_be_visible()
    assert e2e.walk_tour(page) > 10


def test_operations_has_its_own_short_tour_on_a_phone(first_visit_phone):
    """Operations opened Desk's tour (2026-11-03): it has a short one of its own."""

    page = first_visit_phone
    # The platform's tour was seen; Operations' opens by itself on its first visit.
    page.add_init_script("localStorage.setItem('plantcraft-ui:tour:processcraft', 'done')")
    page.goto("/health")
    expect(
        page.get_by_role("dialog").get_by_role("heading", name="Welcome to Operations")
    ).to_be_visible()
    steps = e2e.walk_tour(page)
    assert 3 <= steps <= 6
