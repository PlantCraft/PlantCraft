"""Notebooks end to end: a signal opened in a notebook runs in the browser, offline.

Needs JupyterLite built into ``notebooks/dist`` (``make notebooks``, about a minute online);
skipped otherwise. The kernel (Pyodide) takes up to a minute to start.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import pytest

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS")
LITE = Path(__file__).resolve().parents[2] / "notebooks" / "dist" / "lab" / "index.html"

pytestmark = pytest.mark.skipif(not LITE.exists(), reason="notebooks/dist missing: make notebooks")


def test_a_signal_opens_in_a_notebook_that_reads_it_offline(page):
    assert page.request.put("/api/notebooks/settings", data={"enabled": True}).ok
    listed = page.request.get("/api/v1/signals").json()
    signal = next(item["id"] for item in listed if item.get("kind") != "text")
    page.goto(f"/notebooks?signals={quote(signal)}&start=2000-01-01T00:00:00Z&end=now&origin=e2e")
    # The notebook PlantCraft wrote takes over the tab (the apps open this address in a new one).
    page.locator(".jp-Notebook").first.wait_for(timeout=120_000)
    assert re.search(r"/notebooks/lite/v/\w+/lab/", page.url)
    # The lab binds its commands once the kernel is up: run only then, or the click is lost.
    page.get_by_text(re.compile(r"Python \(Pyodide\) \| Idle")).wait_for(timeout=120_000)
    page.get_by_text("Run", exact=True).click()
    page.get_by_text("Run All Cells", exact=True).click()
    # pc.me(), then the table of the signal and its summary (``data.describe()``: a count row).
    # Every cell is drawn (windowingMode none, notebooks/build.py): wait for the last output.
    page.locator(".jp-OutputArea-output th", has_text="count").first.wait_for(timeout=240_000)
    assert page.locator(".jp-OutputArea-output img").count() >= 1  # the chart
    listed = page.request.get("/api/notebooks").json()["notebooks"]
    assert listed and listed[0]["path"].startswith("My notebooks/")
    # The banner of notebooks/lab/plantcraft-status.js is gone once Python is ready.
    page.locator("#plantcraft-python-starting").wait_for(state="detached", timeout=5_000)


def test_python_installs_once_in_the_browser_and_the_examples_are_a_folder(page):
    assert page.request.put("/api/notebooks/settings", data={"enabled": True}).ok
    page.goto("/notebooks")
    page.get_by_role("tab", name="Run in the browser", selected=True).wait_for()
    page.get_by_role("tab", name="Run on your computer").wait_for()
    install = page.get_by_role("button", name=re.compile(r"Install Python in this browser"))
    install.wait_for()
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / "notebooks-install.png"), full_page=True)
    started = time.monotonic()
    install.click()
    opener = page.get_by_role("link", name="Open JupyterLab")
    opener.wait_for(timeout=300_000)
    print(f"installed in {time.monotonic() - started:.1f} s")  # noqa: T201 - the measure
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / "notebooks-installed.png"), full_page=True)
    # Remembered: the next visit checks the browser's cache and offers JupyterLab at once.
    page.reload()
    opener.wait_for(timeout=30_000)
    with page.context.expect_page() as opened:
        opener.click()
    tab = opened.value
    tab.wait_for_url("**/notebooks/lite/v/**/lab/**", timeout=30_000)
    tab.locator(".jp-DirListing-item", has_text="Examples").wait_for(timeout=120_000)
    tab.locator(".jp-DirListing-item", has_text="My notebooks").wait_for()
    if SHOTS:
        tab.screenshot(path=str(Path(SHOTS) / "jupyterlab-folders.png"))
    tab.locator(".jp-DirListing-item", has_text="Examples").dblclick()
    # One folder per app: PlantCraft's own examples are in Examples/PlantCraft.
    tab.locator(".jp-DirListing-item", has_text="PlantCraft").dblclick()
    started = time.monotonic()
    tab.locator(".jp-DirListing-item", has_text="First steps").dblclick()
    tab.locator(".jp-Notebook").first.wait_for(timeout=120_000)
    # While the kernel starts, the page says so (notebooks/lab/plantcraft-status.js).
    tab.locator("#plantcraft-python-starting").wait_for(timeout=10_000)
    if SHOTS:
        tab.screenshot(path=str(Path(SHOTS) / "jupyterlab-starting.png"))
    tab.get_by_text(re.compile(r"Python \(Pyodide\) \| Idle")).wait_for(timeout=120_000)
    print(f"kernel ready in {time.monotonic() - started:.1f} s")  # noqa: T201 - the measure
    tab.locator("#plantcraft-python-starting").wait_for(state="detached", timeout=5_000)
