#!/usr/bin/env python3
"""A stand-in for the Docker CLI in the installer tests: records every call, runs nothing.

Environment: FAKE_DOCKER_DIR (its log and state), FAKE_DOCKER_FAIL (comma-separated
``up:<service>``, ``load``), FAKE_DOCKER_WRONG_ID (``load`` tags another image id).
The helper container's script runs for real with ``/d`` mapped to the bind source and
``chown`` left out, so the files it would create appear where Docker would put them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

HOME = Path(os.environ["FAKE_DOCKER_DIR"])
FAIL = set(filter(None, os.environ.get("FAKE_DOCKER_FAIL", "").split(",")))


def state() -> dict:
    try:
        return json.loads((HOME / "state.json").read_text())
    except (OSError, ValueError):
        return {"images": {}, "running": []}


def save(value: dict) -> None:
    (HOME / "state.json").write_text(json.dumps(value))


def main(args: list[str]) -> int:
    HOME.mkdir(parents=True, exist_ok=True)
    with (HOME / "calls.jsonl").open("a") as log:
        log.write(json.dumps(args) + "\n")
    current = state()
    if args[:1] == ["load"]:
        if "load" in FAIL:
            print("Error: archive/tar: invalid tar header", file=sys.stderr)
            return 1
        with tarfile.open(args[args.index("-i") + 1]) as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            index = json.load(archive.extractfile("index.json"))
        digest = index["manifests"][0]["digest"]
        if os.environ.get("FAKE_DOCKER_WRONG_ID"):
            digest = "sha256:" + "0" * 64
        for tag in manifest[0]["RepoTags"]:
            current["images"][tag] = digest
            print(f"Loaded image: {tag}")
        save(current)
        return 0
    if args[:2] == ["image", "inspect"]:
        ref = args[-1]
        if ref not in current["images"]:
            print(f"Error: No such image: {ref}", file=sys.stderr)
            return 1
        print(current["images"][ref])
        return 0
    if args[:1] == ["compose"] and "ps" in args:
        for name in current["running"]:
            print(json.dumps({"Service": name, "Name": f"pc-{name}", "State": "running"}))
        return 0
    if args[:1] == ["compose"] and "images" in args:
        print("[]")
        return 0
    if args[:1] == ["compose"] and "logs" in args:
        service = args[-1]
        print(f'{{"level": "info", "app": "{service}", "message": "started"}}')
        print("GET /api/x Authorization: Bearer sekret-token-123 200")
        return 0
    if args[:1] in (["version"], ["info"]):
        print('{"ServerVersion": "fake"}')
        return 0
    if args[:1] == ["compose"]:
        service = args[-1]
        if "up" in args:
            if f"up:{service}" in FAIL:
                print(f"container {service} is unhealthy", file=sys.stderr)
                return 1
            if service not in current["running"]:
                current["running"].append(service)
        elif "rm" in args:
            current["running"] = [item for item in current["running"] if item != service]
        save(current)
        return 0
    if args[:1] == ["ps"]:
        # The operations driver runs while FAKE_DOCKER_DRIVER is set.
        print("f00d" if os.environ.get("FAKE_DOCKER_DRIVER") else "")
        return 0
    if args[:1] == ["run"] and "processcraft-ops" in args:
        return 0  # the operations driver: recorded, run by tests/test_ops_driver.py itself
    if args[:1] == ["run"]:
        mount = args[args.index("-v") + 1]
        source = mount.rsplit(":", 1)[0]
        script = args[-1]
        steps = [step for step in script.split(" && ") if not step.strip().startswith("chown")]
        command = " && ".join(steps).replace("/d/", f"{source}/")
        return subprocess.run(["sh", "-c", command]).returncode
    print(f"fake docker: unsupported {args}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
