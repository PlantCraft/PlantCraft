"""Method help pages: one Markdown file per method in ``methods/help/<method_id>.md``.

Each page has the same sections, in this order: what the method detects, its reference papers,
its parameters (each ``- `name` (default X): meaning``), how to read its finding, and its limits.
``tests/test_method_help.py`` checks every registered method has a page, every parameter is
documented and every default written there is the method's real default.

The pages are plain Markdown, readable in the repository; the API serves them parsed into
sections of paragraphs and bullet lists (inline ``code``, ``**bold**`` and ``[links](url)`` are
left to the interface), with the parameter defaults read from the method itself.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from plantcraft_sdk.i18n import localized

from linkcraft.catalog.labels import METHOD_LABELS, PARAMETER_LABELS
from linkcraft.catalog.registry import METHOD_SPECS
from linkcraft.i18n import current_language, t

HELP_DIR = Path(__file__).resolve().parents[1] / "methods" / "help"
SECTIONS = (
    ("detects", "What it detects"),
    ("reference", "Reference"),
    ("parameters", "Parameters"),
    ("reading", "How to read the finding"),
    ("limits", "Limits"),
)
# A translated page writes "(padrão X)" or "(por defecto X)" for "(default X)"
# (methods/help/<language>/, docs/translations.md).
PARAMETER = re.compile(
    r"^`(?P<key>\w+)` \((?:default|padrão|por defecto) (?P<default>[^)]*)\): (?P<meaning>.+)$", re.S
)


def format_default(value: Any) -> str:
    """A default as the help pages write it: ``0.05``, ``200``, ``none``, ``manual, man, m``."""

    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(format_default(item) for item in value)
    return str(value)


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def _blocks(lines: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append({"type": "p", "text": " ".join(paragraph)})
            paragraph.clear()
        if items:
            blocks.append({"type": "ul", "items": list(items)})
            items.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("- "):
            if paragraph:
                flush()
            items.append(stripped[2:])
        elif items and line.startswith("  "):
            items[-1] += " " + stripped
        else:
            if items:
                flush()
            paragraph.append(stripped)
    flush()
    return blocks


def parse(text: str) -> dict[str, Any]:
    """Title and sections (``{id, title, blocks}``) of one help page."""

    title = ""
    sections: list[dict[str, Any]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = []
            sections.append({"title": line[3:].strip(), "lines": current})
        elif current is not None:
            current.append(line)
    # A translated page titles its sections in its language.
    ids = {name: key for key, name in SECTIONS} | {t(name): key for key, name in SECTIONS}
    return {
        "title": title,
        "sections": [
            {
                "id": ids.get(section["title"], section["title"].lower().replace(" ", "_")),
                "title": section["title"],
                "blocks": _blocks(section["lines"]),
            }
            for section in sections
        ],
    }


def documented_parameters(page: dict[str, Any]) -> dict[str, dict[str, str]]:
    """``{name: {"default": text, "meaning": text}}`` from the Parameters section."""

    found: dict[str, dict[str, str]] = {}
    for section in page["sections"]:
        if section["id"] != "parameters":
            continue
        for block in section["blocks"]:
            for item in block.get("items", []):
                match = PARAMETER.match(item)
                if match:
                    found[match["key"]] = {
                        "default": match["default"].strip(),
                        "meaning": match["meaning"].strip(),
                    }
    return found


def _page(method_id: str) -> dict[str, Any] | None:
    return _page_in(method_id, current_language())


@lru_cache(maxsize=None)
def _page_in(method_id: str, language: str) -> dict[str, Any] | None:
    path = HELP_DIR / f"{method_id}.md"
    if method_id not in METHOD_SPECS or not path.is_file():
        return None
    return parse(localized(path).read_text(encoding="utf-8"))


def method_help(method_id: str, configured: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """One method's help page, with its parameters' real defaults (``None``: no such method)."""

    page = _page(method_id)
    if page is None:
        return None
    spec = METHOD_SPECS[method_id]
    documented = documented_parameters(page)
    parameters = []
    for key, field in spec.parameter_schema.model_fields.items():
        default = field.get_default(call_default_factory=True)
        label = PARAMETER_LABELS.get(key, (field.title or key, field.description or ""))
        parameters.append(
            {
                "key": key,
                "title": t(label[0]),
                "meaning": _sentence((documented.get(key) or {}).get("meaning") or t(label[1])),
                "default": format_default(default),
                "configured": format_default((configured or {})[key])
                if configured and key in configured
                else None,
            }
        )
    metadata = spec.metadata.model_dump(mode="json")
    return {
        "method_id": method_id,
        "label": METHOD_LABELS.get(method_id, metadata["name"]),
        "title": page["title"],
        "summary": next(
            (
                block["text"]
                for section in page["sections"]
                if section["id"] == "detects"
                for block in section["blocks"]
                if block["type"] == "p"
            ),
            "",
        ),
        "sections": [section for section in page["sections"] if section["id"] != "parameters"],
        "parameters": parameters,
        "references": metadata.get("references", []),
        "formula": metadata.get("implemented_formula"),
        "maturity": metadata.get("maturity"),
        "required_signals": metadata.get("required_signals", []),
    }


def help_index() -> list[dict[str, Any]]:
    """Every method with a help page: id, label and the first paragraph of what it detects."""

    found = []
    for method_id in METHOD_SPECS:
        page = method_help(method_id)
        if page is not None:
            found.append(
                {"method_id": method_id, "label": page["label"], "summary": page["summary"]}
            )
    return found
