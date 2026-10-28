"""Settings, all from the environment, each with a safe default.

Secrets (the app key) are never logged or stored by PlantCraft Models, and never reach the
runner container.

| Variable | Default | Meaning |
|---|---|---|
| ``PLANTCRAFT_URL`` | ``http://127.0.0.1:8060`` | PlantCraft API v1, as this server reaches it |
| ``PLANTCRAFT_PUBLIC_URL`` | empty (same origin) | PlantCraft as the browser reaches it (sign-in page) |
| ``PLANTCRAFT_APP_KEY`` | empty | App key: Models reports its runs to PlantCraft with its service token |
| ``PLANTCRAFT_APP_KEY_FILE`` | empty | File holding the app key (a Docker secret) |
| ``MODELCRAFT_DATA_DIR`` | ``var`` | Folder of the SQLite database, run results and FMUs |
| ``MODELCRAFT_ROOT_PATH`` | ``/model`` | Path prefix of the interface and API |
| ``MODELCRAFT_RUNNER`` | ``suite`` | ``suite``: PlantCraft's compute workers run the jobs (needs the app key); ``queue``: a runner shares ``MODELCRAFT_JOBS_DIR`` with this server; ``local``: omc on this machine (development only) |
| ``MODELCRAFT_JOBS_DIR`` | ``<data dir>/jobs`` | Where answers are collected (and, with ``queue``, the folder shared with the runner) |
| ``MODELCRAFT_OMC`` | ``omc`` | omc, for the local runner |
| ``MODELCRAFT_LIBRARIES`` | ``/opt/modelica`` | The Modelica libraries, for the local runner |
| ``MODELCRAFT_ALLOW_EXTERNAL`` | ``false`` | Allow external functions (C code) in models |
| ``MODELCRAFT_CHECK_SECONDS`` | ``120`` | Time limit of a check or a diagram |
| ``MODELCRAFT_RUN_SECONDS`` | ``600`` | Time limit of a simulation or an FMU export |
| ``MODELCRAFT_RUN_WORKERS`` | ``2`` | Runs at the same time |
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from plantcraft_sdk.server.settings import AppSettings, env_flag, env_number, env_text

from modelcraft import APP_ID

RUNNERS = ("suite", "queue", "local")


@dataclass
class Settings(AppSettings):
    APP_ID = APP_ID

    root_path: str = "/model"
    runner: str = "suite"
    jobs_dir: Path | None = None
    omc: str = "omc"
    libraries: Path = Path("/opt/modelica")
    allow_external: bool = False
    check_seconds: float = 120.0
    run_seconds: float = 600.0
    run_workers: int = 2
    # Simulations of one sweep handed to the runner together (built once).
    run_batch: int = 10
    # The most simulations one study may make, and the longest time limit a study may ask.
    study_max_runs: int = 500
    max_run_seconds: float = 6 * 3600.0
    examples: bool = True
    # The example study, queued once at the first start (round 9, D13).
    example_study: bool = True

    @property
    def jobs_path(self) -> Path:
        return self.jobs_dir or self.data_dir / "jobs"

    @classmethod
    def from_environment(cls) -> Settings:
        jobs = env_text("MODELCRAFT_JOBS_DIR")
        return cls(
            **cls.common(APP_ID, "/model"),
            runner=runner if (runner := env_text("MODELCRAFT_RUNNER")) in RUNNERS else "suite",
            jobs_dir=Path(jobs).expanduser() if jobs else None,
            omc=env_text("MODELCRAFT_OMC", "omc"),
            libraries=Path(env_text("MODELCRAFT_LIBRARIES", "/opt/modelica")),
            allow_external=env_flag("MODELCRAFT_ALLOW_EXTERNAL", False),
            check_seconds=max(10.0, env_number("MODELCRAFT_CHECK_SECONDS", 120.0) or 120.0),
            run_seconds=max(10.0, env_number("MODELCRAFT_RUN_SECONDS", 600.0) or 600.0),
            run_workers=max(1, int(env_number("MODELCRAFT_RUN_WORKERS", 2) or 2)),
            run_batch=max(1, min(100, int(env_number("MODELCRAFT_RUN_BATCH", 10) or 10))),
            study_max_runs=max(1, int(env_number("MODELCRAFT_STUDY_MAX_RUNS", 500) or 500)),
            max_run_seconds=max(
                60.0, env_number("MODELCRAFT_MAX_RUN_SECONDS", 6 * 3600.0) or 6 * 3600.0
            ),
            examples=env_flag("MODELCRAFT_EXAMPLES", True),
            example_study=env_flag("MODELCRAFT_EXAMPLE_STUDY", True),
        )
