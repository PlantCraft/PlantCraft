"""Historian's ``app.toml`` and help pages (``plantcraft_sdk.server.files``).

Found in ``HISTCRAFT_APP_DIR`` (``/app`` in the image), else in the source checkout. The help
browser files each guide in its folder, in this order.
"""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk.server.files import OTHER_CATEGORY, AppFiles

HELP_CATEGORIES = {
    "overview": "Getting started",
    "sources": "Collecting data",
    "points": "Collecting data",
    "compression": "Storing data",
    "imports": "Collecting data",
    "export": "Using the data",
    "settings": "Administration",
}
FILES = AppFiles("histcraft", Path(__file__).resolve().parents[2], help_categories=HELP_CATEGORIES)

app_dir = FILES.app_dir
manifest = FILES.manifest
help_pages = FILES.help_pages
help_page = FILES.help_page

__all__ = [
    "FILES",
    "HELP_CATEGORIES",
    "OTHER_CATEGORY",
    "app_dir",
    "help_page",
    "help_pages",
    "manifest",
]
