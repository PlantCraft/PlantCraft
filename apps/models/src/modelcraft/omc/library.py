"""The libraries' class index (the runner's ``library_index`` job), for the library browser.

One line per class: ``name<TAB>restriction<TAB>partial<TAB>comment``; a comment with line breaks
continues on the next lines. The index is built once per runner version and kept in the data
folder, so the browser answers from memory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plantcraft_sdk.files import write_json

# What the browser hides unless asked: documentation, internal packages, and Utilities (files,
# system calls: the policy refuses them, so offering them would only lead to a refusal).
HIDDEN_PARTS = {"UsersGuide", "Internal", "Obsolete", "ModelicaReference", "Utilities"}
RESTRICTIONS = {
    "package",
    "model",
    "block",
    "connector",
    "expandable connector",
    "record",
    "operator record",
    "type",
    "function",
    "pure function",
    "impure function",
    "class",
    "operator",
    "operator function",
}


def parse_index(text: str) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4 and parts[1] in RESTRICTIONS and parts[0] and " " not in parts[0]:
            classes.append(
                {
                    "name": parts[0],
                    "restriction": parts[1],
                    "partial": parts[2] == "true",
                    "comment": parts[3].strip(),
                }
            )
        elif classes and line.strip():
            classes[-1]["comment"] = f"{classes[-1]['comment']} {line.strip()}".strip()
    return classes


class LibraryIndex:
    def __init__(self, classes: list[dict[str, Any]], version: str = ""):
        self.version = version
        self.classes = {item["name"]: item for item in classes}
        self.children: dict[str, list[str]] = {}
        for name in self.classes:
            parent = name.rpartition(".")[0]
            self.children.setdefault(parent, []).append(name)

    @classmethod
    def load(cls, path: Path) -> LibraryIndex | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data["classes"], data.get("version", ""))
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def save(self, path: Path) -> None:
        write_json(path, {"version": self.version, "classes": list(self.classes.values())})

    def __len__(self) -> int:
        return len(self.classes)

    def __contains__(self, name: str) -> bool:
        return name in self.classes

    def get(self, name: str) -> dict[str, Any] | None:
        return self.classes.get(name)

    @staticmethod
    def hidden(name: str) -> bool:
        return any(part in HIDDEN_PARTS for part in name.split("."))

    def _entry(self, name: str) -> dict[str, Any]:
        item = self.classes[name]
        return {
            **item,
            "short": name.rpartition(".")[2],
            "has_children": bool(self.children.get(name)),
        }

    def list(self, parent: str = "", *, all_parts: bool = False) -> list[dict[str, Any]]:
        names = self.children.get(parent, [])
        return [self._entry(n) for n in names if all_parts or not self.hidden(n)]

    def search(self, query: str, *, limit: int = 100) -> list[dict[str, Any]]:
        words = [word for word in query.lower().split() if word]
        if not words:
            return []
        scored = []
        for name, item in self.classes.items():
            if self.hidden(name) or item["restriction"] == "package":
                continue
            haystack = f"{name} {item['comment']}".lower()
            if all(word in haystack for word in words):
                short = name.rpartition(".")[2].lower()
                score = (
                    0 if short == words[0] else 1 if short.startswith(words[0]) else 2,
                    len(name),
                )
                scored.append((score, name))
        return [self._entry(name) for _, name in sorted(scored)[:limit]]

    def names(self, prefix: str = "", *, limit: int = 5000) -> list[str]:
        """Class names for the editor's completion (packages, models, blocks, connectors...)."""

        found = [n for n in self.classes if n.startswith(prefix) and not self.hidden(n)]
        return sorted(found)[:limit]
