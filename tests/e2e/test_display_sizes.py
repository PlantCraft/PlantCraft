"""Every page of PlantCraft fits at the five display sizes, on a small laptop and a large screen.

The display size (user menu, docs/brand.md) scales the type and spacing tokens; a page written
once at the default has to hold at all five. ``plantcraft_sdk.displayfit`` reads each page as drawn
and names any text a box cuts, or a page wider than the screen.
"""

import os

import pytest

from plantcraft_sdk import displayfit

# Each area of the platform has its own menu: Desk, administration, settings.
AREAS = ("/", "/admin", "/setup")


@pytest.mark.slow  # 25 pages, 2 screens, 5 sizes: about two minutes
def test_every_page_fits_at_every_display_size(page, server):
    urls: list[str] = []
    for area in AREAS:
        for url in displayfit.menu_pages(page, server + area):
            if (
                url.split("?")[0]
                .removeprefix(server)
                .startswith(("/link", "/hist", "/dash", "/alarm", "/model", "/doc", "/login"))
            ):
                continue  # another app: its own journeys check it
            if url not in urls:
                urls.append(url)
    assert len(urls) > 10, urls
    displayfit.assert_fits(page, server, urls, os.environ.get("PLANTCRAFT_E2E_SCREENSHOTS"))
