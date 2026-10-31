"""The suite's visual rules that a few lines of reading can hold (docs/ui-guidelines.md).

Navigation happens only through the side menu and the tabs: an Overview has no
buttons at its top, and no button at the top of a page goes to a page the menu already lists.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _menu(path: Path) -> set[str]:
    """The destinations of an app's ``NAV`` list (``pages.ts(x)``)."""

    text = path.read_text(encoding="utf-8")
    start = text.index("export const NAV")
    return set(re.findall(r'to: "([^"]+)"', text[start : text.index("\n];", start)]))


def _braced(text: str, start: int) -> str:
    """The JSX expression that opens with the ``{`` at ``start``, up to its closing brace."""

    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def _top_buttons(text: str) -> list[str]:
    """What a page draws at the right of its title: ``actions={…}`` and ``heading-actions`` rows."""

    found = [_braced(text, match.end() - 1) for match in re.finditer(r"\bactions=\{", text)]
    for match in re.finditer(r'className="heading-actions[^"]*">', text):
        found.append(text[match.end() : text.find("</div>", match.end())])
    return found


def _goes_to(fragment: str, menu: set[str]) -> set[str]:
    targets = set(re.findall(r'(?:to|href)=\{?"([^"?#]+)"', fragment))
    targets |= set(re.findall(r'navigate\("([^"?#]+)"\)', fragment))
    return targets & menu


def _apps() -> list[tuple[str, Path]]:
    found = []
    for pages in sorted(ROOT.glob("apps/*/frontend/src/pages.ts*")):
        found.append((pages.parents[2].name, pages))
    assert found
    return found


def test_no_overview_has_buttons_at_its_top():
    for app, _pages in _apps():
        overview = ROOT / "apps" / app / "frontend/src/OverviewPage.tsx"
        if not overview.exists():
            continue
        assert not re.search(r"\bactions=", overview.read_text(encoding="utf-8")), (
            f"{overview}: an Overview has no buttons at its top (docs/ui-guidelines.md)"
        )
    home = (ROOT / "frontend/src/PlatformHome.tsx").read_text(encoding="utf-8")
    overview = home[home.index("export function PlatformHome") :]
    overview = overview[: overview.index("\n}\n")]
    assert "heading-actions" not in overview, "PlantCraft's Overview has no buttons at its top"


def test_no_top_button_repeats_the_menu():
    problems = []
    for app, pages in _apps():
        menu = _menu(pages)
        for path in sorted((ROOT / "apps" / app / "frontend/src").rglob("*.tsx")):
            for fragment in _top_buttons(path.read_text(encoding="utf-8")):
                for target in _goes_to(fragment, menu):
                    problems.append(f"{path.relative_to(ROOT)}: a top button goes to {target}")
    assert not problems, "\n".join(problems)


def _sources() -> list[Path]:
    found = list((ROOT / "frontend" / "src").rglob("*.tsx"))
    found += list(ROOT.glob("apps/*/frontend/src/**/*.tsx"))
    return sorted(path for path in found if ".test." not in path.name)


def test_asking_before_an_action_is_the_suites_dialog():
    """Rule 9: ``confirmAction`` from ``@plantcraft/ui``, never the browser's ``window.confirm``."""

    offenders = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in _sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "window.confirm(" in line
    ]
    assert not offenders, "window.confirm in place of confirmAction: " + ", ".join(offenders)


def _styles(*roots: str) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        found += [
            path
            for path in ROOT.glob(f"{root}/**/*")
            if path.suffix in {".css", ".ts", ".tsx"} and "node_modules" not in path.parts
        ]
    return sorted(found)


def test_every_colour_and_size_token_a_screen_uses_exists():
    """A ``var(--pc-…)`` names a token of ``@plantcraft/ui`` (or one the page sets itself).

    A misspelt or retired token draws its fallback, a fixed colour that ignores the dark theme,
    or nothing at all (a shadow, a text colour).
    """

    every = _styles("ui/src", "frontend/src", "apps/*/frontend/src")
    defined: set[str] = set()
    for path in every:
        text = path.read_text(encoding="utf-8")
        defined |= set(re.findall(r"(--pc-[a-z0-9-]+)\s*:", text))
        defined |= set(re.findall(r"[\"'](--pc-[a-z0-9-]+)[\"']", text))
    missing = [
        f"{path.relative_to(ROOT)}:{number} {name}"
        for path in _styles("frontend/src", "apps/*/frontend/src")
        if ".test." not in path.name
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for name in re.findall(r"var\((--pc-[a-z0-9-]+[a-z0-9])", line)
        if name not in defined
    ]
    assert not missing, "tokens that do not exist: " + ", ".join(missing)
