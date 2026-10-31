"""SKAB oracle: the Deviation (T²) block against the labelled anomalies of a real pump bench.

Data: ``python tests/oracles/fetch_skab.py`` (pinned, GPL-3.0, never committed). Labels: the
benchmark's own ``anomaly`` column, never our methods. Each of the 34 experiments is judged the
way a user would set it up: Calibrate on its first 400 samples (normal operation, the benchmark's
own training split), then the block judges the rest. Two scores, each a floor in
``[oracles]`` that only rises:

- per sample, as the SKAB leaderboard scores outlier detection: T² beyond its limit is an alarm;
- per run of 60 samples, as a monitoring round reports it: a run whose verdict is not ok is an
  alarm, and the run is anomalous when most of its samples are labelled so.

For each, F1 and the share of normal samples (or runs) left quiet (100 − false alarm rate).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.blocks import Context

from linkcraft.blocks.models import DEVIATION
from linkcraft.models.stats import calibrate

HERE = Path(__file__).parent
DATA = HERE.parents[1] / "oracles" / "skab"
FLOORS = tomllib.loads((HERE.parent / "floors.toml").read_text(encoding="utf-8"))
TRAIN = 400
RUN = 60
EXPERIMENTS = ("valve1", "valve2", "other")


def experiments() -> list[Path]:
    return sorted(path for folder in EXPERIMENTS for path in (DATA / folder).glob("*.csv"))


def read(path: Path) -> tuple[pd.DataFrame, np.ndarray]:
    frame = pd.read_csv(path, sep=";", index_col="datetime", parse_dates=True)
    labels = frame.pop("anomaly").to_numpy() == 1
    frame.pop("changepoint")
    return frame.astype(float), labels


class Counts:
    def __init__(self) -> None:
        self.tp = self.fp = self.fn = self.tn = 0

    def add(self, alarm: np.ndarray, label: np.ndarray) -> None:
        self.tp += int((alarm & label).sum())
        self.fp += int((alarm & ~label).sum())
        self.fn += int((~alarm & label).sum())
        self.tn += int((~alarm & ~label).sum())

    @property
    def f1(self) -> float:
        return 100.0 * 2 * self.tp / max(2 * self.tp + self.fp + self.fn, 1)

    @property
    def quiet(self) -> float:
        return 100.0 * self.tn / max(self.tn + self.fp, 1)

    def __str__(self) -> str:
        missed = 100.0 * self.fn / max(self.fn + self.tp, 1)
        return f"F1 {self.f1:.1f}, false alarms {100 - self.quiet:.1f}%, missed {missed:.1f}%"


def judge(frame: pd.DataFrame, labels: np.ndarray, samples: Counts, runs: Counts) -> None:
    names = list(frame.columns)
    calibration = calibrate(frame.iloc[:TRAIN].to_numpy(), names).as_dict()
    parameters = DEVIATION.spec.parameters(calibration=calibration, centre=True)
    residuals = [frame[name].iloc[TRAIN:].rename(name) for name in names]
    whole = DEVIATION.run({"residuals": residuals}, parameters, Context(states={}, node_id="t2"))
    limit = whole["result"].detail["limit"]
    samples.add(whole["t2"].to_numpy() > limit, labels[TRAIN:])
    states: dict = {}
    alarms, truth = [], []
    for start in range(TRAIN, len(frame) - RUN + 1, RUN):
        part = [series.iloc[start - TRAIN : start - TRAIN + RUN] for series in residuals]
        found = DEVIATION.run({"residuals": part}, parameters, Context(states=states, node_id="t2"))
        alarms.append(found["result"].status != "ok")
        truth.append(labels[start : start + RUN].mean() >= 0.5)
    runs.add(np.array(alarms, dtype=bool), np.array(truth, dtype=bool))


def test_the_deviation_block_finds_the_skab_anomalies():
    files = experiments() if DATA.exists() else []
    if not files:
        pytest.skip("SKAB data absent: run `python tests/oracles/fetch_skab.py`")
    samples, runs = Counts(), Counts()
    for path in files:
        judge(*read(path), samples, runs)
    print(f"SKAB, {len(files)} experiments. Samples: {samples}. Runs of {RUN}: {runs}.")
    floors = FLOORS["oracles"]
    assert len(files) == floors["skab_experiments"]
    assert samples.f1 >= floors["skab_sample_f1"], str(samples)
    assert samples.quiet >= floors["skab_sample_quiet"], str(samples)
    assert runs.f1 >= floors["skab_run_f1"], str(runs)
    assert runs.quiet >= floors["skab_run_quiet"], str(runs)


def test_the_fetcher_checks_every_pinned_file(tmp_path):
    """fetch_skab.fetch from a made-up source folder: a file whose bytes are not the pinned ones
    stops it before anything is written."""

    from tests.oracles import fetch_skab

    source = tmp_path / "source"
    (source / "valve1").mkdir(parents=True)
    (source / "valve1" / "0.csv").write_text("datetime;anomaly\n", encoding="utf-8")
    pinned = {"valve1/0.csv": fetch_skab.sha256(b"datetime;anomaly\n")}
    original = fetch_skab.FILES
    try:
        fetch_skab.FILES = pinned
        assert fetch_skab.fetch(tmp_path / "out", source) == 1
        assert fetch_skab.fetch(tmp_path / "out", source) == 0  # kept: already right
        fetch_skab.FILES = {"valve1/0.csv": "0" * 64}
        with pytest.raises(SystemExit, match="is not the pinned"):
            fetch_skab.fetch(tmp_path / "other", source)
        assert not (tmp_path / "other").exists()
    finally:
        fetch_skab.FILES = original
    assert len(original) == 35 and all(len(digest) == 64 for digest in original.values())
