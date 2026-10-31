"""Every app's menu ends with its settings: Setup in PlantCraft, Settings in
an app, always the last entry, so a person finds them in the same place everywhere."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = {"Setup", "Settings"}


def _menu(text: str) -> list[str]:
    """The labels of the ``NAV`` list, in order."""

    start = text.index("export const NAV")
    body = text[start : text.index("\n];", start)]
    return re.findall(r'label: "([^"]+)"', body)


def test_each_app_menu_ends_with_its_settings():
    pages = sorted(ROOT.glob("apps/*/frontend/src/pages.ts*")) + sorted(
        ROOT.glob("templates/app/frontend/src/pages.ts*")
    )
    assert pages
    for path in pages:
        labels = _menu(path.read_text(encoding="utf-8"))
        assert labels, path
        found = [label for label in labels if label in SETTINGS]
        assert not found or labels[-1] in SETTINGS, f"{path}: {labels}"


def test_plantcraft_menu_ends_with_setup():
    text = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    start = text.index("const nav: ShellNavItem[] = desk ? deskNav : operating ? opsNav : [")
    body = text[start : text.index("\n  ];", start)]
    labels = re.findall(r'label: t\("([^"]+)"\)', body)
    assert labels[:4] == ["Overview", "Assets", "System health", "Preferences"], labels
    assert labels[-1] == "Settings", labels
