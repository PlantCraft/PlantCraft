"""PlantCraft Models's ``app.toml`` and help pages (``plantcraft_sdk.server.files``).

Found in ``MODELCRAFT_APP_DIR`` (``/app`` in the image), else in the source checkout. The help
browser files each guide in its folder, in this order.
"""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk.server.files import OTHER_CATEGORY, AppFiles

HELP_CATEGORIES = {
    "models": "Getting started",
    "blocks": "Building models",
    "simulating": "Simulating",
    "studies": "Simulating",
    "plant-data": "Simulating",
    "fmu": "Exporting FMUs",
    "editor": "Modelica code",
    "diagram": "Modelica code",
    "runner": "Administration",
}
FILES = AppFiles("modelcraft", Path(__file__).resolve().parents[2], help_categories=HELP_CATEGORIES)

app_dir = FILES.app_dir
manifest = FILES.manifest
help_page = FILES.help_page

__all__ = ["FILES", "HELP_CATEGORIES", "OTHER_CATEGORY", "app_dir", "help_page", "manifest"]
