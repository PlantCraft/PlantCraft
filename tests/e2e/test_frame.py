"""The suite's frame (round 8; ui frame.ts): PlantCraft keeps the sidebar and
an app runs beside it in an iframe, so switching apps never loads the page again.

No app server runs in these journeys: the iframe's requests under /link/ are answered by a small
stand-in app that speaks the frame's messages, as an app on ui 0.39.0 does through SuiteShell.
"""

from __future__ import annotations

import json
import re

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect  # noqa: E402

ICON = '<svg viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/><script>alert(1)</script></svg>'

STAND_IN = """<!doctype html><html><body><h1 id="h">Overview</h1>
<p><a id="out" href="/assets">Open the assets</a></p>
<script>
const base = "/link/";
const heading = (path) => (path === "/loops" ? "Loops" : "Overview");
function state() {
  const path = "/" + location.pathname.slice(base.length);
  document.getElementById("h").textContent = heading(path);
  parent.postMessage({ type: "pc-frame:state", state: {
    app: "linkcraft", base, home: "/", path, url: location.pathname + location.search,
    nav: [
      { to: "/", href: "/link/", label: "Overview", icon: %(icon)s, active: path === "/" },
      { to: "/loops", href: "/link/loops", label: "Loops", icon: "", active: path === "/loops" },
    ],
    heading: heading(path), tour: false, assistant: false, assistantOpen: false } }, location.origin);
}
addEventListener("message", (event) => {
  if (event.source !== parent || !event.data || event.data.type !== "pc-frame:go") return;
  history.pushState({}, "", base + event.data.to.replace(/^\\//, ""));
  state();
});
document.getElementById("out").addEventListener("click", (event) => {
  event.preventDefault();
  parent.postMessage({ type: "pc-frame:open", url: "/assets" }, location.origin);
});
parent.postMessage({ type: "pc-frame:ready" }, location.origin);
state();
</script></body></html>""" % {"icon": json.dumps(ICON).replace("</", "<\\/")}

OLD_APP = "<!doctype html><html><body><h1>An app on an older ui</h1></body></html>"


def _serve_app(page, html: str) -> None:
    """The iframe's requests under /link/ get the stand-in; the window's own go to PlantCraft."""

    def answer(route):
        frame = route.request.frame
        if frame.parent_frame is None:
            route.continue_()
        else:
            route.fulfill(status=200, content_type="text/html", body=html)

    page.route(re.compile(r".*/link/.*"), answer)


def test_switching_to_an_app_keeps_the_sidebar_and_loads_only_the_content(page):
    _serve_app(page, STAND_IN)
    page.goto("/admin")
    sidebar = page.locator(".pcs-sidebar")
    expect(sidebar.get_by_role("link", name="Assets")).to_be_visible()
    page.evaluate("window.__noReload = true")
    sidebar.get_by_role("button", name="Switch app").click()
    sidebar.locator(".pcs-app-item", has_text="Analytics").click()
    expect(page).to_have_url(re.compile(r"/link/$"))
    # The sidebar now lists the app's pages, drawn by PlantCraft; the app is the content.
    expect(sidebar.get_by_role("link", name="Loops")).to_be_visible()
    app = page.frame_locator("iframe[data-pc-frame]")
    expect(app.get_by_role("heading", name="Overview")).to_be_visible()
    assert page.evaluate("window.__noReload") is True
    # The app's icon is drawn cleaned: the shape stays, the script does not.
    icon = sidebar.get_by_role("link", name="Overview").locator(".pcs-frame-icon")
    expect(icon.locator("path")).to_have_count(1)
    expect(icon.locator("script")).to_have_count(0)
    # A page of the app from the sidebar: the app goes there, the address and the tab follow.
    sidebar.get_by_role("link", name="Loops").click()
    expect(app.get_by_role("heading", name="Loops")).to_be_visible()
    expect(page).to_have_url(re.compile(r"/link/loops$"))
    expect(sidebar.get_by_role("link", name="Loops")).to_have_attribute("aria-current", "page")
    expect(page).to_have_title(re.compile(r"^Loops · "))
    # A link out of the app opens PlantCraft's page in place.
    app.get_by_role("link", name="Open the assets").click()
    expect(page).to_have_url(re.compile(r"/assets$"))
    expect(page.locator(".pcs-content h1").first).to_be_visible()
    assert page.evaluate("window.__noReload") is True
    # The app stayed loaded behind PlantCraft's page: back to it, the same frame, where it was.
    frame = page.locator("iframe[data-pc-frame]")
    expect(frame).to_have_count(1)
    expect(frame).to_be_hidden()
    sidebar.get_by_role("button", name="Switch app").click()
    sidebar.locator(".pcs-app-item", has_text="Analytics").click()
    expect(frame).to_be_visible()
    expect(app.get_by_role("heading", name="Overview")).to_be_visible()
    assert page.evaluate("window.__noReload") is True
    # Messages opens over the app, from the same sidebar.
    page.locator(".pcs-quick").get_by_role("link", name=re.compile(r"^Messages")).click()
    expect(page.get_by_role("dialog", name="Messages")).to_be_visible()
    page.keyboard.press("Escape")


def test_an_app_address_opened_directly_is_drawn_in_the_frame(page):
    _serve_app(page, STAND_IN)
    page.goto("/link/loops")
    sidebar = page.locator(".pcs-sidebar")
    expect(sidebar.get_by_role("link", name="Loops")).to_have_attribute("aria-current", "page")
    expect(
        page.frame_locator("iframe[data-pc-frame]").get_by_role("heading", name="Loops")
    ).to_be_visible()


def test_an_app_that_does_not_speak_the_frame_opens_on_its_own_page(page):
    _serve_app(page, OLD_APP)
    page.goto("/admin")
    page.evaluate(
        "window.history.pushState({}, '', '/link/'); dispatchEvent(new PopStateEvent('popstate'))"
    )
    # Never its own sidebar beside PlantCraft's: hidden until ready, then its own page.
    expect(page.locator("iframe[data-pc-frame]")).to_be_hidden()
    expect(page).to_have_url(re.compile(r"/link/\?pc-frame=off$"), timeout=8000)
