"""A2.3: incremental reads. Rounds every --every minutes over a 24 h window ending in the past
(the bench data is still), cache vs no cache: identical frames, values read, time, Historian CPU.
    python incr.py --source plant --signals 150 --every 10 --rounds 6
"""
import argparse, json, os, time, warnings
from datetime import datetime, timedelta, timezone
warnings.filterwarnings("ignore")
ap = argparse.ArgumentParser()
ap.add_argument("--source", default="plant"); ap.add_argument("--signals", type=int, default=150)
ap.add_argument("--every", type=float, default=10); ap.add_argument("--rounds", type=int, default=6)
ap.add_argument("--hours", type=float, default=24); ap.add_argument("--url", default="http://127.0.0.1:8100/hist")
a = ap.parse_args()
import pandas as pd
from plantcraft_sdk.client import PlantCraftClient
from linkcraft.data.plant import PlantData
from cpu import proc_cpu, server_pid
token = open("/home/user/bench/token.txt").read().strip()
client = PlantCraftClient(a.url, token, historian_url=a.url, timeout=300)
names = sorted(s["id"] for s in client.signals() if s["id"].startswith(a.source + ":"))[: a.signals]
cached, plain = PlantData(client), PlantData(client, cache=False)
first_end = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None).floor("min") - pd.Timedelta(hours=1) - pd.Timedelta(minutes=a.every * a.rounds)
rows = []
for r in range(a.rounds + 1):
    end = first_end + pd.Timedelta(minutes=a.every * r); start = end - pd.Timedelta(hours=a.hours)
    out = {}
    for label, pdata in (("cache", cached), ("plain", plain)):
        c0 = proc_cpu(server_pid()); t0 = time.perf_counter()
        frame = pdata.read_range(start, end, 60, tags=names)
        out[label] = (frame, time.perf_counter() - t0, proc_cpu(server_pid()) - c0)
    pd.testing.assert_frame_equal(out["cache"][0], out["plain"][0], check_freq=False)
    rows.append({"round": r, "values": int(out["plain"][0].count().sum()),
                 "cache_s": round(out["cache"][1], 3), "plain_s": round(out["plain"][1], 3),
                 "cache_hist_cpu": round(out["cache"][2], 3), "plain_hist_cpu": round(out["plain"][2], 3)})
    print(json.dumps(rows[-1]), flush=True)
steady = rows[1:]
mean = lambda k: sum(x[k] for x in steady) / len(steady)
print(json.dumps({"source": a.source, "signals": len(names), "every_min": a.every, "identical": True,
    "cache_MB": round(cached.cache.nbytes() / 1e6, 1), "cache_values": cached.cache.values(),
    "steady_cache_s": round(mean("cache_s"), 3), "steady_plain_s": round(mean("plain_s"), 3),
    "steady_cache_hist_cpu": round(mean("cache_hist_cpu"), 3), "steady_plain_hist_cpu": round(mean("plain_hist_cpu"), 3)}))
