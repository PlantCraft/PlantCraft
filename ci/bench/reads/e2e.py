"""End to end over HTTP: the SDK and Analytics' PlantData.read_range, as a round reads.

    python e2e.py --source plant --signals 200 --hours 24 --mode json|binary [--repeat 3]
Prints one JSON line: median seconds of read_range, values, frame shape.
"""
import argparse, json, os, statistics, time, warnings
from datetime import datetime, timedelta, timezone
warnings.filterwarnings("ignore")
ap = argparse.ArgumentParser()
ap.add_argument("--source", default="plant")
ap.add_argument("--signals", type=int, default=200)
ap.add_argument("--hours", type=float, default=24)
ap.add_argument("--mode", default="binary")
ap.add_argument("--repeat", type=int, default=3)
ap.add_argument("--url", default="http://127.0.0.1:8100/hist")
ap.add_argument("--reader", default="plant", help="plant (loops, 4 threads) or samples (Signal quality)")
a = ap.parse_args()
os.environ["PLANTCRAFT_BINARY_READS"] = "1" if a.mode == "binary" else "0"
from plantcraft_sdk.client import PlantCraftClient
from linkcraft.data.plant import PlantData
from linkcraft.data.samples import SignalReader
token = open("/home/user/bench/token.txt").read().strip()
client = PlantCraftClient(a.url, token, historian_url=a.url, timeout=300)
names = sorted(s["id"] for s in client.signals() if s["id"].startswith(a.source + ":"))[: a.signals]
end = datetime.now(timezone.utc).replace(microsecond=0)
start = end - timedelta(hours=a.hours)
times = []
for r in range(a.repeat + 1):
    t0 = time.perf_counter()
    if a.reader == "plant":
        frame = PlantData(client).read_range(start, end, 60, tags=names)
        shape, values = list(frame.shape), int(frame.count().sum())
    else:
        found = SignalReader(client).read(names, start, end)
        shape, values = [len(found.series)], sum(len(v) for v in found.series.values())
    if r:
        times.append(time.perf_counter() - t0)
print(json.dumps({"source": a.source, "signals": len(names), "hours": a.hours, "mode": a.mode,
    "reader": a.reader, "values": values, "shape": shape, "median_s": round(statistics.median(times), 3),
    "min_s": round(min(times), 3)}))
