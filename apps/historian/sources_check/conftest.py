"""The source checks (``make sources-check``): Historian reads the Simulator's test kit.

Each check starts a server of the kit (``simcraft.testkit``), points a Historian source at
it and compares what Historian archives or reads with what the kit published. Gateway kinds
(MQTT, Modbus, SQL) run the suite's pinned Telegraf (``sources_check/telegraf.py``), required when
``HISTCRAFT_SOURCES_STRICT`` is set; SQL needs a PostgreSQL: ``HISTCRAFT_SOURCES_PG`` (a DSN) or a
local ``initdb`` started for the run, else it is skipped.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("simcraft.testkit", reason="pip install -e ../../simulator[testkit]")

from simcraft.testkit import plant  # noqa: E402

from histcraft.archive.store import ArchiveStore  # noqa: E402
from histcraft.catalog.models import PointIn, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.service import Collector, CollectorThread  # noqa: E402
from tests.conftest import database, make_settings  # noqa: E402

LOCAL = "127.0.0.1,localhost"


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    """Every server of the kit is local: no request goes through a proxy."""

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", LOCAL)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def series() -> dict[str, plant.Series]:
    return plant.history(minutes=30)


def wait(check: Callable[[], Any], timeout: float = 30.0, what: Any = "") -> Any:
    """``check()`` once it is truthy; ``what`` (text, or a function giving it) names a timeout."""

    deadline = time.monotonic() + timeout
    while True:
        found = check()
        if found:
            return found
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what() if callable(what) else what}")
        time.sleep(0.2)


class Historian:
    """A Historian collector on ``tmp_path`` (catalog, archive, collector thread, gateway port)."""

    def __init__(self, tmp_path: Path):
        port = free_port()
        self.settings = make_settings(
            tmp_path,
            ingest_port=port,
            ingest_url=f"http://127.0.0.1:{port}",
            # The gateway's disk buffer (store and forward) where this Telegraf can write it.
            gateway_buffer_dir=str(tmp_path / "gateway-buffer"),
        )
        self.catalog = CatalogStore(database(tmp_path, "config"))
        self.archive = ArchiveStore(database(tmp_path))
        self.thread = CollectorThread(Collector(self.settings, self.catalog, self.archive))
        self.data_dir = tmp_path
        self.gateway: subprocess.Popen[bytes] | None = None

    def add(self, source: SourceIn, points: list[PointIn]) -> None:
        self.catalog.save_source(source, create=True)
        if points:
            self.catalog.add_points(points)

    def point(self, signal: str) -> int:
        return int(self.catalog.point(signal)["id"])

    def archived(self, signal: str) -> tuple[np.ndarray, Any]:
        return self.archive.read(self.point(signal), 0, 2**62)

    def snapshot(self, signal: str) -> Any:
        point = self.point(signal)
        return (self.archive.snapshots([point]).get(point) or {}).get("value")

    def status(self, source_id: str) -> dict[str, Any]:
        return dict(self.thread.collector.source_status.get(source_id) or {})

    def start_gateway(self, telegraf: Path) -> None:
        config = self.data_dir / "gateway" / "telegraf.conf"
        wait(
            lambda: config.exists() and "[[inputs." in config.read_text().split("internal")[-1],
            what="the gateway configuration",
        )
        env = {key: value for key, value in os.environ.items() if "proxy" not in key.lower()}
        log = (self.data_dir / "telegraf.log").open("wb")
        self.gateway = subprocess.Popen(
            [str(telegraf), "--config", str(config), "--watch-config", "poll"],
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**env, "NO_PROXY": LOCAL},
        )

    def gateway_log(self) -> str:
        path = self.data_dir / "telegraf.log"
        return path.read_text(errors="replace") if path.exists() else ""

    def close(self) -> None:
        if self.gateway is not None:
            self.gateway.terminate()
            try:
                self.gateway.wait(10)
            except subprocess.TimeoutExpired:
                self.gateway.kill()
        self.thread.stop()


@pytest.fixture
def historian(tmp_path) -> Iterator[Historian]:
    found = Historian(tmp_path)
    yield found
    found.close()


@pytest.fixture(scope="session")
def telegraf() -> Path:
    from sources_check.telegraf import binary

    try:
        return binary()
    except Exception as exc:  # noqa: BLE001 - offline: say so
        if os.environ.get("HISTCRAFT_SOURCES_STRICT"):
            raise
        pytest.skip(f"no Telegraf ({exc}); set HISTCRAFT_TELEGRAF")


@pytest.fixture(scope="session")
def postgres(tmp_path_factory) -> Iterator[str]:
    """A PostgreSQL DSN: ``HISTCRAFT_SOURCES_PG``, or a server started from ``initdb``."""

    given = os.environ.get("HISTCRAFT_SOURCES_PG")
    if given:
        yield given
        return
    initdb = shutil.which("initdb") or next(
        (str(path) for path in sorted(Path("/usr/lib/postgresql").glob("*/bin/initdb"))), None
    )
    if initdb is None or os.geteuid() == 0:  # initdb refuses to run as root
        pytest.skip("no PostgreSQL: set HISTCRAFT_SOURCES_PG (initdb missing or run as root)")
    bin_dir = Path(initdb).parent
    folder = tmp_path_factory.mktemp("pg")
    port = free_port()
    run = {"check": True, "capture_output": True}
    subprocess.run([initdb, "-D", str(folder / "data"), "-U", "kit", "--auth=trust"], **run)
    subprocess.run(
        [
            str(bin_dir / "pg_ctl"),
            "-D",
            str(folder / "data"),
            "-o",
            f"-p {port} -k {folder} -c listen_addresses=127.0.0.1",
            "-l",
            str(folder / "log"),
            "-w",
            "start",
        ],
        **run,
    )
    subprocess.run(
        [str(bin_dir / "createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", "kit", "kit"], **run
    )
    try:
        yield f"postgres://kit@127.0.0.1:{port}/kit?sslmode=disable"
    finally:
        subprocess.run(
            [str(bin_dir / "pg_ctl"), "-D", str(folder / "data"), "-m", "fast", "stop"], **run
        )


def rebuilt(times: np.ndarray, values: Any, at: list[int], step: bool) -> list[float]:
    """The archived series at ``at``: the value before (step) or linear between neighbours."""

    stamps = np.asarray(times, dtype=np.int64)
    numbers = np.asarray(values, dtype=float)
    if step:
        index = np.searchsorted(stamps, at, side="right") - 1
        return [float(numbers[i]) for i in index]
    return [float(value) for value in np.interp(at, stamps, numbers)]
