"""An app's manifest (``app.toml``) and help pages, as ``/api/meta`` and ``/api/help`` serve them.

``app.toml`` at the repository root is the single source of an app's metadata
(``docs/app-standard.md``, section 4); ``/api/meta`` serves it with the build's revision. Help
pages are the Markdown files of ``docs/help`` (a translation in ``docs/help/<language>/``, see
``plantcraft_sdk.i18n.localized``). Both are found in ``<APP>_APP_DIR`` (``/app`` in
the image), else in the source checkout::

    FILES = AppFiles("twincraft", Path(__file__).resolve().parents[2],
                     help_categories={"twins": "Getting started", "models": "Building twins"})
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from plantcraft_sdk.i18n import localized, t

HELP_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
OTHER_CATEGORY = "More"


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


class AppFiles:
    """``app.toml`` and ``docs/help`` of one app.

    ``source_root`` is the repository root of a source checkout (used when ``<APP>_APP_DIR`` is
    not set). ``help_categories`` names each guide's folder in the help browser (``"A/B"``
    nests), in this order; a page not listed comes last, under "More".
    """

    def __init__(
        self,
        app_id: str,
        source_root: str | Path,
        *,
        help_categories: Mapping[str, str] | None = None,
    ):
        self.app_id = app_id
        self.env_prefix = app_id.upper()
        self.source_root = Path(source_root)
        self.help_categories = dict(help_categories or {})
        self._manifest: dict[str, Any] | None = None

    def app_dir(self) -> Path:
        configured = os.environ.get(f"{self.env_prefix}_APP_DIR", "").strip()
        return Path(configured) if configured else self.source_root

    def manifest(self) -> dict[str, Any]:
        """``app.toml`` as a dictionary, read once; empty when missing (a bare wheel install)."""

        if self._manifest is None:
            path = self.app_dir() / "app.toml"
            if not path.is_file():
                return {}
            with path.open("rb") as handle:
                self._manifest = tomllib.load(handle)
        return self._manifest

    def clear(self) -> None:
        """Forget the manifest read (tests that point ``<APP>_APP_DIR`` elsewhere)."""

        self._manifest = None

    def revision(self) -> str:
        return os.environ.get(f"{self.env_prefix}_REVISION", "").strip() or "unknown"

    def meta(self) -> dict[str, Any]:
        """What ``/api/meta`` answers: the manifest plus the build revision (no secrets)."""

        return {**self.manifest(), "revision": self.revision()}

    def help_folder(self) -> Path:
        return self.app_dir() / "docs" / "help"

    def help_pages(self) -> list[dict[str, str]]:
        """The help index, ``{id, title, category}`` per ``docs/help/<id>.md``: the guides of
        ``help_categories`` first in its order, the others by file name."""

        folder = self.help_folder()
        if not folder.is_dir():
            return []
        pages = []
        for path in sorted(folder.glob("*.md")):
            if HELP_ID.match(path.stem):
                text = localized(path).read_text(encoding="utf-8")
                category = "/".join(
                    t(part)
                    for part in self.help_categories.get(path.stem, OTHER_CATEGORY).split("/")
                )
                pages.append(
                    {"id": path.stem, "title": _title(text, path.stem), "category": category}
                )
        order = list(self.help_categories)
        return sorted(
            pages, key=lambda page: order.index(page["id"]) if page["id"] in order else len(order)
        )

    def help_page(self, page_id: str) -> dict[str, str] | None:
        """One page as ``{id, title, markdown}``, or None for an unknown id (never a path
        outside the folder)."""

        if not HELP_ID.match(page_id):
            return None
        path = self.help_folder() / f"{page_id}.md"
        if not path.is_file():
            return None
        text = localized(path).read_text(encoding="utf-8")
        return {"id": page_id, "title": _title(text, page_id), "markdown": text}
