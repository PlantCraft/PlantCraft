"""International Stiction Database oracle: ``stiction_screening`` against published labels.

Data: ``python tests/oracles/fetch_isdb.py`` (pinned, never committed). Labels:
``tests/oracles/isdb_labels.toml``, transcribed from Jelali and Huang (2010). Each labelled loop
is served by ``FakePlantCraft`` and analysed by a monitoring round, the production path. The
number of loops whose verdict matches the label never drops below ``[oracles] isdb_loops``.
"""

from __future__ import annotations

import json
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from linkcraft.config import AnalysisConfig
from tests.conftest import make_runtime
from tests.plant import PlantFake

HERE = Path(__file__).parent
DATA = HERE.parents[1] / "oracles" / "isdb"
FLOORS = tomllib.loads((HERE.parent / "floors.toml").read_text(encoding="utf-8"))
LABELS = tomllib.loads((HERE / "isdb_labels.toml").read_text(encoding="utf-8"))
END = datetime(2026, 10, 1, tzinfo=timezone.utc)
SAID = {"warning": "stiction", "bad": "stiction", "ok": "no_stiction"}


def _loop_id(name: str) -> str:
    return name.lower().replace(".", "-").replace("_", "-")


def score(data: Path, labels: dict[str, str], tmp_path: Path) -> tuple[int, list[str]]:
    """Loops whose stiction screening agrees with their label, and the ones that do not."""

    manifest = {row["loop"]: row for row in json.loads((data / "loops.json").read_text())}
    missing = sorted(set(labels) - set(manifest))
    assert not missing, f"labelled loops not in the fetched data: {missing}"
    assets = [{"id": "isdb", "name": "ISDB", "kind": "site", "parent_id": None, "attributes": {}}]
    signals, series, spans, steps = [], {}, [], []
    for name in sorted(labels):
        row = manifest[name]
        frame = pd.read_csv(data / "loops" / f"{name}.csv")
        step = float(row["sample_seconds"] or 1.0)
        index = pd.DatetimeIndex([END - timedelta(seconds=step * i) for i in range(len(frame))])
        loop_id = _loop_id(name)
        roles = [role for role in ("pv", "op", "sp") if role in frame]
        assets.append(
            {
                "id": loop_id,
                "name": name,
                "kind": "loop",
                "parent_id": "isdb",
                "attributes": {},
                "signals": {role: f"{loop_id}.{role}" for role in roles},
            }
        )
        for role in roles:
            signals.append({"id": f"{loop_id}.{role}", "name": role, "source": "isdb", "unit": ""})
            series[f"{loop_id}.{role}"] = pd.Series(frame[role].to_numpy(), index=index[::-1])
        spans.append(step * len(frame))
        steps.append(step)
    fake = PlantFake(assets=assets, signals=signals, series=series, now=END)
    # One window that holds the longest loop, at the finest sampling time.
    analysis = AnalysisConfig(window_minutes=int(max(spans) / 60) + 1, resample_seconds=min(steps))
    runtime = make_runtime(tmp_path, fake, analysis=analysis)
    matched, wrong = 0, []
    try:
        runtime.run_round()
        for name, label in sorted(labels.items()):
            payload = runtime.monitor.loop_payload(_loop_id(name))
            results = {item["method_id"]: item for item in payload["results"]}
            status = results["stiction_screening"]["status"]
            if SAID.get(status) == label:
                matched += 1
            else:
                wrong.append(f"{name}: label {label}, screening {status}")
    finally:
        runtime.shutdown()
    return matched, wrong


def test_stiction_screening_matches_published_labels(tmp_path):
    if not (DATA / "loops.json").exists():
        pytest.skip(
            "ISDB data absent: run `python tests/oracles/fetch_isdb.py` (sha256 not pinned yet, "
            "docs/gaps.md G3)"
        )
    labels = LABELS.get("labels", {})
    if not labels:
        pytest.skip("No published ISDB labels transcribed yet (tests/oracles/isdb_labels.toml)")
    assert LABELS.get("source"), "cite the table the labels come from"
    matched, wrong = score(DATA, labels, tmp_path)
    print(f"ISDB: {matched}/{len(labels)} loops match the published label; wrong: {wrong}")
    assert matched >= FLOORS["oracles"]["isdb_loops"], wrong


def test_the_scoring_path_runs_on_a_synthetic_database(tmp_path):
    """The harness itself, on two made-up loops in the layout fetch_isdb.py writes (not data)."""

    data = tmp_path / "isdb"
    (data / "loops").mkdir(parents=True)
    n = 2000
    steps = np.arange(n)
    levels = np.concatenate([np.arange(46, 54), np.arange(54, 46, -1)]).astype(float)
    sticky = pd.DataFrame(
        {
            "pv": 50 + 3 * np.sin(2 * np.pi * steps / 96),
            "op": levels[(steps // 6) % len(levels)],
        }
    )
    rng = np.random.default_rng(1)
    smooth = pd.DataFrame(
        {"pv": 50 + rng.normal(0, 0.2, n), "op": 40 + np.cumsum(rng.normal(0, 0.01, n))}
    )
    sticky.to_csv(data / "loops" / "demo.sticky.csv", index=False)
    smooth.to_csv(data / "loops" / "demo.smooth.csv", index=False)
    rows = [
        {"loop": name, "sample_seconds": 10.0, "samples": n, "text": {}}
        for name in ("demo.sticky", "demo.smooth")
    ]
    (data / "loops.json").write_text(json.dumps(rows))
    matched, wrong = score(
        data, {"demo.sticky": "stiction", "demo.smooth": "no_stiction"}, tmp_path / "rt"
    )
    assert (matched, wrong) == (2, [])
