"""Streaming export of versioned observations and hidden benchmark truth."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .contracts import (
    BENCHMARK_VERSION,
    DATASET_MANIFEST_SCHEMA,
    OBSERVATION_SCHEMA,
    TRUTH_FRAME_SCHEMA,
    build_benchmark_manifest,
    document_digest,
    write_dataset_manifest,
)
from .engine import PlantSimulator


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _positive_finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def generate_dataset(
    output: str | Path,
    truth_output: str | Path,
    *,
    duration_seconds: float,
    sample_seconds: float,
    seed: int,
    start_at: datetime | None = None,
    integration_step_seconds: float = 1.0,
    scenario_cycle_seconds: float = 21_600.0,
    manifest_output: str | Path | None = None,
) -> dict[str, object]:
    """Generate v1 observation CSV, hidden-truth JSONL, and optional manifest."""

    duration = _positive_finite(duration_seconds, "duration_seconds")
    frame_seconds = _positive_finite(sample_seconds, "sample_seconds")
    integration = _positive_finite(integration_step_seconds, "integration_step_seconds")
    cycle = _positive_finite(scenario_cycle_seconds, "scenario_cycle_seconds")
    if cycle < 600:
        raise ValueError("scenario_cycle_seconds must be at least 600")
    if frame_seconds < integration or not math.isclose(
        frame_seconds / integration,
        round(frame_seconds / integration),
        abs_tol=1e-9,
    ):
        raise ValueError("sample_seconds must be an integer multiple of integration step")
    if not math.isclose(
        duration / frame_seconds,
        round(duration / frame_seconds),
        abs_tol=1e-9,
    ):
        raise ValueError("duration_seconds must be divisible by sample_seconds")

    output_path = Path(output).resolve()
    truth_path = Path(truth_output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    simulator = PlantSimulator(
        seed=seed,
        start_at=start_at or datetime(2026, 1, 1, tzinfo=UTC),
        integration_step_seconds=integration,
        scenario_cycle_seconds=cycle,
    )
    observation_count = 0
    frame_count = 0
    with (
        output_path.open("w", encoding="utf-8", newline="") as data_stream,
        truth_path.open("w", encoding="utf-8", newline="") as truth_stream,
    ):
        writer = csv.DictWriter(
            data_stream,
            fieldnames=(
                "schema",
                "source_timestamp",
                "server_timestamp",
                "signal_id",
                "node_id",
                "value",
                "quality",
                "engineering_unit",
            ),
        )
        writer.writeheader()
        elapsed = 0.0
        while elapsed < duration - 1e-12:
            step = min(frame_seconds, duration - elapsed)
            frame = simulator.advance(step)
            frame_count += 1
            elapsed += step
            for observation in frame.observations:
                row = {
                    "schema": OBSERVATION_SCHEMA,
                    "source_timestamp": observation.timestamp.isoformat(),
                    "server_timestamp": frame.timestamp.isoformat(),
                    "signal_id": observation.signal_id,
                    "node_id": observation.node_id,
                    "value": observation.value,
                    "quality": observation.quality,
                    "engineering_unit": observation.engineering_unit,
                }
                writer.writerow(row)
                observation_count += 1
            truth_row = {
                "schema": TRUTH_FRAME_SCHEMA,
                "timestamp": frame.timestamp.isoformat(),
                "state_digest": frame.state_digest,
                "loops": simulator.truth_state(),
                "transitions": [asdict(event) for event in frame.truth_events],
            }
            encoded_truth = json.dumps(
                truth_row,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=False,
            )
            truth_stream.write(encoded_truth + "\n")
    benchmark_manifest = build_benchmark_manifest(simulator.catalog)
    dataset_manifest: dict[str, object] = {
        "schema": DATASET_MANIFEST_SCHEMA,
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_manifest_digest": document_digest(benchmark_manifest),
        "catalog_digest": f"sha256:{simulator.catalog.digest}",
        "seed": simulator.seed,
        "start_at": simulator.start_at.isoformat(),
        "end_at": frame.timestamp.isoformat(),
        "duration_seconds": duration,
        "integration_step_seconds": integration,
        "observation_frame_seconds": frame_seconds,
        "scenario_cycle_seconds": cycle,
        "frames": frame_count,
        "observations": observation_count,
        "observation_artifact": {
            "schema": OBSERVATION_SCHEMA,
            "format": "csv",
            "path": output_path.name,
            "digest": _file_digest(output_path),
        },
        "truth_artifact": {
            "schema": TRUTH_FRAME_SCHEMA,
            "format": "jsonl",
            "path": truth_path.name,
            "digest": _file_digest(truth_path),
        },
    }
    manifest_digest = document_digest(dataset_manifest)
    manifest_path: Path | None = None
    if manifest_output is not None:
        manifest_path = Path(manifest_output).resolve()
        manifest_digest = write_dataset_manifest(manifest_path, dataset_manifest)
    return {
        **dataset_manifest,
        "dataset_manifest_digest": manifest_digest,
        "output": str(output_path),
        "truth_output": str(truth_path),
        "manifest_output": None if manifest_path is None else str(manifest_path),
    }
