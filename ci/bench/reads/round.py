"""A1.1: one real "Control loop performance" round (Analytics MonitorService.run_once) over the
bench Historian, timed by phase: reads (PlantData.read_range) vs the rest (tasks, algorithms in
the compute pool, saving).   python round.py --source demo200 --loops 50 --mode binary
"""
import argparse, json, logging, os, statistics, tempfile, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ap = argparse.ArgumentParser()
ap.add_argument("--source", default="demo200")
ap.add_argument("--loops", type=int, default=50)
ap.add_argument("--mode", default="binary")
ap.add_argument("--repeat", type=int, default=2)
ap.add_argument("--window", type=int, default=1440)
ap.add_argument("--processes", type=int, default=None)
ap.add_argument("--url", default="http://127.0.0.1:8100/hist")
ap.add_argument("--frame", default="block", help="block (new) or concat (0.5.1)")
def main():
    a = ap.parse_args()
    os.environ["PLANTCRAFT_BINARY_READS"] = "1" if a.mode == "binary" else "0"
    logging.basicConfig(level=logging.ERROR)
    from plantcraft_sdk.client import PlantCraftClient
    from linkcraft.config import AnalysisConfig, LoopConfig, LoopSignals
    from linkcraft.data.plant import PlantData
    from linkcraft.db import Database
    from linkcraft.engine.compute import ComputePool
    from linkcraft.loops import monitor as mon
    import linkcraft.data.plant as plant_mod
    from cpu import proc_cpu, server_pid, pg_cpu
    if a.frame == "concat":
        plant_mod.wide_frame = lambda shaped: plant_mod.pd.concat(shaped, axis=1).sort_index()

    token = open("/home/user/bench/token.txt").read().strip()
    client = PlantCraftClient(a.url, token, historian_url=a.url, timeout=300)
    ids = sorted(s["id"] for s in client.signals() if s["id"].startswith(a.source + ":"))
    pv = [i for i in ids if i.endswith(".PV")]; op = [i for i in ids if i.endswith(".OP")]; sp = [i for i in ids if i.endswith(".SP")]
    loops = [LoopConfig(loop_id=f"l{n:04d}", name=f"Loop {n}", signals=LoopSignals(pv=pv[n % len(pv)],
             op=op[n % len(op)], sp=sp[n % len(sp)])) for n in range(a.loops)]
    tmp = Path(tempfile.mkdtemp())
    plant = PlantData(client)
    service = mon.MonitorService(Database(tmp / "link.sqlite3"), plant, analysis=AnalysisConfig(window_minutes=a.window),
                                 compute=ComputePool(a.processes))
    service.loop_store.sync_from_assets(loops)
    spent = {"read": 0.0}
    orig = service._read
    def timed_read(*args, **kw):
        t0 = time.perf_counter(); out = orig(*args, **kw); spent["read"] += time.perf_counter() - t0; return out
    service._read = timed_read
    rows = []
    for r in range(a.repeat + 1):
        spent["read"] = 0.0
        c0, p0 = proc_cpu(server_pid()), pg_cpu()
        t0 = time.perf_counter(); snap = service.run_once(); total = time.perf_counter() - t0
        if r:
            rows.append({"total": total, "read": spent["read"], "hist_cpu": proc_cpu(server_pid()) - c0,
                         "pg_cpu": pg_cpu() - p0})
        if snap.get("status") != "ok":
            print("round status", snap.get("status"), snap.get("error")); break
    service.compute.shutdown()
    signals = len({s for l in loops for s in (l.signals.pv, l.signals.op, l.signals.sp)})
    out = {"source": a.source, "loops": a.loops, "signals": signals, "window_min": a.window, "mode": a.mode,
           "processes": service.compute.processes,
           "round_s": round(statistics.median(x["total"] for x in rows), 2),
           "read_s": round(statistics.median(x["read"] for x in rows), 2)}
    out["rest_s"] = round(out["round_s"] - out["read_s"], 2)
    out["frame"] = a.frame
    out["historian_cpu_s"] = round(statistics.median(x["hist_cpu"] for x in rows), 2)
    out["postgres_cpu_s"] = round(statistics.median(x["pg_cpu"] for x in rows), 2)
    print(json.dumps(out))

if __name__ == "__main__":
    main()
