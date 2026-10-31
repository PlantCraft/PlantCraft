"""Operations, built in like Desk: Status with each app's load, Logs with filters, Load alerts."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect

from plantcraft_sdk.server import logs

SHOTS = os.environ.get("PLANTCRAFT_E2E_SHOTS")


def _shot(page, name: str) -> None:
    """Screenshots for the pull request, only when asked (PLANTCRAFT_E2E_SHOTS=<folder>)."""

    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"{name}.png"), full_page=True)


@pytest.fixture(autouse=True)
def _log_file(tmp_path):
    """The JSON log file the platform's server writes in an installation (its __main__ sets it)."""

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    saved = dict(logs._configured)
    logs.configure_logging("processcraft", version="e2e", data_dir=tmp_path)
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)
    logs._configured.clear()
    logs._configured.update(saved)


def _metrics() -> None:
    """What the installer writes every 30 s, for a suite with one app above its warning level."""

    folder = Path(os.environ["PLANTCRAFT_INSTALLER_STATE"]) / "status"
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    def service(name, cpu, cpus, load, mem_mb, mem_pct):
        return {"service": name, "name": f"pc-{name}-1", "state": "running", "health": "healthy",
                "restarts": 0, "started_at": now, "cpu_pct": cpu, "cpus": cpus,
                "cpu_load_pct": load, "mem_bytes": mem_mb * 2**20, "mem_pct": mem_pct}  # fmt: skip

    (folder / "metrics.json").write_text(json.dumps({
        "at": now, "error": None,
        "host": {"cpus": 8, "cpu_pct": 61.0, "mem_pct": 70.2, "mem_total_bytes": 16 * 2**30,
                 "mem_used_bytes": 11 * 2**30, "load_1m": 4.9},
        "disk": {"total_bytes": 245 * 2**30, "free_bytes": 142 * 2**30, "free_pct": 58.0},
        "services": [
            service("processcraft", 136.0, 4.0, 34.0, 412, 41.0),
            service("histcraft", 104.0, 2.0, 52.0, 780, 38.0),
            service("linkcraft-executor", 344.0, 4.0, 86.0, 1290, 63.0),
            service("dashcraft", 18.0, 2.0, 9.0, 220, 22.0),
        ],
    }))  # fmt: skip


def test_operations_shows_the_load_the_logs_and_the_alert_levels(page, runtime):
    _metrics()
    logging.getLogger("plantcraft.e2e").warning("Historian read took 4.2 s for 214 signals")
    logging.getLogger("plantcraft.e2e").error("Historian read 504 after 30 s (request 7)")
    runtime.watch.tick()  # the watch's next look, without its 30 s
    page.goto("/admin")
    page.locator(".pcs-switcher .pcs-brand").click()
    page.locator(".pcs-switcher-pop").get_by_text("Operations", exact=True).click()
    expect(page).to_have_url(re.compile(r"/health$"))
    expect(page.get_by_role("heading", level=1, name="Status", exact=True)).to_be_visible()
    host = page.get_by_label("The machine")
    expect(host.get_by_text(re.compile(r"Machine CPU: 61 % · 8 CPUs"))).to_be_visible()
    row = page.get_by_role("row").filter(has_text="linkcraft-executor")
    expect(row.get_by_text("86 %", exact=True)).to_be_visible()
    expect(row.get_by_text("3.4 of 4 CPUs")).to_be_visible()
    expect(row.locator(".ops-load-warning")).to_have_count(1)
    _shot(page, "1-status")

    nav = page.locator("nav.pcs-nav")
    nav.get_by_role("link", name="Logs", exact=True).click()
    expect(page.get_by_role("heading", level=1, name="Logs", exact=True)).to_be_visible()
    expect(page.get_by_text("Historian read 504 after 30 s (request 7)")).to_be_visible()
    expect(page.get_by_text("Most frequent warnings and errors")).to_be_visible()
    page.get_by_label("Level").select_option("ERROR")
    page.get_by_role("button", name="Search", exact=True).click()
    expect(page.get_by_text("Historian read took 4.2 s for 214 signals")).to_have_count(0)
    _shot(page, "2-logs")
    page.get_by_text("Historian read 504 after 30 s (request 7)").first.click()
    expect(page.get_by_role("dialog")).to_contain_text("plantcraft.e2e")
    _shot(page, "3-log-record")
    page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()

    nav.get_by_role("link", name="Load alerts", exact=True).click()
    expect(page.get_by_role("heading", level=1, name="Load alerts", exact=True)).to_be_visible()
    page.get_by_label("CPU · Warning").fill("70")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Saved: the next check uses them.")).to_be_visible()
    _shot(page, "4-load-alerts")
    page.goto("/health")
    row = page.get_by_role("row").filter(has_text="histcraft")
    expect(row.locator(".ops-load-warning")).to_have_count(0)  # 52 % stays under 70 %
    page.goto("/ops/alerts")
    page.get_by_label("CPU · Warning").fill("80")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Saved: the next check uses them.")).to_be_visible()


def test_the_phone_reads_the_logs(browser, server):
    from tests.e2e.conftest import _open_page, _sign_in

    context, page, errors, _outside = _open_page(browser, server, "en-US")
    _sign_in(context)
    page.set_viewport_size({"width": 390, "height": 844})
    logging.getLogger("plantcraft.e2e").error("Models worker killed (exit 137)")
    page.goto("/ops/logs")
    expect(page.get_by_text("Models worker killed (exit 137)").first).to_be_visible()
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, f"the page scrolls sideways on a phone: {width}px"
    _shot(page, "5-logs-phone")
    context.close()
    assert not errors, errors
