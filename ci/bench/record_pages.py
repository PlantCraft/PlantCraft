#!/usr/bin/env python3
"""Records what each screen of the suite asks the server for, for ``load_users.py`` (never in CI).

::

    python3 ci/bench/record_pages.py --url https://vm/ --user demo --password plantcraft-demo

A browser signs in (the public demo's visitor by default), opens each start screen
(``START`` below) and, from each, the screens its links lead to (one example of each kind of
address: ``/dash/dashboards/<id>`` once per dashboard up to ``--per-kind``), waits until the
network is quiet and writes ``ci/bench/load_pages.json``: for each screen, the calls it made.
A call is a path (a GET) or ``{"method": "POST", "path", "body"}`` for the reads sent as a
POST (a trend's data, a batch of series). Times in a call are kept relative to the recording,
``{now-3600}`` for an hour ago, so a replay reads the same span ending at its own now.
Streams, writes and other hosts are left out. Needs ``playwright`` (``pip install
'.[e2e]'``); ``--chromium`` names a Chromium binary when Playwright's own is not installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

OUT = Path(__file__).resolve().parent / "load_pages.json"
# The screens a visitor opens first: the platform's, then each app's main ones.
START = [
    "/",
    "/attention",
    "/assets",
    "/assets/FIC-1003",
    "/actions",
    "/messages",
    "/calendar",
    "/link/",
    "/link/loops/FIC-1003",
    "/link/results",
    "/hist/",
    "/hist/points",
    "/dash/dashboards",
    "/dash/trends",
    "/dash/reports",
    "/alarm/alarms",
    "/alarm/events",
    "/model/",
    "/model/studies",
    "/doc/documents",
]
# POSTs that only read: a trend's lines, a batch of series, a picker's options, a search.
READ_POSTS = re.compile(r"/(data|series|resolve|variable-options|search|options)$")
# Never replayed: streams and the sign-in itself.
SKIP = re.compile(r"/(stream|events/stream|login|logout|sse)(\?|$)")
# A time in a call, plain or as a query string writes it (``%3A`` for ``:``).
ISO = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}(:|%3A)\d{2}((:|%3A)\d{2}(\.\d+)?)?(Z|[+-]\d{2}(:|%3A)?\d{2})?"
)
# Ids in addresses, so one example of each kind of screen is opened.
ID_PART = re.compile(r"/[^/]*[\d%][^/]*(?=/|$)")


def log(message: str) -> None:
    print(f"[record] {message}", flush=True)


def relative(text: str, now: datetime) -> str:
    """Absolute times in a call as ``{now-<seconds>}``, so a replay reads the same span."""

    def swap(match: re.Match) -> str:
        raw = match.group(0)
        try:
            moment = datetime.fromisoformat(raw.replace("%3A", ":").replace("Z", "+00:00"))
        except ValueError:
            return raw
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return f"{{now-{max(0, round((now - moment).total_seconds()))}}}"

    return ISO.sub(swap, text)


def kind_of(path: str) -> str:
    return ID_PART.sub("/<id>", path.split("?")[0].rstrip("/") or "/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="the suite's address")
    parser.add_argument("--user", default="demo")
    parser.add_argument("--password", default="plantcraft-demo")
    parser.add_argument("--per-kind", type=int, default=3, help="screens of one kind at most")
    parser.add_argument("--chromium", help="a Chromium binary")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("playwright is not installed: pip install '.[e2e]'")
        return 2

    base = args.url.rstrip("/")
    host = urlsplit(base).netloc
    pages: dict[str, list] = {}
    seen_kinds: dict[str, int] = {}
    with sync_playwright() as playwright:
        options: dict = {"args": ["--no-proxy-server"]}
        if args.chromium:
            options["executable_path"] = args.chromium
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            ignore_https_errors=True, viewport={"width": 1440, "height": 1000}, locale="en-US"
        )
        answer = context.request.post(
            base + "/api/login", data={"username": args.user, "password": args.password}
        )
        if not answer.ok:
            log(f"sign-in refused: {answer.status}")
            return 1
        # Tours off: a visitor's first screens would otherwise wait on the tour.
        context.add_init_script(
            "try { localStorage.setItem('plantcraft-ui:tours-off', '1') } catch (e) {}"
        )
        page = context.new_page()
        page.set_default_timeout(30_000)
        calls: list = []

        def requested(request) -> None:
            split = urlsplit(request.url)
            if split.netloc != host or request.resource_type not in {"fetch", "xhr"}:
                return
            path = split.path + (f"?{split.query}" if split.query else "")
            if SKIP.search(split.path) or "/api/" not in split.path:
                return
            now = datetime.now(timezone.utc)
            if request.method == "GET":
                calls.append(relative(path, now))
            elif request.method == "POST" and READ_POSTS.search(split.path):
                body = request.post_data or ""
                calls.append(
                    {
                        "method": "POST",
                        "path": relative(path, now),
                        "body": json.loads(relative(body, now)) if body else None,
                    }
                )

        page.on("request", requested)
        queue = list(START)
        done: set[str] = set()
        while queue:
            path = queue.pop(0)
            kind = kind_of(path)
            if path in done or seen_kinds.get(kind, 0) >= args.per_kind:
                continue
            done.add(path)
            seen_kinds[kind] = seen_kinds.get(kind, 0) + 1
            calls.clear()
            began = time.perf_counter()
            try:
                page.goto(base + path)
                page.wait_for_load_state("networkidle", timeout=30_000)
                page.wait_for_timeout(1500)  # panels that ask after the first answers
                page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception as exc:  # noqa: BLE001 - a slow screen is recorded as far as it got
                log(f"{path}: {type(exc).__name__}")
            unique = []
            for call in calls:
                if call not in unique:
                    unique.append(call)
            if unique:
                pages[path] = unique
            log(f"{path}: {len(unique)} calls in {time.perf_counter() - began:.1f} s")
            if path not in START:
                continue
            # The screens this one leads to, in the platform and inside the app's frame.
            for frame in page.frames:
                try:
                    hrefs = frame.eval_on_selector_all(
                        "a[href]", "els => els.map(e => e.getAttribute('href'))"
                    )
                except Exception:  # noqa: BLE001 - a frame that went away
                    continue
                prefix = "/" + path.strip("/").split("/")[0] if frame != page.main_frame else ""
                for href in hrefs:
                    if not href or href.startswith(("http", "#", "mailto:")) or "/api/" in href:
                        continue
                    target = href if href.startswith("/") else f"{prefix}/{href}"
                    if frame != page.main_frame and not target.startswith(prefix + "/"):
                        target = prefix + target
                    target = target.split("#")[0]
                    if target.endswith("/new") or "/api/" in target:
                        continue
                    if target not in done and target not in queue:
                        queue.append(target)
        browser.close()

    args.out.write_text(json.dumps(pages, indent=1) + "\n")
    calls_total = sum(len(calls) for calls in pages.values())
    log(f"{len(pages)} screens, {calls_total} calls: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
