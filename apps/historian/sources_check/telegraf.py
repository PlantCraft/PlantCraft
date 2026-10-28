"""The gateway's Telegraf for the source checks: the binary of the image the suite pins.

``HISTCRAFT_TELEGRAF`` names a binary to use instead. Otherwise the image pinned by digest in
``deploy/compose.yaml`` is read from Docker Hub (no Docker needed), each layer checked against
its SHA-256, and ``usr/bin/telegraf`` kept in ``~/.cache/plantcraft/``.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = "https://registry-1.docker.io/v2/library/telegraf"
INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def pinned() -> tuple[str, str]:
    """The (version, digest) of the gateway image in the suite's compose file."""

    text = (ROOT / "deploy" / "compose.yaml").read_text()
    found = re.search(r"telegraf:([\d.]+)@(sha256:[0-9a-f]{64})", text)
    if not found:
        raise RuntimeError("deploy/compose.yaml pins no telegraf image")
    return found.group(1), found.group(2)


def _get(url: str, token: str, accept: str = "") -> bytes:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    if accept:
        request.add_header("Accept", accept)
    with urllib.request.urlopen(request, timeout=120) as answer:  # noqa: S310 (fixed https URL)
        return answer.read()


def _checked(data: bytes, digest: str) -> bytes:
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError(f"{digest}: what the registry sent does not match the digest")
    return data


def binary() -> Path:
    """A Telegraf binary to run: ``HISTCRAFT_TELEGRAF``, the cache, or a fresh download."""

    given = os.environ.get("HISTCRAFT_TELEGRAF")
    if given:
        return Path(given)
    version, digest = pinned()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}[
        platform.machine().lower()
    ]
    cache = Path.home() / ".cache" / "plantcraft" / f"telegraf-{version}-{arch}-{digest[7:19]}"
    if cache.exists():
        return cache
    token_url = (
        "https://auth.docker.io/token?service=registry.docker.io"
        "&scope=repository:library/telegraf:pull"
    )
    with urllib.request.urlopen(token_url, timeout=60) as answer:  # noqa: S310
        token = json.load(answer)["token"]
    index = json.loads(_checked(_get(f"{REGISTRY}/manifests/{digest}", token, INDEX), digest))
    image = next(
        item["digest"]
        for item in index["manifests"]
        if item.get("platform", {}).get("architecture") == arch
        and item.get("platform", {}).get("os") == "linux"
    )
    manifest = json.loads(_checked(_get(f"{REGISTRY}/manifests/{image}", token, MANIFEST), image))
    for layer in reversed(manifest["layers"]):  # the binary sits in one of the last layers
        blob = _checked(_get(f"{REGISTRY}/blobs/{layer['digest']}", token), layer["digest"])
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as archive:
            try:
                member = archive.getmember("usr/bin/telegraf")
            except KeyError:
                continue
            data = archive.extractfile(member)
            assert data is not None
            cache.parent.mkdir(parents=True, exist_ok=True)
            partial = cache.with_suffix(".part")
            partial.write_bytes(data.read())
            partial.chmod(0o755)
            partial.replace(cache)
            return cache
    raise RuntimeError("usr/bin/telegraf is in no layer of the pinned image")
