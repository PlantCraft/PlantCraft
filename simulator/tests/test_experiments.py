from pathlib import Path

import pytest

from simcraft import experiments
from simcraft.catalog import load_catalog
from simcraft.contracts import document_digest
from simcraft.experiments import (
    evaluate_seed,
    run_isolation_matrix,
    run_scenario_study,
)
from simcraft.model import SCENARIO_PARAMETERS


def test_every_scenario_has_frozen_parameters_and_validation_rules() -> None:
    scenario_ids = {item.scenario_id for item in load_catalog().scenarios}
    assert set(SCENARIO_PARAMETERS) == scenario_ids
    assert set(experiments.PREREGISTERED_RULES) == scenario_ids


def test_one_complete_cycle_passes_all_scenario_signatures() -> None:
    result = evaluate_seed(1)

    assert result["passed"] is True
    assert result["failures"] == []
    assert len(result["scenarios"]) == 20
    assert document_digest(result).startswith("sha256:")


def test_sluggish_signature_uses_a_fixed_physical_response_window() -> None:
    result = evaluate_seed(
        1,
        scenario_cycle_seconds=7_200,
        frame_seconds=30,
        integration_step_seconds=5,
        scenario_ids=("control.sluggish_tuning",),
    )

    active = result["scenarios"]["control.sluggish_tuning"]["active"]
    assert active["samples"] > experiments.INITIAL_RESPONSE_WINDOW_SECONDS / 30
    assert active["initial_response_control_error"] >= 0.003
    assert result["passed"] is True


def test_one_scenario_can_be_qualified_without_other_fault_injections() -> None:
    result = evaluate_seed(
        1,
        scenario_cycle_seconds=600,
        scenario_ids=("data.gap",),
        collect_frame_samples=True,
    )

    assert result["enabled_scenarios"] == ["data.gap"]
    assert set(result["scenarios"]) == {"data.gap"}
    assert result["passed"] is True
    assert result["scenarios"]["data.gap"]["observations"]["active"]["observed_fraction"] == 0.0
    assert result["scenarios"]["data.gap"]["observations"]["active"]["pv_available"] == 0.0
    sample = result["frame_samples"][0]
    assert sample["elapsed_seconds"] == 30
    assert set(sample["features"]) == set(experiments.FRAME_FEATURE_METRICS)
    assert not ({"true_pv", "sensor_bias", "scenario_id"} & set(sample["features"]))


def test_transport_signatures_ignore_frames_without_scheduled_signals() -> None:
    result = evaluate_seed(
        1,
        scenario_cycle_seconds=600,
        frame_seconds=5,
        scenario_ids=(
            "normal.steady",
            "data.bad_quality",
            "data.irregular_cadence",
        ),
    )

    assert result["passed"] is True
    assert result["scenarios"]["normal.steady"]["active"]["observed_fraction"] == 1.0
    assert result["scenarios"]["data.bad_quality"]["active"]["bad_fraction"] == 1.0
    assert result["scenarios"]["data.irregular_cadence"]["active"]["uncertain_fraction"] > 0.7


def test_regularized_grid_is_causal_and_age_bounded() -> None:
    result = evaluate_seed(
        1,
        scenario_cycle_seconds=600,
        frame_seconds=30,
        scenario_ids=("data.gap",),
        collect_frame_samples=True,
    )
    active = [
        sample
        for sample in result["frame_samples"]
        if sample["loop_id"] == "AIC-105" and sample["active"]
    ]

    assert active[0]["features"]["imputed_fraction"] > 0.0
    assert active[-1]["features"]["regularized_pv_available"] == 0.0
    assert active[-1]["features"]["imputed_fraction"] == 0.0


def test_study_manifest_is_path_independent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        experiments,
        "SEED_PARTITIONS",
        {"development": (1,), "validation": (2,), "held_out_test": (3,)},
    )

    def fake_evaluate(arguments):
        return {
            "seed": arguments[0],
            "frames": 1,
            "scenarios": {},
            "passed": True,
            "failures": [],
        }

    monkeypatch.setattr(experiments, "_evaluate_seed_arguments", fake_evaluate)
    first = run_scenario_study(tmp_path / "first/study.json")
    second = run_scenario_study(tmp_path / "second/study.json")

    assert first == second
    assert first["scenario_mode"] == "integrated"
    assert len(first["selected_scenarios"]) == 20
    assert (tmp_path / "first/study.json").read_bytes() == (
        tmp_path / "second/study.json"
    ).read_bytes()
    digest = first.pop("study_digest")
    assert digest == document_digest(first)

    isolated = run_scenario_study(
        tmp_path / "isolated/study.json",
        scenario_ids=("data.gap",),
    )
    assert isolated["scenario_mode"] == "isolated"
    assert isolated["selected_scenarios"] == ["data.gap"]
    assert isolated["statistics"] == {}
    assert isolated["observation_window_baselines"] == {}
    assert isolated["frame_baselines"] == {}


@pytest.mark.parametrize("jobs", [0, -1, True, 1.5])
def test_study_rejects_invalid_worker_counts(jobs: object, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        run_scenario_study(tmp_path / "study.json", jobs=jobs)


def test_study_can_skip_memory_heavy_frame_baselines(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        experiments,
        "SEED_PARTITIONS",
        {"development": (1,), "validation": (2,), "held_out_test": (3,)},
    )

    def fake_evaluate(arguments):
        assert arguments[-1] is False
        return {
            "seed": arguments[0],
            "frames": 4_320,
            "scenarios": {},
            "passed": True,
            "failures": [],
        }

    monkeypatch.setattr(experiments, "_evaluate_seed_arguments", fake_evaluate)
    report = run_scenario_study(
        tmp_path / "paper-study.json",
        frame_seconds=5.0,
        scenario_cycle_seconds=21_600.0,
        include_frame_baselines=False,
    )

    assert report["frame_baselines"] == {}
    assert all(result["frames"] == 4_320 for result in report["results"])


@pytest.mark.parametrize(
    ("scenario_ids", "message"),
    [
        ((), "at least one"),
        (("data.gap", "data.gap"), "unique"),
        (("unknown.scenario",), "unknown scenarios"),
    ],
)
def test_study_rejects_invalid_scenario_selections(
    scenario_ids: tuple[str, ...], message: str, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match=message):
        run_scenario_study(
            tmp_path / "study.json",
            scenario_ids=scenario_ids,
        )


def test_confidence_interval_is_explicit() -> None:
    interval = experiments._confidence_interval([1.0, 2.0, 3.0, 4.0, 5.0])

    assert interval["mean"] == 3.0
    assert interval["lower"] < interval["mean"] < interval["upper"]


def test_summary_baseline_fits_development_and_scores_reserved_seeds() -> None:
    results = []
    for seed in range(1, 31):
        scenarios = {}
        for scenario_id, offset in (("scenario.a", 0.0), ("scenario.b", 10.0)):
            active = {metric: offset for metric in experiments.SUMMARY_METRICS}
            active["observed_fraction"] = 1.0
            observed = {metric: offset for metric in experiments.OBSERVATION_METRICS}
            observed.update(
                {
                    "observed_fraction": 1.0,
                    "pv_range": offset,
                    "sp_range": offset,
                }
            )
            scenarios[scenario_id] = {
                "active": active,
                "inactive": active,
                "observations": {"active": observed, "inactive": observed},
                "transitions": 2,
            }
        results.append({"seed": seed, "scenarios": scenarios})

    report = experiments.evaluate_observation_baselines(results)

    assert set(report["views"]) == set(experiments.OBSERVATION_ABLATION_FEATURES)
    for view in report["views"].values():
        assert view["splits"]["validation"]["accuracy"] == 1.0
        assert view["splits"]["held_out_test"]["macro_f1"] == 1.0


def test_statistics_are_reported_for_an_isolated_scenario() -> None:
    active = {metric: 1.0 for metric in experiments.SUMMARY_METRICS}
    results = [
        {
            "seed": seed,
            "scenarios": {
                "sensor.noise": {
                    "active": active,
                    "inactive": active,
                    "transitions": 2,
                }
            },
        }
        for seed in range(1, 31)
    ]

    statistics = experiments.summarize_scenario_statistics(results)

    assert statistics["scenarios"]["sensor.noise"]["sensor_error"]["count"] == 30
    assert experiments.evaluate_observation_baselines(results) == {}


def test_per_frame_baseline_uses_reserved_seed_partitions() -> None:
    results = []
    for seed in range(1, 31):
        samples = []
        for elapsed, active, offset in ((0, False, 0.0), (30, True, 10.0)):
            features = {metric: offset for metric in experiments.FRAME_FEATURE_METRICS}
            samples.append(
                {
                    "scenario_id": "scenario.a",
                    "loop_id": "A",
                    "elapsed_seconds": elapsed,
                    "active": active,
                    "features": features,
                }
            )
        results.append({"seed": seed, "frame_samples": samples})

    report = experiments.evaluate_frame_baselines(results, frame_seconds=30.0)

    assert set(report["views"]) == set(experiments.FRAME_ABLATION_FEATURES)
    for view in report["views"].values():
        assert view["splits"]["validation"]["accuracy"] == 1.0
        assert view["splits"]["held_out_test"]["macro_f1"] == 1.0


def test_temporal_detection_and_loop_localization_are_explicit() -> None:
    temporal_records = [
        {
            "seed": 21,
            "scenario_id": "scenario.a",
            "loop_id": "A",
            "elapsed_seconds": elapsed,
            "active": active,
        }
        for elapsed, active in (
            (0, False),
            (30, True),
            (60, True),
            (90, True),
            (120, False),
        )
    ]
    temporal = experiments._temporal_detection_metrics(
        temporal_records,
        ["inactive", "active", "active", "active", "inactive"],
        persistence_frames=3,
    )

    assert temporal["onsets"] == 1
    assert temporal["detection_rate"] == 1.0
    assert temporal["mean_detection_delay_seconds"] == 60.0

    localization_records = [
        {
            "seed": 21,
            "scenario_id": "scenario.a",
            "loop_id": loop_id,
            "elapsed_seconds": elapsed,
            "active": active,
        }
        for elapsed, loop_id, active in (
            (30, "A", True),
            (30, "B", False),
            (60, "A", False),
            (60, "B", True),
        )
    ]
    localization = experiments._localization_metrics(
        localization_records,
        [2.0, 1.0, 1.0, 2.0],
        top_k=5,
    )

    assert localization["mean_average_precision"] == 1.0
    assert localization["precision_at_5"] == 0.5
    assert localization["recall_at_5"] == 1.0


def test_isolation_matrix_is_canonical_and_path_independent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        experiments,
        "SEED_PARTITIONS",
        {"development": (1,), "validation": (2,), "held_out_test": (3,)},
    )
    monkeypatch.setattr(
        experiments,
        "PREREGISTERED_RULES",
        {"scenario.a": (), "scenario.b": ()},
    )

    def fake_isolated(arguments):
        seed, scenario_id, *_ = arguments
        active = {metric: float(seed) for metric in experiments.SUMMARY_METRICS}
        scenario = {"active": active, "inactive": active, "transitions": 2}
        return {
            "seed": seed,
            "scenario_id": scenario_id,
            "frames": 1,
            "scenario": scenario,
            "passed": True,
            "failures": [],
            "evaluation_digest": "sha256:" + "0" * 64,
        }

    monkeypatch.setattr(experiments, "_evaluate_isolated_arguments", fake_isolated)
    first = run_isolation_matrix(tmp_path / "first/matrix.json")
    second = run_isolation_matrix(tmp_path / "second/matrix.json")

    assert first == second
    assert first["run_count"] == 6
    assert first["passed"] is True
    assert (tmp_path / "first/matrix.json").read_bytes() == (
        tmp_path / "second/matrix.json"
    ).read_bytes()
    digest = first.pop("matrix_digest")
    assert digest == document_digest(first)


def test_isolation_matrix_rejects_invalid_worker_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        run_isolation_matrix(tmp_path / "matrix.json", jobs=0)
