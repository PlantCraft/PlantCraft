"""Write the image's software bill of materials (CycloneDX 1.5 JSON) to stdout.

Run inside the image after the install (Dockerfile): every Python distribution installed, and,
when given, the frontend packages bundled into /app/ui (from package-lock.json, without the
development-only ones). PlantCraft's bundle copies the result from /app/sbom.json.

    python sbom.py [frontend/package-lock.json] > /app/sbom.json
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path


def _license(dist: metadata.Distribution) -> list[dict]:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return [{"expression": expression}]
    names = [
        c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if "License ::" in c
    ]
    if names:
        return [{"license": {"name": name}} for name in names]
    text = (meta.get("License") or "").strip()
    return [{"license": {"name": text.splitlines()[0][:100]}}] if text else []


def python_components() -> list[dict]:
    seen: dict[str, dict] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if not name or name.lower() in seen:
            continue
        version = dist.version
        seen[name.lower()] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
            "licenses": _license(dist),
        }
    return sorted(seen.values(), key=lambda c: c["name"].lower())


def npm_components(lock_file: Path) -> list[dict]:
    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    out = []
    for path, package in (lock.get("packages") or {}).items():
        if not path or package.get("dev") or "version" not in package:
            continue
        name = path.split("node_modules/")[-1]
        component = {
            "type": "library",
            "name": name,
            "version": package["version"],
            "purl": f"pkg:npm/{name.replace('@', '%40')}@{package['version']}",
        }
        if package.get("license"):
            component["licenses"] = [{"expression": package["license"]}]
        out.append(component)
    return sorted(out, key=lambda c: (c["name"], c["version"]))


def main(argv: list[str]) -> None:
    app = tomllib.loads(
        Path(os.environ.get("HISTCRAFT_APP_DIR", "/app"), "app.toml").read_text(encoding="utf-8")
    )["app"]
    components = python_components()
    if argv:
        components += npm_components(Path(argv[0]))
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": {
                "type": "application",
                "name": app["name"],
                "version": app["version"],
                "licenses": [{"expression": app["license"]}],
            },
        },
        "components": components,
    }
    json.dump(document, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1:])
