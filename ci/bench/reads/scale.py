"""A1.3: how a round's read grows with load. N rounds at once (separate processes, like N Analytics
rounds or apps), each PlantData.read_range of S signals x 24 h; variants:
  base   = JSON + pd.concat (0.5.1)    binary = binary answer + block frame
  incr   = binary + incremental cache, measured on the round after a warm one (10 min later)
    python scale.py --source plant --signals 200 --rounds 1 2 4 8 16 --variant base binary incr
"""

import argparse
import json
import multiprocessing as mp
import os
import time
import warnings

warnings.filterwarnings("ignore")


def one(args):
    source, signals, variant, url, barrier_at = args
    os.environ["PLANTCRAFT_BINARY_READS"] = "0" if variant == "base" else "1"
    from datetime import datetime, timezone

    import linkcraft.data.plant as plant_mod
    import pandas as pd
    from linkcraft.data.plant import PlantData

    from plantcraft_sdk.client import PlantCraftClient

    if variant == "base":
        plant_mod.wide_frame = lambda shaped: pd.concat(shaped, axis=1).sort_index()
    token = open("/home/user/bench/token.txt").read().strip()
    client = PlantCraftClient(url, token, historian_url=url, timeout=600)
    names = sorted(s["id"] for s in client.signals() if s["id"].startswith(source + ":"))[:signals]
    end = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None).floor("min") - pd.Timedelta(
        hours=1
    )
    pdata = PlantData(client, cache=(variant == "incr"))
    if variant == "incr":  # the warm round, 10 min before
        pdata.read_range(
            end - pd.Timedelta(hours=24, minutes=10), end - pd.Timedelta(minutes=10), 60, tags=names
        )
    warm_done = time.time()
    while time.time() < barrier_at:
        time.sleep(0.005)
    t0 = time.perf_counter()
    frame = pdata.read_range(end - pd.Timedelta(hours=24), end, 60, tags=names)
    return (
        time.perf_counter() - t0,
        int(frame.count().sum()),
        len(frame.attrs.get("failed_tags") or []),
        warm_done < barrier_at,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="plant")
    ap.add_argument("--signals", type=int, nargs="+", default=[200])
    ap.add_argument("--rounds", type=int, nargs="+", default=[1, 2, 4, 8, 16])
    ap.add_argument("--variant", nargs="+", default=["base", "binary", "incr"])
    ap.add_argument("--url", default="http://127.0.0.1:8100/hist")
    a = ap.parse_args()
    from cpu import proc_cpu, server_pid

    ctx = mp.get_context("spawn")
    for variant in a.variant:
        for signals in a.signals:
            for n in a.rounds:
                with ctx.Pool(n) as pool:
                    at = time.time() + 8 + (n * signals / 100 if variant == "incr" else 0) + n * 0.3
                    job = pool.map_async(one, [(a.source, signals, variant, a.url, at)] * n)
                    time.sleep(max(0, at - time.time()))
                    c0 = proc_cpu(server_pid())
                    res = job.get()
                    hist = proc_cpu(server_pid()) - c0
                times = sorted(r[0] for r in res)
                print(
                    json.dumps(
                        {
                            "variant": variant,
                            "source": a.source,
                            "signals": signals,
                            "rounds": n,
                            "values_each": res[0][1],
                            "failed_tags": sum(r[2] for r in res),
                            "warm_in_time": all(r[3] for r in res),
                            "p50_s": round(times[len(times) // 2], 2),
                            "max_s": round(times[-1], 2),
                            "historian_cpu_s_total": round(hist, 2),
                        }
                    ),
                    flush=True,
                )
