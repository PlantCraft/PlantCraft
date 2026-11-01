"""displayfit finds cut text and a page wider than the screen, and leaves alone what is cut on purpose."""

import os

import pytest

from plantcraft_sdk import displayfit

sync_api = pytest.importorskip("playwright.sync_api")

PAGE = """<!doctype html><html><body style="margin:0;font:16px sans-serif">
<div id="cut" style="height:20px;overflow:hidden"><p style="margin:0">one</p><p style="margin:0">two</p><p style="margin:0">three</p></div>
<div style="width:60px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">a long name shortened on purpose</div>
<div style="width:60px;overflow:hidden" data-clip-ok><span style="white-space:nowrap">cut on purpose, said so</span></div>
<div style="height:200px;overflow:auto"><div style="height:600px">a box that scrolls</div></div>
<span style="position:absolute;width:1px;height:1px;overflow:hidden">screen reader only</span>
<div style="height:16px;line-height:1;overflow:hidden;font-size:16px">tight line</div>
<button style="width:40px;white-space:nowrap">a button too narrow</button>
</body></html>"""


@pytest.fixture(scope="module")
def page():
    with sync_api.sync_playwright() as runner:
        try:
            browser = runner.chromium.launch(
                executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
            )
        except Exception as exc:  # No browser installed: nothing to drive.
            pytest.skip(f"Chromium unavailable: {exc}")
        opened = browser.new_page(viewport={"width": 800, "height": 600})
        yield opened
        browser.close()


def test_problems_names_cut_text_only(page):
    page.set_content(PAGE)
    found = displayfit.problems(page)
    assert found == [
        'cut text in div: "two"',
        'cut text in div: "three"',
        'text out of button: "a button too narrow"',
    ], found


def test_problems_names_text_drawn_over_text(page):
    page.set_content(
        '<body style="margin:0;font:16px sans-serif"><div style="height:10px">first title</div>'
        '<div style="margin-top:-12px">lies over it</div><p>apart</p>'
        '<details><summary>More</summary><div style="margin-top:-30px">closed, not drawn</div></details></body>'
    )
    assert displayfit.problems(page) == ['text over text: "lies over it" and "first title"']


def test_problems_names_a_page_wider_than_the_screen(page):
    page.set_content('<body style="margin:0"><div style="width:1200px">wide</div></body>')
    assert displayfit.problems(page) == ["wider than the screen: 1200px on 800px"]


def test_cases_cover_five_sizes_on_two_screens():
    assert len(displayfit.CASES) == 10
    assert displayfit.describe(1, {"width": 1366, "height": 768}) == "Larger text at 1366x768"
    with pytest.raises(ValueError):
        displayfit.set_size(None, 7)
