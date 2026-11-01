"""One hook for user-facing text: ``t("Rule {name} not found.", name=name)``.

English is the source and the key; this app's translations are ``locales/<language>.json``
next to this file, over the SDK's own (docs/translations.md). The page's language comes with
each request (``plantcraft_sdk.i18n.LanguageMiddleware``).
"""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk.i18n import current_language, t, use_catalogs

use_catalogs(Path(__file__).with_name("locales"))

__all__ = ["current_language", "t"]
