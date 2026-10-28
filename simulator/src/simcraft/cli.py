"""The `simcraft` command: benchmark catalog, datasets, both OPC UA servers, health check."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime

from .catalog import load_catalog
from .contracts import (
    build_benchmark_manifest,
    load_benchmark_manifest,
    write_benchmark_manifest,
)
from .dataset import generate_dataset
from .engine import SUPPORTED_SCENARIOS
from .experiments import run_isolation_matrix, run_scenario_study
from .profiles import PROFILE_IDS, get_runtime_profile, load_runtime_profiles
from .server import DEFAULT_ENDPOINT, OpcUaPlantServer
from .settings import env


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simcraft",
        description=(
            "PlantCraft Simulator: OPC UA process plant simulator. The benchmark (500 signals, "
            "20 scenarios) and, under `simcraft loops`, the 50-loop portfolio of the "
            "PlantCraft demo."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "loops",
        help="the 50-loop portfolio: `simcraft loops serve|catalog` (see `loops --help`)",
        add_help=False,
    )
    subparsers.add_parser("healthcheck", help="exit 0 when the local OPC UA server is healthy")

    subparsers.add_parser("validate-catalog", help="validate the bundled 50-loop catalog")
    inspect_parser = subparsers.add_parser("inspect", help="print catalog metadata")
    inspect_parser.add_argument("--json", action="store_true", dest="as_json")

    export_manifest = subparsers.add_parser(
        "export-manifest", help="write the canonical benchmark manifest"
    )
    export_manifest.add_argument("--output", default="benchmark-manifest.json")
    validate_manifest = subparsers.add_parser(
        "validate-manifest", help="validate a benchmark manifest before use"
    )
    validate_manifest.add_argument("path")
    validate_manifest.add_argument("--expected-catalog-digest")
    subparsers.add_parser("profiles", help="print the versioned runtime profiles")
    validate_scenarios = subparsers.add_parser(
        "validate-scenarios", help="run the deterministic 30-seed scenario study"
    )
    validate_scenarios.add_argument("--output", default="var/scenario-study.json")
    validate_scenarios.add_argument("--jobs", type=int, default=1)
    validate_scenarios.add_argument("--scenario-cycle-hours", type=float, default=1.0)
    validate_scenarios.add_argument("--frame-seconds", type=float, default=30.0)
    validate_scenarios.add_argument("--integration-step-seconds", type=float, default=1.0)
    validate_scenarios.add_argument(
        "--skip-frame-baselines",
        action="store_true",
        help="omit in-memory per-frame baselines for long, high-cadence studies",
    )
    isolation_matrix = subparsers.add_parser(
        "validate-isolation-matrix",
        help="run all 20 scenarios independently across the 30 fixed seeds",
    )
    isolation_matrix.add_argument("--output", default="var/scenario-isolation-matrix.json")
    isolation_matrix.add_argument("--jobs", type=int, default=1)
    isolation_matrix.add_argument("--scenario-cycle-hours", type=float, default=1.0)
    isolation_matrix.add_argument("--frame-seconds", type=float, default=30.0)
    isolation_matrix.add_argument("--integration-step-seconds", type=float, default=1.0)
    validate_scenarios.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SUPPORTED_SCENARIOS),
        help=(
            "enable only this scenario; repeat for a deliberate overlap "
            "(default: integrated plant schedule)"
        ),
    )

    generate = subparsers.add_parser("generate", help="generate observations and hidden truth")
    generate.add_argument("--output", default="var/observations.csv")
    generate.add_argument("--truth-output", default="var/truth.jsonl")
    generate.add_argument("--manifest-output")
    generate.add_argument("--profile", choices=PROFILE_IDS, default="development")
    generate.add_argument("--duration-hours", type=float)
    generate.add_argument("--sample-seconds", type=float)
    generate.add_argument("--integration-step-seconds", type=float)
    generate.add_argument("--scenario-cycle-hours", type=float)
    generate.add_argument("--seed", type=int, default=20260903)
    generate.add_argument("--start-at", type=datetime.fromisoformat)

    serve = subparsers.add_parser("serve", help="serve the benchmark through OPC UA")
    serve.add_argument("--endpoint", default=env("SIMCRAFT_ENDPOINT", DEFAULT_ENDPOINT))
    # Not SIMCRAFT_HISTORY_DB: that names the loop portfolio's historian, a file the
    # benchmark must never adopt (it holds values without a benchmark checkpoint).
    serve.add_argument("--history-db", default="var/history.sqlite3")
    serve.add_argument("--profile", choices=PROFILE_IDS, default="development")
    serve.add_argument("--history-hours", type=float)
    serve.add_argument("--sample-seconds", type=float)
    serve.add_argument("--integration-step-seconds", type=float)
    serve.add_argument("--scenario-cycle-hours", type=float)
    serve.add_argument("--max-history-values-per-node", type=int)
    serve.add_argument("--seed", type=int, default=20260903)
    serve.add_argument("--reset", action="store_true")
    return parser


async def _serve(args: argparse.Namespace) -> None:
    profile = get_runtime_profile(args.profile)
    server = OpcUaPlantServer(
        endpoint=args.endpoint,
        history_db=args.history_db,
        history_hours=(
            profile.history_seconds / 3600.0 if args.history_hours is None else args.history_hours
        ),
        sample_seconds=(
            profile.observation_frame_seconds
            if args.sample_seconds is None
            else args.sample_seconds
        ),
        integration_step_seconds=(
            profile.integration_step_seconds
            if args.integration_step_seconds is None
            else args.integration_step_seconds
        ),
        scenario_cycle_seconds=(
            profile.scenario_cycle_seconds
            if args.scenario_cycle_hours is None
            else args.scenario_cycle_hours * 3600.0
        ),
        max_history_values_per_node=(
            profile.max_history_values_per_node
            if args.max_history_values_per_node is None
            else args.max_history_values_per_node
        ),
        seed=args.seed,
        reset=args.reset,
    )
    await server.start()
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()


def _loops_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simcraft loops",
        description="The 50-loop portfolio that the PlantCraft demo reads through OPC UA.",
    )
    commands = parser.add_subparsers(dest="loops_command", required=True)
    commands.add_parser("serve", help="serve the loops through OPC UA (see `serve --help`)")
    commands.add_parser("catalog", help="print every loop and its tags as JSON")
    return parser


def _loops(argv: list[str]) -> int:
    if argv[:1] == ["serve"]:
        from .loops.server import main as serve_loops

        return serve_loops(argv[1:], prog="simcraft loops serve")
    args = _loops_parser().parse_args(argv)
    if args.loops_command == "catalog":
        from .loops import loop_catalog

        print(json.dumps(loop_catalog(), indent=2, ensure_ascii=False))
        return 0
    raise AssertionError(args.loops_command)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["loops"]:
        return _loops(argv[1:])
    if argv[:1] == ["testkit"]:  # development and CI only: not in --help
        from .testkit.cli import main as testkit

        return testkit(argv[1:])
    args = _parser().parse_args(argv)
    if args.command == "healthcheck":
        from .healthcheck import main as healthcheck

        return healthcheck()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    catalog = load_catalog()
    if args.command == "validate-catalog":
        errors = catalog.validate()
        if errors:
            for error in errors:
                print(error)
            return 1
        print(
            f"PASS: {len(catalog.loops)} loops, {len(catalog.signals)} signals, "
            f"{len(catalog.scenarios)} scenarios, digest={catalog.digest}"
        )
        return 0
    if args.command == "inspect":
        summary = {
            "loops": len(catalog.loops),
            "signals": len(catalog.signals),
            "scenarios": len(catalog.scenarios),
            "areas": sorted({item.area_code for item in catalog.loops}),
            "catalog_digest": f"sha256:{catalog.digest}",
        }
        print(json.dumps(summary, indent=2 if args.as_json else None))
        return 0
    if args.command == "profiles":
        print(json.dumps([item.to_dict() for item in load_runtime_profiles()], indent=2))
        return 0
    if args.command == "export-manifest":
        manifest = build_benchmark_manifest(catalog)
        digest = write_benchmark_manifest(args.output, manifest)
        print(json.dumps({"output": args.output, "manifest_digest": digest}, indent=2))
        return 0
    if args.command == "validate-manifest":
        manifest = load_benchmark_manifest(
            args.path,
            expected_catalog_digest=args.expected_catalog_digest,
        )
        print(
            f"PASS: benchmark_version={manifest['benchmark_version']}, "
            f"catalog_digest={manifest['catalog_digest']}"
        )
        return 0
    if args.command == "validate-scenarios":
        if args.jobs <= 0:
            raise ValueError("jobs must be positive")
        report = run_scenario_study(
            args.output,
            jobs=args.jobs,
            scenario_cycle_seconds=args.scenario_cycle_hours * 3_600.0,
            frame_seconds=args.frame_seconds,
            integration_step_seconds=args.integration_step_seconds,
            scenario_ids=None if args.scenario is None else tuple(args.scenario),
            include_frame_baselines=not args.skip_frame_baselines,
        )
        print(
            json.dumps(
                {
                    "output": args.output,
                    "seeds": len(report["results"]),
                    "scenario_mode": report["scenario_mode"],
                    "selected_scenarios": report["selected_scenarios"],
                    "study_digest": report["study_digest"],
                },
                indent=2,
            )
        )
        return 0
    if args.command == "validate-isolation-matrix":
        report = run_isolation_matrix(
            args.output,
            jobs=args.jobs,
            scenario_cycle_seconds=args.scenario_cycle_hours * 3_600.0,
            frame_seconds=args.frame_seconds,
            integration_step_seconds=args.integration_step_seconds,
        )
        print(
            json.dumps(
                {
                    "output": args.output,
                    "runs": report["run_count"],
                    "passed": report["passed"],
                    "failed_runs": len(report["failed_runs"]),
                    "matrix_digest": report["matrix_digest"],
                },
                indent=2,
            )
        )
        return 0
    if args.command == "generate":
        profile = get_runtime_profile(args.profile)
        manifest_output = args.manifest_output or f"{args.output}.manifest.json"
        report = generate_dataset(
            args.output,
            args.truth_output,
            duration_seconds=(
                profile.duration_seconds
                if args.duration_hours is None
                else args.duration_hours * 3600.0
            ),
            sample_seconds=(
                profile.observation_frame_seconds
                if args.sample_seconds is None
                else args.sample_seconds
            ),
            seed=args.seed,
            start_at=args.start_at,
            integration_step_seconds=(
                profile.integration_step_seconds
                if args.integration_step_seconds is None
                else args.integration_step_seconds
            ),
            scenario_cycle_seconds=(
                profile.scenario_cycle_seconds
                if args.scenario_cycle_hours is None
                else args.scenario_cycle_hours * 3600.0
            ),
            manifest_output=manifest_output,
        )
        report["profile"] = profile.profile_id
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "serve":
        try:
            asyncio.run(_serve(args))
        except KeyboardInterrupt:
            return 0
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
