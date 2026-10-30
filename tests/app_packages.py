"""Builds app packages for the tests: ephemeral publisher keys, synthetic `docker save` archives.

Nothing here is a real key or a real image; every test makes its own.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

from plantcraft.apps import package as pkg

SBOM = {
    "spdxVersion": "SPDX-2.3",
    "name": "hello",
    "creationInfo": {"created": "2026-10-19T00:00:00Z"},
    "packages": [
        {"name": "python", "versionInfo": "3.13.16", "licenseConcluded": "PSF-2.0"},
        {"name": "fastapi", "versionInfo": "0.116.1", "licenseDeclared": "MIT"},
    ],
}


def publisher(folder: Path, name: str = "testpub") -> tuple[Path, Path]:
    """A new key pair in ``folder/keys``; returns (private key, trusted folder with the .pub)."""

    private, public = pkg.keygen(name, folder / "keys")
    trusted = folder / "trusted"
    trusted.mkdir(exist_ok=True)
    (trusted / public.name).write_bytes(public.read_bytes())
    return private, trusted


def _add(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def image_tar(
    path: Path,
    image: str,
    *,
    tags: list[str] | None = None,
    index_names: list[str] | None = None,
    repositories: dict[str, Any] | None = None,
    images: int = 1,
    layer: bytes = b"layer",
) -> str:
    """A small archive shaped like `docker save` output; returns the image's index digest."""

    config = json.dumps({"architecture": "amd64", "config": {}}).encode()
    config_hex = hashlib.sha256(config).hexdigest()
    layer_hex = hashlib.sha256(layer).hexdigest()
    index_hex = hashlib.sha256(config + layer).hexdigest()
    entry = {
        "Config": f"blobs/sha256/{config_hex}",
        "RepoTags": tags if tags is not None else [image],
        "Layers": [f"blobs/sha256/{layer_hex}"],
    }
    names = index_names if index_names is not None else [f"docker.io/library/{image}"]
    index = {
        "schemaVersion": 2,
        "manifests": [
            {"digest": f"sha256:{index_hex}", "annotations": {"io.containerd.image.name": name}}
            for name in names
        ],
    }
    with tarfile.open(path, "w") as archive:
        _add(archive, f"blobs/sha256/{config_hex}", config)
        _add(archive, f"blobs/sha256/{layer_hex}", layer)
        _add(archive, "index.json", json.dumps(index).encode())
        _add(archive, "manifest.json", json.dumps([entry] * images).encode())
        if repositories is not None:
            _add(archive, "repositories", json.dumps(repositories).encode())
    return f"sha256:{index_hex}"


def _slot(app_id: str) -> int:
    """A stable number per test app, so each one gets its own port and uid."""

    return int(hashlib.sha256(app_id.encode()).hexdigest(), 16) % 800


def template(
    app_id: str = "hello",
    version: str = "0.1.0",
    *,
    app: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    permissions: dict[str, Any] | None = None,
    **sections: Any,
) -> dict[str, Any]:
    """The sections of an app.toml for a test app (``app``/``runtime`` override single keys)."""

    return {
        "app": {
            "id": app_id,
            "name": app_id.title(),
            "version": version,
            "category": "Testing",
            "summary": "A test app.",
            "description": "A test app, built by the tests.",
            "publisher": "testpub",
            "license": "Apache-2.0",
            **(app or {}),
        },
        # A key given as None is left out (an app that names no port or no uid).
        "runtime": {
            key: value
            for key, value in {
                "prefix": f"/{app_id}/",
                "port": 9000 + _slot(app_id),
                "uid": 10100 + _slot(app_id),
                "health": "/healthz",
                "image": app_id,
                **(runtime or {}),
            }.items()
            if value is not None
        },
        "permissions": permissions
        if permissions is not None
        else {"read": ["assets", "signals"], "write": [], "plant_write": False, "outbound": []},
        **sections,
    }


def build(
    folder: Path,
    key: Path,
    *,
    app_id: str = "hello",
    version: str = "0.1.0",
    compress: bool = False,
    image_kwargs: dict[str, Any] | None = None,
    **fields: Any,
) -> Path:
    """A valid signed package (``image_kwargs`` shape its synthetic image archive)."""

    folder.mkdir(parents=True, exist_ok=True)
    manifest = template(app_id, version, **fields)
    image = folder / f"{app_id}-{version}-image.tar"
    image_tar(image, f"{app_id}:{version}", **(image_kwargs or {}))
    sbom = folder / "sbom.spdx.json"
    sbom.write_text(json.dumps(SBOM))
    out = folder / f"{app_id}-{version}.pcapp"
    pkg.build_package(manifest, image, sbom, key, out, compress=compress)
    return out


def raw(path: Path, members: list[tuple[str, bytes]] | list[tarfile.TarInfo | tuple]) -> Path:
    """A tar with exactly these members: (name, data) pairs or (TarInfo, data) pairs."""

    with tarfile.open(path, "w") as archive:
        for item in members:
            if isinstance(item[0], tarfile.TarInfo):
                info, data = item
                archive.addfile(info, io.BytesIO(data) if data is not None else None)
            else:
                _add(archive, item[0], item[1])
    return path


def members_of(package: Path) -> dict[str, bytes]:
    with tarfile.open(package, "r:*") as archive:
        return {m.name: archive.extractfile(m).read() for m in archive.getmembers()}


def resign(package: Path, key: Path, out: Path, change) -> Path:
    """The package with its manifest changed by ``change(dict)`` and signed again with ``key``."""

    members = members_of(package)
    manifest = json.loads(members["manifest.json"])
    change(manifest)
    data = pkg.manifest_bytes(manifest)
    members["manifest.json"] = data
    members["manifest.sig"] = pkg.sign(data, pkg.load_private_key(key))
    order = ["manifest.json", "manifest.sig", "sbom.spdx.json", "image.tar"]
    return raw(out, [(name, members[name]) for name in order])
