"""What every app's browser journeys (``tests/e2e``) share, written once.

The fake PlantCraft runs in a forked uvicorn server; the app runs in a uvicorn thread with its
built interface, pointed at the fake like a real install points at PlantCraft; a headless
Chromium signs in with a token the fake signs, set as PlantCraft's cookie on the shared host.
An app's ``tests/e2e/conftest.py`` builds its runtime and uses these::

    with e2e.served(fake.app) as processcraft_url:      # the fake, over HTTP
        ...build the runtime on processcraft_url...
        with e2e.serving(create_app(runtime)) as url:  # the app, over HTTP
            yield url

Playwright, uvicorn and Chromium are test-only tools: journeys skip when one is missing, unless
``<APP>_E2E_REQUIRED=1`` (the CI ``e2e`` job), where that is a failure. Chromium comes from
``PLAYWRIGHT_CHROMIUM_EXECUTABLE`` when set, else from Playwright's own install.
"""

from __future__ import annotations

import multiprocessing
import os
import socket
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

# The suite's guided tour opens on a first visit and would cover the page; journeys switch it
# off (@plantcraft/ui reads this key), and the tour has a journey of its own.
TOURS_OFF = "try { localStorage.setItem('plantcraft-ui:tours-off', '1') } catch (error) {}"


def required(app_id: str) -> bool:
    return os.environ.get(f"{app_id.upper()}_E2E_REQUIRED") == "1"


def unavailable(app_id: str, reason: str) -> None:
    """Skip the journey, or fail it where journeys are required (CI)."""

    import pytest

    if required(app_id):
        pytest.fail(reason, pytrace=False)
    pytest.skip(reason)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve(app: Any, sock: socket.socket) -> None:
    import uvicorn

    uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False)).run(sockets=[sock])


@contextmanager
def served(app: Any, ready_path: str = "/api/v1/auth/keys") -> Iterator[str]:
    """Serve ``app`` (the fake PlantCraft) from a forked server on a free local port, so it
    keeps the same signing keys; yields its URL once ``ready_path`` answers."""

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(256)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = multiprocessing.get_context("fork").Process(
        target=_serve, args=(app, sock), daemon=True
    )
    server.start()
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                httpx.get(f"{url}{ready_path}", timeout=2)
                break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise RuntimeError("The fake PlantCraft did not start.") from None
                time.sleep(0.1)
        yield url
    finally:
        server.terminate()
        server.join(timeout=10)
        sock.close()


@contextmanager
def serving(app: Any, name: str = "The app") -> Iterator[str]:
    """Serve ``app`` (the app under test) in a uvicorn thread; yields its URL once started."""

    import uvicorn

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError(f"{name} did not start.")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@contextmanager
def chromium(app_id: str) -> Iterator[Any]:
    """A headless Chromium (Playwright), or a skip (a failure where journeys are required)."""

    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        unavailable(app_id, "Playwright is not installed: python -m pip install playwright")
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(executable_path=executable)
        except Error as error:
            unavailable(app_id, f"Chromium could not start: {str(error).splitlines()[0]}")
        yield instance
        instance.close()


@contextmanager
def page(
    browser: Any,
    cookies: Iterable[dict[str, Any]] = (),
    viewport: dict[str, int] | None = None,
) -> Iterator[Any]:
    """A fresh browser page with the tour off; fails the test on any JavaScript error."""

    context = browser.new_context(viewport=viewport or {"width": 1440, "height": 900})
    context.add_init_script(TOURS_OFF)
    if cookies:
        context.add_cookies(list(cookies))
    opened = context.new_page()
    errors: list[str] = []
    opened.on("pageerror", lambda error: errors.append(str(error)))
    try:
        yield opened
    finally:
        context.close()
    assert not errors, f"JavaScript errors on the page: {errors}"


def screenshots(app_id: str) -> Path | None:
    """Where journeys save screenshots: ``<APP>_E2E_SCREENSHOTS``, else nowhere."""

    folder = os.environ.get(f"{app_id.upper()}_E2E_SCREENSHOTS", "").strip()
    if not folder:
        return None
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    return path


def png(width: int = 24, height: int = 16, color: tuple[int, int, int] = (31, 111, 139)) -> bytes:
    """A small PNG of one colour, for journeys that give a block its picture (round 9 M2)."""

    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(color) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )
