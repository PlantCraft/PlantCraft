"""Analytics on the Tennessee Eastman process over three years (A22): scale and diagnosis.

The dataset is Souza, de Souza and Silva (2023), "New TEP datasets": three years of continuous
operation simulated with the Braatz group's Fortran code (Downs and Vogel 1993), 525,600
samples every 3 minutes of 52 signals (41 measurements, 11 manipulated variables), with faults
1 to 20 at random times and durations between periods of normal operation (``STATUS``).
https://github.com/anasouzac/new_tep_datasets. The repository declares no license, so the file
is downloaded to a cache when this runs and never kept in PlantCraft's repository.

What it measures, through Analytics' own code:

1. **Scale.** The 52 signals are an asset of an in-memory plant (``MemoryPlant``: the asset and
   ``series_many_pandas``, as Analytics reads PlantCraft, without the network or the Historian,
   so the numbers are Analytics' own). Calibrate runs on the longest stretch of normal
   operation (timed). The empirical model block (``model.empirical``, M4) then runs every 8 hours
   over the three years (``runs_over``: one read, the blocks' memory carried), as a replay of
   the past does: time per run, runs per second, peak memory of the process.
2. **Diagnosis.** The model is fitted (``fit_pca``, as Calibrate does) on the settled normal
   operation of the first year and judged on the second and third years only. Per fault: the share of its samples beyond the T² or SPE limit (detection
   rate) and the time from its start to the first such sample; on normal operation more than
   20 hours after a fault (the plant settled), the share beyond (false alarms); per 8-hour run,
   the verdict against whether a fault was active.

    python ci/bench/tep/tep.py [--cache ~/.cache/plantcraft-bench/tep] [--every-hours 8]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from linkcraft.assets.calibrate import calibrate_on_asset
from linkcraft.assets.run import AssetTiming, runs_over, segment_ends
from linkcraft.models.pca import PcaModel, fit_pca, judge_pca

URL = "https://media.githubusercontent.com/media/anasouzac/new_tep_datasets/main/python_data_3years.csv"
SHA256 = "53fd62f32b541d6aaac821dc65e1e76d1bd99ce2dffbff4a1f41bd595a7bafc6"
SIZE = 516_660_037
START = pd.Timestamp("2023-01-01", tz="UTC")
STEP = 180.0
ASSET = "tep"
SETTLED_SAMPLES = 400  # 20 hours after a fault ends


def download(cache: Path) -> Path:
    path = cache / "python_data_3years.csv"
    if path.exists() and path.stat().st_size == SIZE:
        return path
    cache.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    with urllib.request.urlopen(URL, timeout=900) as answer, partial.open("wb") as out:
        while chunk := answer.read(1 << 20):
            out.write(chunk)
    digest = hashlib.sha256(partial.read_bytes()).hexdigest()
    if digest != SHA256:
        partial.unlink()
        raise SystemExit(f"The download does not match its checksum ({digest}).")
    partial.rename(path)
    return path


def load(path: Path) -> tuple[pd.DataFrame, np.ndarray]:
    raw = pd.read_csv(path, sep=";")
    status = raw.pop("STATUS").to_numpy(int)
    raw = raw.drop(columns=raw.columns[0])
    raw.index = START + pd.to_timedelta(np.arange(len(raw)) * STEP, unit="s")
    return raw.astype(float), status


class MemoryPlant:
    """PlantCraft as Analytics reads it (an asset, ``series_many_pandas``), in memory."""

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.ids = {name: f"tep:{name}" for name in frame.columns}
        self.columns = {self.ids[name]: frame[name] for name in frame.columns}

    def asset(self, asset_id: str) -> dict:
        return {"id": asset_id, "name": "Tennessee Eastman", "kind": "unit", "signals": {}}

    def series_many_pandas(self, names, start, end, step):
        begin, finish = pd.Timestamp(start), pd.Timestamp(end)
        return {name: self.columns[name].loc[begin:finish] for name in names}, []


def diagram(plant: MemoryPlant, calibration: dict | None = None) -> dict:
    nodes = [
        {"id": f"s{index}", "block": "input.signal", "parameters": {"signal": signal}}
        for index, signal in enumerate(plant.ids.values())
    ]
    nodes += [
        {
            "id": "pca",
            "block": "model.empirical",
            "parameters": {"calibration": calibration, "persistence": 1, "share": 0.2},
        },
        {"id": "out", "block": "output.result", "parameters": {"name": "Empirical model"}},
    ]
    edges = [
        {"source": f"s{index}", "source_port": "value", "target": "pca", "target_port": "signals"}
        for index in range(len(plant.ids))
    ]
    edges.append({"source": "pca", "source_port": "result", "target": "out", "target_port": "in"})
    return {"nodes": nodes, "edges": edges}


def since_fault(status: np.ndarray) -> np.ndarray:
    found = np.empty(len(status))
    count = 1e9
    for index, value in enumerate(status):
        count = 0 if value else count + 1
        found[index] = count
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cache", default=str(Path.home() / ".cache/plantcraft-bench/tep"))
    parser.add_argument("--every-hours", type=float, default=8.0)
    parser.add_argument("--calibration-days", type=float, default=30.0)
    parser.add_argument("--confidence", type=float, default=0.99)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    began = time.perf_counter()
    path = download(Path(args.cache).expanduser())
    frame, status = load(path)
    loaded = time.perf_counter() - began
    plant = MemoryPlant(frame)
    print(f"Loaded {frame.shape[0]:,} samples x {frame.shape[1]} signals in {loaded:.1f} s")

    # Calibrate on the first stretch of normal operation that lasts the calibration days.
    days = args.calibration_days
    normal = pd.Series(status == 0, index=frame.index)
    run_id = (normal != normal.shift()).cumsum()
    stretches = normal.groupby(run_id).agg(["first", "size"])
    longest = stretches[stretches["first"]].sort_values("size", ascending=False).index[0]
    first = normal[run_id == longest].index
    cal_start = first[0] + pd.Timedelta(hours=20)  # settled after any fault before it
    cal_end = min(cal_start + pd.Timedelta(days=days), first[-1])
    timing = AssetTiming(
        cycle_seconds=args.every_hours * 3600,
        window_seconds=args.every_hours * 3600,
        step_seconds=STEP,
    )
    tic = time.perf_counter()
    found = calibrate_on_asset(
        diagram(plant), "pca", ASSET, client=plant, start=cal_start, end=cal_end, timing=timing
    )
    calibrated = time.perf_counter() - tic
    stretch = PcaModel.from_dict(found["calibration"])
    print(
        f"Calibrate on the longest normal stretch: {stretch.samples:,} samples "
        f"({cal_start:%Y-%m-%d} to {cal_end:%Y-%m-%d}) in {calibrated:.2f} s"
    )
    # The model the diagnosis uses: the settled normal operation of the first year.
    first_year = frame.index < frame.index[0] + pd.Timedelta(days=365)
    settled = (status == 0) & (since_fault(status) > SETTLED_SAMPLES)
    tic = time.perf_counter()
    model = fit_pca(frame[first_year & settled].to_numpy(), list(plant.ids.values()))
    fitted = time.perf_counter() - tic
    calibration = {**model.as_dict(), "outputs": model.signals}
    print(
        f"Fitted on the first year's settled normal operation: {model.samples:,} samples in "
        f"{fitted:.2f} s, {model.components} components, {model.explained:.1%} of the variance"
    )

    # Scale: the algorithm every N hours over the three years, one read, memory carried.
    ends = segment_ends(frame.index[0], frame.index[-1], timing.window_seconds)
    tic = time.perf_counter()
    # Only each run's verdict is kept, as the scheduler keeps a subject's latest run, not all.
    runs = [
        run["summary"]["verdict"]["status"]
        for run in runs_over(
            diagram(plant, calibration),
            ASSET,
            client=plant,
            ends=ends,
            window=timing.window_seconds,
            step=STEP,
        )
    ]
    replay = time.perf_counter() - tic
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # kB on Linux
    print(
        f"{len(runs):,} runs of {args.every_hours:g} h in {replay:.1f} s: "
        f"{1000 * replay / len(runs):.1f} ms per run, {len(runs) / replay:.0f} runs/s, "
        f"peak memory of the process {peak / 2**20:.0f} MiB"
    )

    # Diagnosis per sample.
    tic = time.perf_counter()
    judged = judge_pca(frame.to_numpy(), model, confidence=args.confidence)
    judge_seconds = time.perf_counter() - tic
    beyond = (judged.t2 > judged.t2_limit) | (judged.spe > judged.spe_limit)
    # Judged out of sample: the second and third years only.
    tested = ~first_year
    status = np.where(tested, status, -1)
    settled &= tested
    false_alarm = float(beyond[settled].mean())
    faults = []
    starts = np.flatnonzero((status != 0) & (np.roll(status, 1) != status))
    for fault in sorted(set(status) - {0, -1}):
        rows = status == fault
        delays = []
        for begin in starts[status[starts] == fault]:
            end = begin
            while end < len(status) and status[end] == fault:
                end += 1
            hit = np.flatnonzero(beyond[begin:end])
            delays.append(hit[0] * STEP / 60 if len(hit) else np.nan)
        faults.append(
            {
                "fault": int(fault),
                "episodes": len(delays),
                "hours": round(float(rows.sum()) * STEP / 3600, 1),
                "detected_pct": round(100 * float(beyond[rows].mean()), 1),
                "median_delay_min": None
                if np.all(np.isnan(delays))
                else round(float(np.nanmedian(delays)), 0),
                "missed_episodes": int(np.sum(np.isnan(delays))),
            }
        )

    # Diagnosis per run: a fault active in the run's window against the verdict.
    hits = misses = alarms = quiet = 0
    for end, run in zip(ends, runs, strict=True):
        window = (frame.index > end - pd.Timedelta(seconds=timing.window_seconds)) & (
            frame.index <= end
        )
        if not tested[window].all():
            continue
        faulty = bool((status[window] != 0).any())
        recovered = bool(settled[window].all())
        flagged = run in {"warning", "bad"}
        if faulty:
            hits += flagged
            misses += not flagged
        elif recovered:
            alarms += flagged
            quiet += not flagged

    report = {
        "samples": int(frame.shape[0]),
        "signals": int(frame.shape[1]),
        "load_seconds": round(loaded, 1),
        "calibrate_stretch": {"samples": stretch.samples, "seconds": round(calibrated, 2)},
        "model": {
            "trained_on": "first year, settled normal operation",
            "tested_on": "second and third years",
            "samples": model.samples,
            "components": model.components,
            "explained": round(model.explained, 3),
            "seconds": round(fitted, 2),
        },
        "replay": {
            "runs": len(runs),
            "hours_each": args.every_hours,
            "seconds": round(replay, 1),
            "ms_per_run": round(1000 * replay / len(runs), 1),
            "peak_mib": round(peak / 2**20),
        },
        "judge_all_seconds": round(judge_seconds, 2),
        "false_alarm_pct": round(100 * false_alarm, 2),
        "runs_with_fault_flagged_pct": round(100 * hits / max(1, hits + misses), 1),
        "settled_runs_flagged_pct": round(100 * alarms / max(1, alarms + quiet), 1),
        "faults": faults,
    }
    print(f"Judged every sample in {judge_seconds:.1f} s")
    print(f"False alarms on settled normal operation: {report['false_alarm_pct']} % of samples")
    print(
        f"Runs with a fault flagged: {report['runs_with_fault_flagged_pct']} % "
        f"({hits} of {hits + misses}); settled normal runs flagged: "
        f"{report['settled_runs_flagged_pct']} % ({alarms} of {alarms + quiet})"
    )
    print("fault  episodes  hours  detected %  median delay (min)  missed episodes")
    for row in faults:
        print(
            f"{row['fault']:>5}  {row['episodes']:>8}  {row['hours']:>5}  {row['detected_pct']:>10}"
            f"  {row['median_delay_min']!s:>18}  {row['missed_episodes']:>15}"
        )
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
