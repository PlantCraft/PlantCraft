"""A class's own elements, read from its text: declarations, connections and equations.

Enough of Modelica's component clause (``[prefixes] Type name[dims](modifiers) = value
"comment" annotation(...);``) to read a block's interface (its inputs, outputs and parameters)
and a diagram model (its blocks and their connections) without omc. omc stays the judge of
what is valid Modelica: what this reader cannot place is reported, never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from modelcraft.modelica.edit import _connect, _own, _section_of, _statements
from modelcraft.modelica.source import ClassDef, Token, find, tokens

TYPE_PREFIXES = {
    "parameter",
    "constant",
    "discrete",
    "input",
    "output",
    "flow",
    "stream",
    "final",
    "inner",
    "outer",
    "replaceable",
    "redeclare",
    "each",
}


@dataclass
class Declaration:
    prefixes: list[str]
    type: str
    name: str
    dims: str = ""
    modifiers: dict[str, str] = field(default_factory=dict)
    binding: str | None = None
    comment: str = ""
    annotation: str = ""
    section: str = "public"
    start: int = 0
    end: int = 0


@dataclass
class ClassElements:
    declarations: list[Declaration]
    connections: list[tuple[str, str]]
    # Equations and algorithms other than connect(), and extends clauses (base class names).
    equations: int = 0
    extends: list[str] = field(default_factory=list)
    # Statements this reader cannot place (several names in one declaration...).
    unread: int = 0
    annotation: str = ""


def _matching(items: list[Token], index: int) -> int:
    depth = 0
    for position in range(index, len(items)):
        if items[position].text in ("(", "{", "["):
            depth += 1
        elif items[position].text in (")", "}", "]"):
            depth -= 1
            if depth == 0:
                return position
    return len(items) - 1


def split_arguments(inner: str) -> list[str]:
    """``a = 1, b(c = 2) = {1, 2}`` split at its top-level commas."""

    parts, depth, current, quoted = [], 0, "", False
    for char in inner:
        if char == '"':
            quoted = not quoted
        elif not quoted and char in "({[":
            depth += 1
        elif not quoted and char in ")}]":
            depth -= 1
        if char == "," and depth == 0 and not quoted:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def modifier_map(inner: str) -> dict[str, str]:
    """``k = 2, each start = 0`` as ``{"k": "2", "start": "0"}`` (nested modifiers kept as text)."""

    found: dict[str, str] = {}
    for part in split_arguments(inner):
        key, sep, value = part.partition("=")
        words = key.split()
        if not words:
            continue
        name = words[-1]
        if sep and re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", name):
            found[name] = value.strip()
    return found


def _declaration(text: str, items: list[Token], statement: list[int]) -> Declaration | None:
    words = [items[i] for i in statement]
    position = 0
    prefixes = []
    while position < len(words) and words[position].text in TYPE_PREFIXES:
        prefixes.append(words[position].text)
        position += 1
    if position >= len(words) or words[position].kind != "ident":
        return None
    type_parts = [words[position].text]
    position += 1
    while (
        position + 1 < len(words)
        and words[position].text == "."
        and words[position + 1].kind == "ident"
    ):
        type_parts.append(words[position + 1].text)
        position += 2
    dims = ""
    if position < len(words) and words[position].text == "[":  # Real[3] x
        close = _matching(words, position)
        dims = text[words[position].start : words[close].end]
        position = close + 1
    if position >= len(words) or words[position].kind != "ident":
        return None
    name = words[position].text
    position += 1
    if position < len(words) and words[position].text == "[":
        close = _matching(words, position)
        dims = text[words[position].start : words[close].end]
        position = close + 1
    modifiers: dict[str, str] = {}
    if position < len(words) and words[position].text == "(":
        close = _matching(words, position)
        modifiers = modifier_map(text[words[position].end : words[close].start])
        position = close + 1
    binding = None
    if position < len(words) and words[position].text in ("=", ":="):
        start = position + 1
        depth = 0
        while position + 1 < len(words):
            token = words[position + 1]
            if token.text in ("(", "{", "["):
                depth += 1
            elif token.text in (")", "}", "]"):
                depth -= 1
            if depth == 0 and (
                token.kind == "string" or token.text in ("annotation", ";", ",", "if")
            ):
                break
            position += 1
        binding = (
            text[words[start].start : words[position].end].strip() if position >= start else ""
        )
        position += 1
    if position < len(words) and words[position].text in (",", "if"):
        return None  # several names in one declaration, or a conditional component
    comment = ""
    while position < len(words) and words[position].kind == "string":
        comment += words[position].text[1:-1]
        position += 1
        if position < len(words) and words[position].text == "+":
            position += 1
    annotation = ""
    if position < len(words) and words[position].text == "annotation":
        close = _matching(words, position + 1)
        annotation = text[words[position + 1].end : words[close].start]
    return Declaration(
        prefixes=prefixes,
        type=".".join(type_parts),
        name=name,
        dims=dims,
        modifiers=modifiers,
        binding=binding,
        comment=comment,
        annotation=annotation,
        start=words[0].start,
        end=words[-1].end,
    )


def elements(text: str, cls: ClassDef) -> ClassElements:
    """What the class declares and connects, in its own body (nested classes left out)."""

    items = tokens(text)
    statements = _statements(items, _own(items, cls))
    sections = _section_of(items, statements)
    found = ClassElements(declarations=[], connections=[])
    for statement, section in zip(statements, sections, strict=True):
        first = items[statement[0]].text
        if len(statement) == 1 and first in (
            "equation",
            "algorithm",
            "public",
            "protected",
            "initial",
        ):
            continue
        if first == "annotation":
            close = _matching(items, statement[0] + 1)
            found.annotation = text[items[statement[0] + 1].end : items[close].start]
            continue
        if section in ("public", "protected"):
            if first == "extends":
                parts = []
                position = statement[0] + 1
                while position < statement[-1] and (
                    items[position].kind == "ident" or items[position].text == "."
                ):
                    parts.append(items[position].text)
                    position += 1
                found.extends.append("".join(parts))
                continue
            if first == "import":
                continue
            if items[statement[0]].kind == "keyword" and first not in TYPE_PREFIXES:
                continue  # a nested class definition
            declaration = _declaration(text, items, statement)
            if declaration is None:
                found.unread += 1
                continue
            declaration.section = section
            found.declarations.append(declaration)
            continue
        pair = _connect(items, statement)
        if pair and section == "equation":
            found.connections.append(pair)
        else:
            found.equations += 1
    return found


def class_elements(text: str, name: str) -> ClassElements | None:
    cls = find(text, name)
    if cls is None or cls.short_class:
        return None
    return elements(text, cls)


# Literal values ---------------------------------------------------------------------------

NUMBER = re.compile(r"^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")


def literal(text: str | None) -> tuple[bool, object]:
    """A Modelica literal as JSON: numbers, true/false, ``{...}`` arrays of them. ``(False,
    None)`` for anything else (an expression, a string, an enumeration)."""

    if text is None:
        return False, None
    value = text.strip()
    if NUMBER.match(value):
        number = float(value)
        return True, int(
            number
        ) if number.is_integer() and "." not in value and "e" not in value.lower() else number
    if value in ("true", "false"):
        return True, value == "true"
    if value.startswith("{") and value.endswith("}"):
        parts = split_arguments(value[1:-1])
        found = []
        for part in parts:
            ok, item = literal(part)
            if not ok:
                return False, None
            found.append(item)
        return True, found
    return False, None


def modelica_value(value: object) -> str:
    """JSON (a number, a boolean, nested lists of them, or an expression's text) as Modelica."""

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("Not a finite number.")
        text = repr(value)
        return text[:-2] if text.endswith(".0") else text
    if isinstance(value, list):
        return "{" + ", ".join(modelica_value(item) for item in value) + "}"
    if isinstance(value, str):
        return value.strip()
    raise ValueError("Not a value Models can write.")
