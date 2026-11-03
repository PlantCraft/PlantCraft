"""How complete a module's translations are: ``python -m plantcraft_sdk.i18n_check <folder>``.

Every user-facing text is English in the code, wrapped in ``t("...")``, and each translation is
a catalog ``locales/<language>.json`` next to the code that uses it (docs/translations.md). This
check finds every catalog folder under the given folders and, for each one, the English texts
its code passes to ``t()``:

- ``locales`` inside an ``i18n`` package covers the package above it (``plantcraft/i18n/locales``
  covers ``plantcraft/``); any other ``locales`` covers its parent folder (``frontend/src``,
  ``ui/src``, ``src/<app package>``).
- TypeScript (``.ts``, ``.tsx``) and Python (``.py``) are read; tests, ``node_modules`` and
  builds are not.

It always fails on a broken catalog: not a flat object of non-empty strings, or a translation
whose ``{name}`` fields differ from the English. With ``--strict`` it also fails when a text is
missing from a catalog (the gate once a language is complete); without it the missing ones are
only counted. ``--missing`` lists them, ``--json`` prints the counts for scripts.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

LANGUAGES = ("pt-BR", "es")
SKIP = {"node_modules", "dist", "build", "tests", "__pycache__", ".venv", "vendor", "e2e"}
FIELD = re.compile(r"\{(\w*)\}")
TS_CALL = re.compile(r"""(?<![\w.$])t\(\s*(?:"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)')\s*[,)]""")
PY_CALL = re.compile(
    r"""(?<![\w.])t\(\s*((?:(?:"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')\s*)+)[,)]"""
)
PY_LITERAL = re.compile(r""""(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'""")


@dataclass
class Coverage:
    catalog: Path
    used: set[str] = field(default_factory=set)
    entries: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        return sorted(self.used - self.entries.keys())

    @property
    def unused(self) -> list[str]:
        return sorted(self.entries.keys() - self.used)


def _is_test(path: Path) -> bool:
    name = path.name
    return name.startswith("test_") or ".test." in name or name.endswith("_test.py")


def _sources(root: Path):
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".py"} or _is_test(path):
            continue
        if SKIP.intersection(part for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name.endswith(".d.ts"):
            continue
        yield path


def _ts_unescape(text: str) -> str:
    try:
        return json.loads(f'"{text}"')
    except json.JSONDecodeError:
        return text


def texts_in(path: Path) -> set[str]:
    """The English texts a source file passes to ``t()`` as literals."""

    code = path.read_text(encoding="utf-8", errors="replace")
    found: set[str] = set()
    if path.suffix == ".py":
        for match in PY_CALL.finditer(code):
            try:
                found.add(
                    "".join(ast.literal_eval(part) for part in PY_LITERAL.findall(match.group(1)))
                )
            except (ValueError, SyntaxError):
                continue
    else:
        for match in TS_CALL.finditer(code):
            double, single = match.group(1), match.group(2)
            found.add(_ts_unescape(double) if double is not None else single.replace("\\'", "'"))
    return {text for text in found if text.strip()}


def covered_folder(locales: Path) -> Path:
    parent = locales.parent
    return parent.parent if parent.name == "i18n" else parent


def catalog_folders(roots: list[Path]) -> list[Path]:
    folders: set[Path] = set()
    for root in roots:
        for locales in root.rglob("locales"):
            if locales.is_dir() and not SKIP.intersection(locales.relative_to(root).parts):
                folders.add(locales.resolve())
    return sorted(folders)


def check(locales: Path, language: str) -> Coverage:
    coverage = Coverage(catalog=locales / f"{language}.json")
    covered = covered_folder(locales)
    for path in _sources(covered):
        coverage.used |= texts_in(path)
    if not coverage.catalog.is_file():
        return coverage
    try:
        data = json.loads(coverage.catalog.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        coverage.problems.append(f"not JSON: {error}")
        return coverage
    if not isinstance(data, dict):
        coverage.problems.append("not a flat object of English text to translation")
        return coverage
    for english, translated in data.items():
        if not isinstance(translated, str) or not translated.strip():
            coverage.problems.append(f"empty translation: {english!r}")
        elif sorted(FIELD.findall(english)) != sorted(FIELD.findall(translated)):
            coverage.problems.append(f"fields differ: {english!r} -> {translated!r}")
    coverage.entries = {key: value for key, value in data.items() if isinstance(value, str)}
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m plantcraft_sdk.i18n_check", description=__doc__.split("\n")[0]
    )
    parser.add_argument("folders", nargs="*", default=["."], type=Path)
    parser.add_argument("--language", action="append", choices=LANGUAGES)
    parser.add_argument(
        "--strict", action="store_true", help="fail when a text is missing from a catalog"
    )
    parser.add_argument("--missing", action="store_true", help="list the missing texts")
    parser.add_argument("--json", action="store_true", help="print the counts as JSON")
    args = parser.parse_args(argv)
    languages = args.language or list(LANGUAGES)
    here = Path.cwd().resolve()
    failed = False
    report = []
    for locales in catalog_folders([folder.resolve() for folder in args.folders]):
        for language in languages:
            coverage = check(locales, language)
            name = (
                str(coverage.catalog.relative_to(here))
                if coverage.catalog.is_relative_to(here)
                else str(coverage.catalog)
            )
            used = len(coverage.used)
            done = used - len(coverage.missing)
            report.append(
                {
                    "catalog": name,
                    "used": used,
                    "translated": done,
                    "missing": len(coverage.missing),
                    "unused": len(coverage.unused),
                    "problems": coverage.problems,
                }
            )
            if not args.json:
                share = f"{100 * done / used:.0f}%" if used else "-"
                print(
                    f"{name}: {done}/{used} translated ({share}), {len(coverage.missing)} missing, {len(coverage.unused)} unused"
                )
                for problem in coverage.problems:
                    print(f"  problem: {problem}")
                if args.missing:
                    for text in coverage.missing:
                        print(f"  missing: {text}")
            if coverage.problems or (args.strict and coverage.missing):
                failed = True
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
