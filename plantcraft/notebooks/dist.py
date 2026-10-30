"""JupyterLite's build as the browser installs it (docs/en/notebooks.md, "Run in the browser").

The files are served under a path that names their build (``/notebooks/lite/v/<build>/``), with
a year of browser cache: a person downloads Python once, and a new build has new paths, so it is
never mixed with an old one. The Notebooks page fetches every file once ("Install Python in this
browser", with its progress) from the list here; afterwards JupyterLab opens from the cache.
Pages and lists (``.html``, ``.json``, the service worker) are always asked again.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

# Asked again on every visit: the pages, JupyterLite's settings and lists, its service worker.
FRESH_SUFFIXES = {".html", ".json"}
FRESH_NAMES = {"service-worker.js"}

_cache: dict[tuple[str, float], dict[str, Any]] = {}
_lock = threading.Lock()


def is_fresh(path: Path) -> bool:
    return path.suffix in FRESH_SUFFIXES or path.name in FRESH_NAMES


def build_info(root: Path) -> dict[str, Any] | None:
    """``{"build", "bytes", "files"}`` of the build in ``root``, or None when there is none.

    ``build`` changes when any file is added, removed or changes size; ``files`` are the paths
    the browser keeps (everything but what is always asked again), with ``bytes`` their total.
    """

    config = root / "jupyter-lite.json"
    if not config.is_file():
        return None
    key = (str(root), config.stat().st_mtime)
    with _lock:
        if key in _cache:
            return _cache[key]
        digest = hashlib.sha256(config.read_bytes())
        files: list[str] = []
        total = 0
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            size = path.stat().st_size
            digest.update(f"{relative}\0{size}\n".encode())
            if not is_fresh(path):
                files.append(relative)
                total += size
        info = {"build": digest.hexdigest()[:12], "bytes": total, "files": files}
        _cache.clear()
        _cache[key] = info
        return info
