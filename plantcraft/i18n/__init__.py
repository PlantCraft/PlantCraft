"""Interface language: English is the source, other languages are catalogs.

Every user-facing string is written in English and wrapped in ``t()``; the
English text is the catalog key. ``locales/<language>.json`` maps it to the
translation. The language of a request comes from the ``X-Language`` header,
the ``processcraft_language`` cookie or ``Accept-Language`` (see
``plantcraft.api.app``); work running outside a request uses English unless
``PLANTCRAFT_LANGUAGE`` says otherwise.

Translations are off by default while the interface settles: every answer is
English whatever the browser asks for. ``PLANTCRAFT_TRANSLATIONS=1`` turns
the catalogs back on.
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar, Token
from functools import lru_cache
from pathlib import Path

from plantcraft_sdk import i18n as _sdk_i18n

DEFAULT_LANGUAGE = "en"
LANGUAGES = {"en": "English", "pt-BR": "Português (Brasil)"}
COOKIE = "processcraft_language"
# Tells every page of the suite whether to offer other languages (@plantcraft/ui i18n.ts).
TRANSLATIONS_COOKIE = "plantcraft_translations"
LOCALES = Path(__file__).with_name("locales")

_language: ContextVar[str | None] = ContextVar("processcraft_language", default=None)


def translations_on() -> bool:
    return os.environ.get("PLANTCRAFT_TRANSLATIONS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalize(value: str | None) -> str | None:
    """A supported language code for ``value`` ("pt", "pt_br", "pt-BR,en;q=0.8"), or None.

    English for any known language while translations are off."""

    if not translations_on():
        return DEFAULT_LANGUAGE if (value or "").strip() else None
    for part in (value or "").split(","):
        code = part.split(";")[0].strip().replace("_", "-").lower()
        if not code:
            continue
        for language in LANGUAGES:
            if code == language.lower() or code.split("-")[0] == language.split("-")[0].lower():
                return language
    return None


def default_language() -> str:
    return normalize(os.environ.get("PLANTCRAFT_LANGUAGE")) or DEFAULT_LANGUAGE


def current_language() -> str:
    return _language.get() or default_language()


def set_language(value: str | None) -> Token:
    return _language.set(normalize(value))


def reset_language(token: Token) -> None:
    _language.reset(token)


@lru_cache(maxsize=None)
def catalog(language: str) -> dict[str, str]:
    """PlantCraft's catalog over the SDK's (text worded inside the SDK)."""

    path = LOCALES / f"{language}.json"
    if language == DEFAULT_LANGUAGE:
        return {}
    merged = dict(_sdk_i18n.catalog(language))
    if path.is_file():
        merged.update(json.loads(path.read_text(encoding="utf-8")))
    return merged


def t(text: str, /, **values: object) -> str:
    """``text`` (English) in the current language, with ``{name}`` fields filled in."""

    translated = catalog(current_language()).get(text, text) or text
    return translated.format(**values) if values else translated


# Text worded inside the SDK (the @method contracts and findings) goes through this catalog.
_sdk_i18n.install(t, current_language)
