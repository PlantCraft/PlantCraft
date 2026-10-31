"""SACAC oracle: ``stiction_screening`` against the category SACAC files each industrial loop in.

Data: ``python tests/oracles/fetch_sacac.py`` (pinned, never committed: the repository declares
no licence). Labels: the repository's own categories (Bauer et al., 2016), never our methods:
a loop under Stiction is "stiction", one under Tuning is "no_stiction". Each loop is scored
alone, through a monitoring round on ``FakePlantCraft`` (the production path,
as the ISDB oracle). The number of loops whose verdict matches never drops below
``[oracles] sacac_loops``.
"""

from __future__ import annotations

import json
import tomllib
from collections import defaultdict
from pathlib import Path

import pytest

from tests.oracles.test_isdb_oracle import score

HERE = Path(__file__).parent
DATA = HERE.parents[1] / "oracles" / "sacac"
FLOORS = tomllib.loads((HERE.parent / "floors.toml").read_text(encoding="utf-8"))


def test_stiction_screening_matches_the_sacac_categories(tmp_path):
    if not (DATA / "loops.json").exists():
        pytest.skip(
            "SACAC data absent: run `python tests/oracles/fetch_sacac.py` where sacac.org.za is "
            "reachable (docs/gaps.md G3)"
        )
    rows = json.loads((DATA / "loops.json").read_text(encoding="utf-8"))
    # One round per loop, so each one's window is its own record (cases run from 20 minutes to
    # two days).
    matched, wrong = 0, []
    for index, row in enumerate(rows):
        found, missed = score(DATA, {row["loop"]: row["category"]}, tmp_path / f"loop-{index}")
        matched += found
        wrong += missed
    by_label = defaultdict(lambda: [0, 0])
    for row in rows:
        by_label[row["category"]][1] += 1
    for line in wrong:
        by_label[line.split("label ")[1].split(",")[0]][0] -= 1
    summary = {label: f"{count + total}/{total}" for label, (count, total) in by_label.items()}
    print(f"SACAC: {matched}/{len(rows)} loops match their category {summary}; wrong: {wrong}")
    assert matched >= FLOORS["oracles"]["sacac_loops"], wrong


def test_the_fetcher_reads_the_repository_layout(tmp_path):
    """fetch_sacac.convert on a made-up archive in SACAC's layout (not data): a stiction case
    (OP moving in steps), a tuning case (smooth OP), and a plant-wide one it skips."""

    import zipfile

    import numpy as np

    from tests.oracles.fetch_sacac import convert, sample_seconds

    n = 2000
    steps = np.arange(n)
    levels = np.concatenate([np.arange(46, 54), np.arange(54, 46, -1)]).astype(float)
    sticky = [(50 + 3 * np.sin(2 * np.pi * i / 96), levels[(i // 6) % len(levels)]) for i in steps]
    rng = np.random.default_rng(1)
    op = 40 + np.cumsum(rng.normal(0, 0.01, n))
    smooth = [(50 + rng.normal(0, 0.2), op[i], 50.0) for i in steps]
    archive = tmp_path / "repo.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "Stiction/stiction-F-x/stiction-F-x.csv",
            "PV,OP\r" + "\r".join(f"{a},{b}" for a, b in sticky),  # bare CR, as SACAC's
        )
        bundle.writestr("Stiction/stiction-F-x/stiction-F-x.txt", "Sampling rate: 10 seconds\n")
        bundle.writestr(
            "Tuning/tuning-L-x/tuning-L-x.csv",
            "SP;PV;OP\n" + "\n".join(f"{c};{a};{b}" for a, b, c in smooth),
        )
        bundle.writestr("Tuning/tuning-L-x/tuning-L-x.txt", "Sampling rate: 10 seconds (mean)\n")
        bundle.writestr("Stiction/plantwide/plantwide.csv", "Tag1,Tag2\n1,2\n")
        bundle.writestr("Saturation/sat-x/sat-x.csv", "PV,OP\n1,2\n")
    count, skipped = convert(archive, tmp_path / "sacac")
    assert count == 2 and [item["case"] for item in skipped] == ["plantwide"]
    rows = json.loads((tmp_path / "sacac" / "loops.json").read_text())
    assert {row["loop"]: row["category"] for row in rows} == {
        "stiction-F-x": "stiction",
        "tuning-L-x": "no_stiction",
    }
    assert sample_seconds("Sampling rate: non-constant (mean value: 12 seconds)") == 12.0
    labels = {row["loop"]: row["category"] for row in rows}
    assert score(tmp_path / "sacac", labels, tmp_path / "rt") == (2, [])


def test_the_shape_index_tells_a_triangle_from_a_sine_and_a_wander():
    """He et al. (2007) on clean shapes: a triangle wave near 1, a sine near 0; a random walk
    (no regular cycle) is not judged."""

    import numpy as np

    from linkcraft.methods.cpm.stiction import shape_index

    rng = np.random.default_rng(0)
    steps = np.arange(4000)
    period = 100
    sine = np.sin(2 * np.pi * steps / period) + rng.normal(0, 0.05, steps.size)
    triangle = 2 * np.abs(2 * ((steps / period) % 1) - 1) - 1 + rng.normal(0, 0.05, steps.size)
    assert shape_index(sine, period) < 0.2
    assert shape_index(triangle, period) > 0.8
    assert shape_index(np.cumsum(rng.normal(0, 1, steps.size)), period) is None
