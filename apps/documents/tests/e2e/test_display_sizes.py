"""Every page of the app's menu fits at the five display sizes, on a small laptop and a large screen.

The display size (user menu, PlantCraft docs/brand.md) scales the type and spacing tokens; a page
written once at the default has to hold at all five. ``plantcraft_sdk.displayfit`` reads each page
as drawn and names any text a box cuts, or a page wider than the screen.
"""

import pytest
from plantcraft_sdk import displayfit


@pytest.mark.slow  # every page, 2 screens, 5 sizes
def test_every_page_fits_at_every_display_size(signed_in, app_url, screenshots):
    displayfit.assert_fits(signed_in, app_url, screenshots=screenshots)
