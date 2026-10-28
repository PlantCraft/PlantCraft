"""The Historian's examples in Notebooks (``Examples/Historian``): served in the suite's format
and run as a person's notebook runs them."""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk import apptest
from plantcraft_sdk.notebooks import example_problems

from histcraft.notebook_examples import EXAMPLES

ROOT = Path(__file__).resolve().parents[1]


def test_the_historian_serves_its_examples(client):
    assert apptest.objects_problems(client, "/hist", ROOT) == []
    assert example_problems(EXAMPLES) == []


def test_every_example_runs_as_a_notebook_runs_it(client, fake, tmp_path):
    # The export example saves its file where the notebook runs.
    problems = apptest.run_examples(EXAMPLES, client, "/hist", fake, root=ROOT, workdir=tmp_path)
    assert problems == [], "\n".join(problems)
    assert (tmp_path / "historian-export.csv").stat().st_size > 0
