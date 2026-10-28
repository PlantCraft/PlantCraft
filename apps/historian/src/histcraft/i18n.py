"""One hook for user-facing text: ``t("Point {tag} not found.", tag=tag)``.

HistCraft is English only for now (owner decision, 2026-10-19). Every string a
person reads still goes through ``t()`` so a catalog can be installed later.
"""

from __future__ import annotations

from plantcraft_sdk.i18n import current_language, t

__all__ = ["current_language", "t"]
