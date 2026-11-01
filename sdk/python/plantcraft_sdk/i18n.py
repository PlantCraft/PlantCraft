"""User-facing text in the person's language, for the SDK and every app of the suite.

English is the source text and the catalog key: ``t("Loop {loop} not found.", loop=loop_id)``.
Each module keeps its translations in ``locales/<language>.json`` next to its code
(docs/translations.md); an app adds its folder once, in its ``i18n`` module:

    use_catalogs(Path(__file__).with_name("locales"))

and the SDK's own catalog (``plantcraft_sdk/locales``) is always under it. A text missing from
the catalogs is English.

The language of a request is the one the page chose, in the ``X-Language`` header or the
suite's ``processcraft_language`` cookie (``@plantcraft/ui`` writes both, English while the
installation keeps translations off); the app server reads it in ``LanguageMiddleware``
(``plantcraft_sdk.server.web.mount`` adds it). Work outside a request is English.

PlantCraft itself has its own catalogs and request handling (``plantcraft.i18n``) and installs
them here with ``install(t, current_language)``, so text worded inside the SDK follows them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar, Token
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_LANGUAGE = "en"
LANGUAGES = {"en": "English", "pt-BR": "Português (Brasil)"}
COOKIE = "processcraft_language"
HEADER = "x-language"
LOCALES = Path(__file__).with_name("locales")

_translate: Callable[..., str] | None = None
_installed_language: Callable[[], str] | None = None
_folders: list[Path] = [LOCALES]
_language: ContextVar[str | None] = ContextVar("plantcraft_sdk_language", default=None)


def install(translate: Callable[..., str], language: Callable[[], str] | None = None) -> None:
    """Route ``t`` (and ``current_language``) through the host's own functions."""

    global _translate, _installed_language
    _translate = translate
    _installed_language = language


def use_catalogs(*folders: Path) -> None:
    """Add a module's ``locales`` folders; later folders win over earlier ones."""

    for folder in folders:
        if folder not in _folders:
            _folders.append(Path(folder))
    catalog.cache_clear()


def normalize(value: str | None) -> str | None:
    """A supported language code for ``value`` ("pt", "pt_br", "pt-BR,en;q=0.8"), or None."""

    for part in (value or "").split(","):
        code = part.split(";")[0].strip().replace("_", "-").lower()
        if not code:
            continue
        for language in LANGUAGES:
            if code == language.lower() or code.split("-")[0] == language.split("-")[0].lower():
                return language
    return None


@lru_cache(maxsize=None)
def catalog(language: str) -> dict[str, str]:
    """Every catalog of ``language``, merged (empty for English)."""

    merged: dict[str, str] = {}
    if language == DEFAULT_LANGUAGE:
        return merged
    for folder in _folders:
        path = folder / f"{language}.json"
        if path.is_file():
            merged.update(json.loads(path.read_text(encoding="utf-8")))
    return merged


def set_language(value: str | None) -> Token:
    return _language.set(normalize(value))


def reset_language(token: Token) -> None:
    _language.reset(token)


def current_language() -> str:
    if _installed_language is not None:
        return _installed_language()
    return _language.get() or DEFAULT_LANGUAGE


def t(text: str, /, **values: object) -> str:
    """``text`` (English) in the current language, with ``{name}`` fields filled in."""

    if _translate is not None:
        return _translate(text, **values)
    translated = catalog(current_language()).get(text) or text
    return translated.format(**values) if values else translated


def request_language(headers: dict[str, str], cookies: dict[str, str]) -> str | None:
    """The language a request asks for: the page's header, else the suite's cookie."""

    return normalize(headers.get(HEADER)) or normalize(cookies.get(COOKIE))


class LanguageMiddleware:
    """Answer each request in the language its page chose (plain ASGI, so the language is set
    for the endpoint's own context, threads included)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[str, str] = {}
        cookies: dict[str, str] = {}
        for name, value in scope.get("headers") or []:
            key = name.decode("latin-1").lower()
            if key == HEADER:
                headers[HEADER] = value.decode("latin-1")
            elif key == "cookie":
                for part in value.decode("latin-1").split(";"):
                    cookie_name, _, cookie_value = part.strip().partition("=")
                    cookies.setdefault(cookie_name, cookie_value)
        token = _language.set(request_language(headers, cookies))
        try:
            await self.app(scope, receive, send)
        finally:
            _language.reset(token)
