"""The only outbound requests of app management, both started by an administrator.

- The online catalog, when ``PLANTCRAFT_APP_CATALOG_URL`` is set (off by default and in
  isolated plants): its signed index and the packages it lists, from that address only.
- The health check of an external app's address, when an administrator registers it.

Redirects are never followed, sizes are capped and nothing is sent but a GET.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

from processcraft.apps import package as pkg

TIMEOUT = (5, 30)
HEALTH_TIMEOUT = 4


class RemoteError(Exception):
    """The catalog or an address could not be used; the message says why."""


def catalog_base(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise RemoteError("PLANTCRAFT_APP_CATALOG_URL must be an http(s) address without a user")
    return url if url.endswith("/") else url + "/"


def _get(url: str, limit: int) -> bytes:
    try:
        with requests.get(url, timeout=TIMEOUT, stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise RemoteError(f"{_safe(url)} answered {response.status_code}")
            body = bytearray()
            for chunk in response.iter_content(64 * 1024):
                body += chunk
                if len(body) > limit:
                    raise RemoteError(f"{_safe(url)} sent more than {limit} bytes")
            return bytes(body)
    except requests.RequestException as exc:
        raise RemoteError(f"cannot reach {_safe(url)}: {type(exc).__name__}") from exc


def _safe(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname or ''}{f':{parts.port}' if parts.port else ''}{parts.path}"


def fetch_index(base: str, trusted: dict[str, Any]) -> list[dict[str, Any]]:
    """The apps of the catalog at ``base``, after checking the index signature."""

    base = catalog_base(base)
    raw = _get(urljoin(base, "index.json"), pkg.INDEX_LIMIT)
    signature = _get(urljoin(base, "index.json.sig"), pkg.KiB)
    try:
        return pkg.verify_index(raw, signature, trusted)
    except pkg.PackageError as exc:
        raise RemoteError(f"the catalog index is not trusted: {exc}") from exc


def package_url(base: str, entry: dict[str, Any]) -> str:
    """Where a listed package is; always under the catalog's own address."""

    base = catalog_base(base)
    url = urljoin(base, entry["package"])
    if not url.startswith(base):
        raise RemoteError("the catalog lists a package outside its own address")
    return url


def download(base: str, entry: dict[str, Any], target: Path, max_bytes: int) -> str:
    """Downloads a listed package to ``target``; returns its SHA-256 (checked against the index)."""

    if entry["size"] > max_bytes:
        raise RemoteError("the package is larger than this server accepts")
    url = package_url(base, entry)
    digest, size = hashlib.sha256(), 0
    try:
        with requests.get(url, timeout=TIMEOUT, stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise RemoteError(f"{_safe(url)} answered {response.status_code}")
            with target.open("wb") as out:
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > entry["size"]:
                        raise RemoteError("the package is larger than the catalog says")
                    digest.update(chunk)
                    out.write(chunk)
    except requests.RequestException as exc:
        raise RemoteError(f"cannot download {_safe(url)}: {type(exc).__name__}") from exc
    if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
        raise RemoteError("the downloaded package does not match the SHA-256 in the catalog")
    return digest.hexdigest()


def check_health(url: str) -> dict[str, Any]:
    """One GET to an external app's address: did it answer, and with which status."""

    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if url.startswith("/"):
        return {
            "ok": None,
            "status": None,
            "detail": "Served through this server's proxy; not checked from PlantCraft.",
            "checked_at": checked,
        }
    try:
        with requests.get(
            url, timeout=HEALTH_TIMEOUT, stream=True, allow_redirects=False
        ) as response:
            status = response.status_code
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status": None,
            "detail": f"No answer from {_safe(url)} ({type(exc).__name__}).",
            "checked_at": checked,
        }
    return {
        "ok": status < 500,
        "status": status,
        "detail": f"{_safe(url)} answered {status}.",
        "checked_at": checked,
    }
