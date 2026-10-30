"""Many people at once against PlantCraft in 1 and in N server processes (PLANTCRAFT_WORKERS).

    python ci/bench/workers_bench.py --clients 16 --seconds 20 --workers 1 4

Starts ``python -m plantcraft.api.serve`` on a fresh data folder for each worker count, with
2,000 assets, signs in once and runs ``--clients`` threads that each loop over the pages people
open (session, home, asset tree, one asset) with one write in ten (an asset renamed). Prints
requests per second and latency percentiles; the same machine for every count.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "bench-admin-secret"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start(folder: Path, workers: int) -> tuple[subprocess.Popen, str]:
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(folder / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    (folder / "scenario.json").write_text(json.dumps(scenario))
    (folder / "admin-password").write_text(PASSWORD)
    port = _free_port()
    env = {
        **os.environ,
        "PLANTCRAFT_SCENARIO": str(folder / "scenario.json"),
        "PLANTCRAFT_PREWARM_HISTORY": "false",
        "PLANTCRAFT_BASIC_AUTH_ENABLED": "true",
        "PLANTCRAFT_BASIC_AUTH_USERNAME": "admin",
        "PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE": str(folder / "admin-password"),
        "PLANTCRAFT_WORKERS": str(workers),
        "PLANTCRAFT_HOST": "127.0.0.1",
        "PLANTCRAFT_PORT": str(port),
        "PLANTCRAFT_LOG_LEVEL": "WARNING",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "plantcraft.api.serve"],
        cwd=folder,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/healthz", timeout=2).status_code == 200:
                return server, base
        except httpx.HTTPError:
            time.sleep(0.3)
    server.kill()
    raise SystemExit("the server did not start")


def _seed(base: str, cookies: dict[str, str], assets: int) -> None:
    with httpx.Client(base_url=base, cookies=cookies, timeout=60) as client:
        for index in range(assets):
            client.post(
                "/api/assets",
                json={"name": f"Pump {index}", "asset_id": f"P-{index}", "kind": "equipment"},
            ).raise_for_status()


def run(workers: int, clients: int, seconds: float, assets: int) -> dict[str, float]:
    folder = Path(tempfile.mkdtemp(prefix=f"workers-{workers}-"))
    server, base = _start(folder, workers)
    try:
        with httpx.Client(base_url=base, timeout=30) as client:
            client.post("/api/login", json={"username": "admin", "password": PASSWORD})
            cookies = dict(client.cookies)
        _seed(base, cookies, assets)
        latencies: list[float] = []
        errors = [0]
        lock = threading.Lock()
        end = time.time() + seconds

        def person(seed: int) -> None:
            rnd = random.Random(seed)
            mine: list[float] = []
            with httpx.Client(base_url=base, cookies=cookies, timeout=60) as client:
                while time.time() < end:
                    asset = f"P-{rnd.randrange(assets)}"
                    for method, path, body in (
                        ("GET", "/api/session", None),
                        ("GET", "/api/home", None),
                        ("GET", "/api/assets", None),
                        ("GET", f"/api/assets/{asset}", None),
                        *(
                            [
                                (
                                    "PATCH",
                                    f"/api/assets/{asset}",
                                    {"name": f"Pump {rnd.random():.4f}"},
                                )
                            ]
                            if rnd.random() < 0.1
                            else []
                        ),
                    ):
                        start = time.perf_counter()
                        answer = client.request(method, path, json=body)
                        mine.append(time.perf_counter() - start)
                        if answer.status_code >= 400:
                            with lock:
                                errors[0] += 1
            with lock:
                latencies.extend(mine)

        threads = [threading.Thread(target=person, args=(k,)) for k in range(clients)]
        started = time.time()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.time() - started
        latencies.sort()
        return {
            "workers": workers,
            "requests_per_second": round(len(latencies) / elapsed, 1),
            "p50_ms": round(latencies[len(latencies) // 2] * 1000, 1),
            "p95_ms": round(latencies[int(len(latencies) * 0.95)] * 1000, 1),
            "p99_ms": round(latencies[int(len(latencies) * 0.99)] * 1000, 1),
            "errors": errors[0],
            "requests": len(latencies),
        }
    finally:
        server.terminate()
        server.wait(30)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clients", type=int, default=16)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--assets", type=int, default=2000)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 4])
    args = parser.parse_args()
    print(f"CPUs: {os.cpu_count()}, clients: {args.clients}, {args.seconds:.0f} s each")
    for workers in args.workers:
        print(json.dumps(run(workers, args.clients, args.seconds, args.assets)), flush=True)


if __name__ == "__main__":
    main()
