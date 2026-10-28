"""The suite's words (docs/glossary.md): a retired word never comes back to the interface of an
area already renamed. Only interface text is read: the strings of `t()` and `tt()`, menu labels,
titles, help and the attributes people read. Ids, routes and API fields keep their words until
the brand's final name (BACKLOG D5b)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INTERFACE = re.compile(
    r"""(?:\b(?:t|tt)\(\s*|\b(?:label|title|body|heading|summary|hint|help|detail|about|description):\s*"""
    r"""|\b(?:placeholder|title|aria-label|detail|description|hint)=)(["'`])((?:\\.|(?!\1).)*)\1"""
)

# Area -> (folder, retired words as patterns over one interface string).
AREAS: dict[str, tuple[str, list[str]]] = {
    "PlantCraft and Desk": (
        "frontend/src",
        [
            r"\bSetup\b",
            r"^Users$",
            r"\bUsers ›",
            r"^Health$",
            r"^Executions$",
            r"^Alarm$",
            r"^Works?$",
            r"\bEvaluate works\b",
        ],
    ),
    "Historian": ("apps/historian/frontend/src", [r"(?<![Ss]et )\b[Pp]oints?\b"]),
    "View": ("apps/view/frontend/src", [r"\b[Cc]ards?\b", r"^Tags$", r"^Alarm$", r"^Attention$"]),
    "Analytics (Link)": (
        "apps/link/frontend/src",
        [
            r"\bLink\b",
            r"\b[Ss]chedules?\b",
            r"\b[Ee]xecutions?\b",
            r"(?<!\{)\b[Ss]ubjects?\b(?!\})",
            r"^Tags$",
            r"^Attention$",
            r"^Alarm$",
            r"\b[Vv]erdicts?\b",
            r"\bSetup\b",
            r"^(Output|Input) series$",
        ],
    ),
    "Models": (
        "apps/models/frontend/src",
        [
            r"\b[Ee]xecutions?\b",
            r"\b[Ee]xperiment\b",
            r"\b[Ii]ntegrators?\b",
            r"^Runs$",
            r"^Group$",
            r"\bLink\b",
        ],
    ),
    "Alarms": (
        "apps/alarms/frontend/src",
        [
            r"\b[Nn]otices?\b",
            r"(?<!\{)\b[Ss]ubjects?\b(?!\})",
            r"\bSetup\b",
            r"^Incoming$",
            r"\b[Pp]oints in a row\b",
            r"^Kinds?$",
            r"\b[Vv]erdicts?\b",
        ],
    ),
}


# Files another open change still rewrites; they join the check once it is merged.
PENDING: set[str] = set()


def _interface_strings(path: Path):
    for match in INTERFACE.finditer(path.read_text(encoding="utf-8")):
        yield match.group(2)


def _sources(folder: str):
    for path in sorted((ROOT / folder).rglob("*")):
        pending = str(path.relative_to(ROOT)) in PENDING
        if path.suffix in {".ts", ".tsx"} and ".test." not in path.name and not pending:
            yield path


def test_retired_words_stay_out_of_the_renamed_interfaces():
    found = []
    for area, (folder, words) in AREAS.items():
        patterns = [re.compile(word) for word in words]
        for path in _sources(folder):
            for text in _interface_strings(path):
                for pattern in patterns:
                    if pattern.search(text):
                        found.append(
                            f"{area}: {path.relative_to(ROOT)}: {text!r} ({pattern.pattern})"
                        )
    assert not found, "Retired words (docs/glossary.md):\n" + "\n".join(found)


def test_the_glossary_lists_every_checked_area():
    glossary = (ROOT / "docs/glossary.md").read_text(encoding="utf-8")
    for folder, _words in AREAS.values():
        assert f"`{folder}`" in glossary, folder


def test_the_check_reads_interface_strings_only():
    sample = 't("Add panel") + label: "Signals" + const cards = []; title={t("Points")}'
    assert [text for text in (m.group(2) for m in INTERFACE.finditer(sample))] == [
        "Add panel",
        "Signals",
        "Points",
    ]
