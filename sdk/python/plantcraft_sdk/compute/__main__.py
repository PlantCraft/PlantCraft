"""``python -m plantcraft_sdk.compute gateway|executor``: the two parts of a compute worker."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from plantcraft_sdk.compute import folder
from plantcraft_sdk.compute.executor import Executor
from plantcraft_sdk.compute.gateway import HEALTH, Gateway, GatewayError
from plantcraft_sdk.server.workers import available_cpus


def _int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value.isdigit() else default


def _gateway(args: argparse.Namespace) -> int:
    import httpx

    verify: bool | str = args.ca_file or True
    http = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), verify=verify)
    jobs = Path(args.jobs)
    credential_file = Path(args.credential_file)
    credential = ""
    if credential_file.is_file():
        credential = credential_file.read_text(encoding="utf-8").strip()
    if not credential:
        if not args.code:
            print(
                "No credential yet: give --code (PlantCraft › Settings › Compute › Add worker).",
                file=sys.stderr,
            )
            return 2
        gateway = Gateway(args.platform, jobs, "", http=http)
        try:
            credential = Gateway.enroll(args.platform, args.code, gateway.executors(), http=http)
        except GatewayError as exc:
            print(f"PlantCraft refused the code: {exc}", file=sys.stderr)
            return 2
        credential_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(credential_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(credential)
        print(f"Enrolled; the credential is in {credential_file}.", flush=True)
    gateway = Gateway(
        args.platform, jobs, credential, http=http, max_bytes=args.max_mb * 1024 * 1024
    )
    ended = threading.Event()

    def terminate(*_: object) -> None:
        ended.set()
        gateway.stop.set()

    signal.signal(signal.SIGTERM, terminate)
    print(f"compute gateway: {args.platform}, jobs in {jobs}", flush=True)
    try:
        gateway.serve()
    except GatewayError as exc:
        print(f"PlantCraft refused this worker: {exc}", file=sys.stderr)
    if not ended.is_set():
        # Revoked (or removed): it waits to be stopped instead of exiting, which a restart
        # policy would turn into a loop; its healthcheck goes unhealthy meanwhile.
        print("This worker takes no task: remove it, or enroll it again.", file=sys.stderr)
        # Its healthcheck reads this file: unhealthy at once, not a minute later.
        (jobs / HEALTH).unlink(missing_ok=True)
        ended.wait()
        return 3
    return 0


def _installed_version(app: str) -> str | None:
    """The version of the app's package installed in this image (the app's id is its name)."""

    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(app)
    except PackageNotFoundError:
        return None


def _executor(args: argparse.Namespace) -> int:
    executor = Executor(
        Path(args.jobs),
        app=args.app,
        version=args.version or _installed_version(args.app),
        handler=args.handler,
        environment=args.environment,
        workers=args.workers,
        memory_mb=args.memory_mb,
        max_file_bytes=args.max_mb * 1024 * 1024,
    )
    signal.signal(signal.SIGTERM, lambda *_: executor.stop.set())
    print(
        f"compute executor {args.app} {args.version} ({executor.environment}): "
        f"{args.workers} slots",
        flush=True,
    )
    executor.serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("PLANTCRAFT_LOG_LEVEL", "INFO").upper())
    parser = argparse.ArgumentParser(prog="python -m plantcraft_sdk.compute")
    commands = parser.add_subparsers(dest="command", required=True)
    gateway = commands.add_parser("gateway", help="talk to PlantCraft: take tasks, send answers")
    gateway.add_argument(
        "--platform",
        default=os.environ.get("PLANTCRAFT_URL", ""),
        required=not os.environ.get("PLANTCRAFT_URL"),
    )
    gateway.add_argument("--jobs", default=os.environ.get("PLANTCRAFT_COMPUTE_JOBS", "/jobs"))
    gateway.add_argument(
        "--credential-file",
        default=os.environ.get("PLANTCRAFT_COMPUTE_CREDENTIAL_FILE", "/data/worker-credential"),
    )
    gateway.add_argument("--code", default=os.environ.get("PLANTCRAFT_COMPUTE_CODE", ""))
    gateway.add_argument("--ca-file", default=os.environ.get("PLANTCRAFT_CA_FILE", ""))
    gateway.add_argument("--max-mb", type=int, default=_int("PLANTCRAFT_COMPUTE_MAX_MB", 64))
    executor = commands.add_parser("executor", help="run one app's tasks (no network)")
    executor.add_argument("--app", required=True)
    executor.add_argument(
        "--version", default="", help="default: the installed package named --app"
    )
    executor.add_argument("--jobs", default=os.environ.get("PLANTCRAFT_COMPUTE_JOBS", "/jobs"))
    executor.add_argument("--handler", required=True, help="module:function")
    executor.add_argument(
        "--environment",
        default=os.environ.get("PLANTCRAFT_COMPUTE_ENVIRONMENT", "standard"),
        help="the image's environment (standard: the app's own image)",
    )
    executor.add_argument(
        "--workers",
        type=int,
        default=_int("PLANTCRAFT_COMPUTE_SLOTS", max(1, available_cpus() - 1)),
    )
    executor.add_argument(
        "--memory-mb", type=int, default=_int("PLANTCRAFT_COMPUTE_MEMORY_MB", 2048)
    )
    executor.add_argument("--max-mb", type=int, default=_int("PLANTCRAFT_COMPUTE_MAX_MB", 64))
    args = parser.parse_args(argv)
    if args.command == "gateway":
        return _gateway(args)
    folder.prepare(Path(args.jobs))
    return _executor(args)


if __name__ == "__main__":
    sys.exit(main())
