"""02.2: a View trend with mean, max and min lines of S signals over 24 h.
old = means + every raw sample summarised in the View (0.5.x); new = one grid read with each
cell's extremes from the Historian (``extremes``). Prints one JSON line per case."""

import argparse
import json
import time
import warnings
from datetime import timedelta

warnings.filterwarnings("ignore")

from cpu import proc_cpu, server_pid  # noqa: E402
from dashcraft.query.trends import summarise  # noqa: E402

from plantcraft_sdk.client import PlantCraftClient  # noqa: E402


def old(client, names, start, end, step):
    means = client.series_many(names, start, end, step)
    raw = client.series_many(names, start, end)
    out = {}
    for item in raw["series"]:
        out[item["signal"]] = (
            summarise(item["t"], item["v"], start, step, "max", end),
            summarise(item["t"], item["v"], start, step, "min", end),
        )
    return means, out, sum(len(i["t"]) for i in raw["series"])


def new(client, names, start, end, step):
    batch = client.series_many(names, start, end, step, extremes=True)
    return batch, {i["signal"]: (i.get("high"), i.get("low")) for i in batch["series"]}, 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="plant")
    ap.add_argument("--signals", type=int, nargs="+", default=[10, 50])
    ap.add_argument("--step", type=int, nargs="+", default=[300, 3600])
    ap.add_argument("--url", default="http://127.0.0.1:8100/hist")
    a = ap.parse_args()
    token = open("/home/user/bench/token.txt").read().strip()
    client = PlantCraftClient(a.url, token, historian_url=a.url, timeout=600)
    ids = sorted(s["id"] for s in client.signals() if s["id"].startswith(a.source + ":"))
    probe = client.value(ids[0], "last", "7d")
    import pandas as pd

    end = pd.Timestamp(probe["at"]).floor("h").to_pydatetime()
    start = end - timedelta(hours=24)
    for signals in a.signals:
        names = ids[:signals]
        for step in a.step:
            for name, fn in (("old", old), ("new", new)):
                fn(client, names, start, end, step)  # warm
                c0, t0 = proc_cpu(server_pid()), time.perf_counter()
                _, bands, raw_values = fn(client, names, start, end, step)
                wall, hist = time.perf_counter() - t0, proc_cpu(server_pid()) - c0
                print(
                    json.dumps(
                        {
                            "source": a.source,
                            "signals": signals,
                            "step": step,
                            "path": name,
                            "wall_s": round(wall, 3),
                            "historian_cpu_s": round(hist, 3),
                            "raw_values": raw_values,
                            "banded": sum(1 for h, lo in bands.values() if h),
                        }
                    ),
                    flush=True,
                )
