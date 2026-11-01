"""The page a demo visit waits on while the demo is updated (docs/public-demo.md, "Updating the
demo").

The demo sends its visits here when an announced update comes (``plantcraft demo update-notice``,
``PLANTCRAFT_PUBLIC_DEMO_UPDATING_URL``): the site does not restart with the demo, so the visitor
sees a page that says the demo is being updated, not an error that reads as a broken product.
The page asks ``/api/demo/ready`` every 10 s and offers the demo again once it answers with no
update under way (read from the demo's stats, ``SITE_DEMO_STATS_URL``).
"""

from __future__ import annotations

import threading
import time
from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

# The demo's answer is kept this long: a few visitors waiting do not each ask it.
READY_CACHE_SECONDS = 5.0

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>PlantCraft demo: updating</title>
<link rel="stylesheet" href="/demo-updating.css">
<script src="/demo-updating.js" defer></script>
</head>
<body>
<main data-demo="%%DEMO%%">
  <div class="spinner" aria-hidden="true"></div>
  <h1>The demo is being updated</h1>
  <p>We are installing a new version of PlantCraft's live demo. Nothing is broken: it will be back
  in a few minutes, and this page opens it again by itself.</p>
  <p class="status" role="status" aria-live="polite">Checking again in a few seconds…</p>
  <a class="button" href="%%DEMO%%" hidden>Enter the demo</a>
  <p class="small"><a href="/">Back to plantcraft.io</a></p>
</main>
</body>
</html>
"""

STYLE = """
:root { color-scheme: light dark; --bg: #f6f7f9; --card: #fff; --text: #1d2430; --muted: #5b6575;
  --accent: #1f6feb; --border: #dde2ea; }
@media (prefers-color-scheme: dark) { :root { --bg: #0f1318; --card: #171c23; --text: #e6e9ee;
  --muted: #9aa4b2; --accent: #5b9cff; --border: #2a313b; } }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px;
  background: var(--bg); color: var(--text); font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 460px; padding: 32px 28px; border: 1px solid var(--border); border-radius: 14px;
  background: var(--card); text-align: center; }
h1 { margin: 16px 0 8px; font-size: 22px; }
p { margin: 8px 0; color: var(--muted); }
.status { font-size: 14px; }
.small { margin-top: 18px; font-size: 14px; }
a { color: var(--accent); }
.button { display: inline-block; margin-top: 12px; padding: 10px 18px; border-radius: 999px;
  background: var(--accent); color: #fff; font-weight: 600; text-decoration: none; }
.spinner { width: 34px; height: 34px; margin: 0 auto; border: 3px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
"""

SCRIPT = """
(function () {
  var main = document.querySelector("main");
  var status = document.querySelector(".status");
  var enter = document.querySelector(".button");
  var spinner = document.querySelector(".spinner");
  function ask() {
    fetch("/api/demo/ready", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (answer) {
        if (answer.ready) {
          status.textContent = "The demo is back.";
          spinner.hidden = true;
          enter.hidden = false;
          window.setTimeout(function () { window.location.assign(main.dataset.demo); }, 1500);
        } else {
          status.textContent = "Still updating. Checking again in a few seconds…";
          window.setTimeout(ask, 10000);
        }
      })
      .catch(function () { window.setTimeout(ask, 10000); });
  }
  window.setTimeout(ask, 3000);
})();
"""


def install(app: FastAPI, *, demo_url: str, read_demo) -> None:
    """The page, its style and script, and ``GET /api/demo/ready``. ``read_demo(days)`` is the
    demo's stats (``DemoSource.read``): a dict when the demo answers, else why it does not."""

    page = PAGE.replace("%%DEMO%%", escape(demo_url, quote=True))
    lock = threading.Lock()
    cached: dict[str, float | bool] = {"at": 0.0, "ready": False}

    @app.get("/demo-updating")
    def updating_page() -> HTMLResponse:
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    @app.get("/demo-updating.css")
    def updating_style() -> Response:
        return Response(STYLE, media_type="text/css")

    @app.get("/demo-updating.js")
    def updating_script() -> Response:
        return Response(SCRIPT, media_type="text/javascript")

    @app.get("/api/demo/ready")
    def ready() -> dict[str, bool]:
        """Whether the demo answers with no update under way (nothing else about it)."""
        with lock:
            now = time.monotonic()
            if now - float(cached["at"]) >= READY_CACHE_SECONDS:
                answer = read_demo(1)
                up = isinstance(answer, dict) and not (answer.get("now") or {}).get("updating")
                cached.update(at=now, ready=bool(up))
            return {"ready": bool(cached["ready"])}
