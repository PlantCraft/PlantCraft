"""Small allowlist of end-user documentation shown in the application.

Each guide lives in ``docs/<language>/<slug>.md``. English (``docs/en``) is
the source; a translation that is missing falls back to it.
"""

from __future__ import annotations

from pathlib import Path

from processcraft.i18n import DEFAULT_LANGUAGE, current_language, t

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = PROJECT_ROOT / "docs"

# English labels; they are translated with t() when served, never at import.
DOCS = {
    "start": {
        "title": "Getting started",
        "description": "An hour with the demo plant: one sticky valve followed through every app.",
        "slug": "getting-started",
        "category": "Getting started",
    },
    "guide": {
        "title": "User guide",
        "description": "Sign in, the Overview, assets, actions, messages, people and groups.",
        "slug": "user-guide",
        "category": "Getting started",
    },
    "operations": {
        "title": "How the suite works",
        "description": "PlantCraft in the middle, each app in its own container, data through API v1.",
        "slug": "how-it-works",
        "category": "Getting started",
    },
    "configuration": {
        "title": "Configuration file",
        "description": "By script: set an installation up at once, sources, signals, assets and loops from Excel or JSON.",
        "slug": "configuration-file",
        "category": "Quick reference",
    },
    "running": {
        "title": "Running the suite",
        "description": "For administrators: the time zone, Health, Backups and Updates.",
        "slug": "running-the-suite",
        "category": "Settings",
    },
    "sizing": {
        "title": "Sizing the server",
        "description": "CPU, memory and disk for your plant's size, from measured numbers.",
        "slug": "sizing",
        "category": "Settings",
    },
    "notebooks": {
        "title": "Notebooks",
        "description": "Python in the browser with the plant's data, and the same notebook on your computer.",
        "slug": "notebooks",
        "category": "Getting started",
    },
    "glossary": {
        "title": "Concepts",
        "description": "Asset, signal, role, group, app, app key and token.",
        "slug": "concepts",
        "category": "Quick reference",
    },
    "stack": {
        "title": "Stack",
        "description": "The libraries the suite uses by area, their licences, and what we wrote ourselves.",
        "slug": "stack",
        "category": "Quick reference",
    },
}


def document_index() -> list[dict[str, str]]:
    """The guides with their labels in the current language."""

    return [
        {
            "document_id": key,
            "title": t(item["title"]),
            "description": t(item["description"]),
            "category": t(item["category"]),
        }
        for key, item in DOCS.items()
    ]


def read_document(document_id: str) -> str:
    """The guide's Markdown in the current language, or in English when not translated."""

    item = DOCS.get(document_id) or DOCS["operations"]
    root = DOCS_ROOT.resolve()
    for language in dict.fromkeys((current_language(), DEFAULT_LANGUAGE)):
        path = (DOCS_ROOT / language / f"{item['slug']}.md").resolve()
        if root not in path.parents:
            raise ValueError("Document outside the allowed folder.")
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(item["slug"])
