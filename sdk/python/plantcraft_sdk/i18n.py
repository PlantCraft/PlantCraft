"""Translation hook for user-facing text produced inside the SDK.

The SDK has no catalogs of its own: English is the source text. A host that
translates (PlantCraft, or an app with its own catalogs) installs its
functions once with ``install(t, current_language)``; until then ``t`` only
fills in ``{name}`` fields and the language is English.
"""

from __future__ import annotations

from collections.abc import Callable

_translate: Callable[..., str] | None = None
_language: Callable[[], str] | None = None


def install(translate: Callable[..., str], language: Callable[[], str] | None = None) -> None:
    """Route ``t`` (and ``current_language``) through the host's own functions."""

    global _translate, _language
    _translate = translate
    _language = language


def t(text: str, /, **values: object) -> str:
    """``text`` (English) in the current language, with ``{name}`` fields filled in."""

    if _translate is not None:
        return _translate(text, **values)
    return text.format(**values) if values else text


def current_language() -> str:
    return _language() if _language is not None else "en"
