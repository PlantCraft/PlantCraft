import csv
import json
from pathlib import Path

from simcraft.dataset import generate_dataset


def test_dataset_and_hidden_truth_have_stable_digests(tmp_path: Path) -> None:
    first = generate_dataset(
        tmp_path / "first.csv",
        tmp_path / "first-truth.jsonl",
        duration_seconds=90,
        sample_seconds=30,
        seed=42,
    )
    second = generate_dataset(
        tmp_path / "second.csv",
        tmp_path / "second-truth.jsonl",
        duration_seconds=90,
        sample_seconds=30,
        seed=42,
    )

    assert first["observation_artifact"]["digest"] == second["observation_artifact"]["digest"]
    assert first["truth_artifact"]["digest"] == second["truth_artifact"]["digest"]
    assert (tmp_path / "first.csv").read_bytes() == (tmp_path / "second.csv").read_bytes()
    assert (tmp_path / "first-truth.jsonl").read_bytes() == (
        tmp_path / "second-truth.jsonl"
    ).read_bytes()

    with (tmp_path / "first.csv").open(newline="", encoding="utf-8") as stream:
        observations = list(csv.DictReader(stream))
    truth_rows = [
        json.loads(line)
        for line in (tmp_path / "first-truth.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert observations
    assert observations[0]["schema"] == "process-plant-opcua/observation/v1"
    assert observations[0]["source_timestamp"] == observations[0]["server_timestamp"]
    assert len(truth_rows) == 3
    assert truth_rows[0]["schema"] == "process-plant-opcua/truth-frame/v1"
    assert "loops" not in observations[0]
    assert len(truth_rows[0]["loops"]) == 50
