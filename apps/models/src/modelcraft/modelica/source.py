"""Reading Modelica source without omc: tokens, the classes a file defines, and the policy.

This is a light reader of the Modelica 3.6 lexical rules (comments, strings, quoted
identifiers, numbers, operators) and of class definitions (``[prefixes] model Name ... end
Name;``, short classes ``type T = Real;``), enough for the project tree, for finding where a
class lives and for the diagram's text edits. omc stays the judge of what is valid Modelica.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from modelcraft.i18n import t

CLASS_WORDS = {
    "class",
    "model",
    "block",
    "connector",
    "record",
    "type",
    "package",
    "function",
    "operator",
}
PREFIX_WORDS = {
    "encapsulated",
    "partial",
    "final",
    "replaceable",
    "redeclare",
    "inner",
    "outer",
    "expandable",
    "pure",
    "impure",
    "operator",
}
SECTION_WORDS = {"equation", "algorithm", "public", "protected", "initial", "external"}
KEYWORDS = (
    CLASS_WORDS
    | PREFIX_WORDS
    | SECTION_WORDS
    | {
        "within",
        "end",
        "extends",
        "import",
        "annotation",
        "connect",
        "if",
        "then",
        "else",
        "elseif",
        "for",
        "loop",
        "while",
        "when",
        "elsewhen",
        "in",
        "and",
        "or",
        "not",
        "true",
        "false",
        "parameter",
        "constant",
        "discrete",
        "input",
        "output",
        "flow",
        "stream",
        "der",
        "each",
        "constrainedby",
        "break",
        "return",
    }
)

TOKEN = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<line_comment>//[^\n]*)
  | (?P<block_comment>/\*.*?(?:\*/|\Z))
  | (?P<string>"(?:\\.|[^"\\])*(?:"|\Z))
  | (?P<qident>'(?:\\.|[^'\\])*(?:'|\Z))
  | (?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\.\^|\.\*|\./|\.\+|\.-|<=|>=|==|<>|:=|[-+*/^=<>(){}\[\];:,.])
  | (?P<other>.)
    """,
    re.S | re.X,
)


@dataclass
class Token:
    kind: str  # ident | keyword | number | string | op | other
    text: str
    start: int
    end: int


def tokens(text: str) -> list[Token]:
    found = []
    for match in TOKEN.finditer(text):
        kind = match.lastgroup or "other"
        if kind in ("space", "line_comment", "block_comment"):
            continue
        value = match.group()
        if kind == "qident":
            kind = "ident"
        elif kind == "ident" and value in KEYWORDS:
            kind = "keyword"
        found.append(Token(kind, value, match.start(), match.end()))
    return found


@dataclass
class ClassDef:
    name: str  # qualified within the file (and its within clause)
    short: str
    restriction: str
    start: int  # offset of the first prefix or class word
    end: int  # offset just past "end Name;" (or the short class's ";")
    body_start: int  # first token index inside the class
    body_end: int  # index of the "end" token (or the ";" of a short class)
    line: int
    comment: str = ""
    partial: bool = False
    short_class: bool = False
    children: list[ClassDef] = field(default_factory=list)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _restriction(items: list[Token], index: int) -> tuple[str, int] | None:
    """The restriction starting at ``items[index]`` (``expandable connector``, ``operator
    record``, ``pure function``...) and the index of the class name after it."""

    words = []
    i = index
    while (
        i < len(items)
        and items[i].kind == "keyword"
        and items[i].text in PREFIX_WORDS | CLASS_WORDS
    ):
        words.append(items[i].text)
        i += 1
    if not words or i >= len(items) or items[i].kind != "ident":
        return None
    classes = [w for w in words if w in CLASS_WORDS]
    if not classes:
        return None
    restriction = classes[-1]
    if "expandable" in words and restriction == "connector":
        restriction = "expandable connector"
    elif (
        words.count("operator")
        and restriction in ("record", "function")
        and "operator" in words[:-1]
    ):
        restriction = f"operator {restriction}"
    elif restriction == "function" and ("pure" in words or "impure" in words):
        restriction = ("impure " if "impure" in words else "pure ") + "function"
    return restriction, i


def _within(items: list[Token]) -> tuple[str, int]:
    if items and items[0].text == "within":
        parts = []
        i = 1
        while i < len(items) and items[i].text != ";":
            parts.append(items[i].text)
            i += 1
        return "".join(parts), i + 1
    return "", 0


STATEMENT_ENDS = frozenset({"if", "when", "for", "while"})


def outline(text: str) -> list[ClassDef]:
    """The classes the file defines, nested, with their spans."""

    items = tokens(text)
    within, index = _within(items)

    def parse(index: int, prefix: str, stop_name: str | None) -> tuple[list[ClassDef], int]:
        found: list[ClassDef] = []
        depth = 0  # parentheses: modifiers and annotations may hold class-like words
        while index < len(items):
            token = items[index]
            if token.text in ("(", "{", "["):
                depth += 1
            elif token.text in (")", "}", "]"):
                depth = max(0, depth - 1)
            elif (
                depth == 0
                and token.text == "end"
                and stop_name is not None
                # "end if", "end when", "end for", "end while" close a statement, not the class.
                and (index + 1 >= len(items) or items[index + 1].text not in STATEMENT_ENDS)
            ):
                return found, index
            elif (
                depth == 0 and token.kind == "keyword" and token.text in PREFIX_WORDS | CLASS_WORDS
            ):
                previous = items[index - 1].text if index else ";"
                at_element = (
                    index == 0
                    or previous in {";", "public", "protected", "within"} | PREFIX_WORDS
                    or items[index - 1].kind == "string"
                )
                head = _restriction(items, index)
                if head and at_element:
                    restriction, name_index = head
                    name = items[name_index].text
                    qualified = f"{prefix}.{name}" if prefix else name
                    words = [t.text for t in items[index:name_index]]
                    after = name_index + 1
                    if after < len(items) and items[after].text == "=":
                        # A short class definition: up to its semicolon.
                        semicolon = after
                        paren = 0
                        while semicolon < len(items):
                            if items[semicolon].text in ("(", "{", "["):
                                paren += 1
                            elif items[semicolon].text in (")", "}", "]"):
                                paren -= 1
                            elif items[semicolon].text == ";" and paren <= 0:
                                break
                            semicolon += 1
                        end = items[min(semicolon, len(items) - 1)].end
                        found.append(
                            ClassDef(
                                qualified,
                                name,
                                restriction,
                                token.start,
                                end,
                                after,
                                semicolon,
                                line_of(text, token.start),
                                partial="partial" in words,
                                short_class=True,
                            )
                        )
                        index = semicolon + 1
                        continue
                    if after < len(items) and items[after].text == "extends" and restriction:
                        after += 1  # "model extends Base" (a class extension)
                    comment = ""
                    if after < len(items) and items[after].kind == "string":
                        comment = items[after].text[1:-1]
                    children, end_index = parse(after, qualified, name)
                    end_offset = items[end_index].end if end_index < len(items) else len(text)
                    close = end_index
                    while close < len(items) and items[close].text != ";":
                        close += 1
                    if close < len(items):
                        end_offset = items[close].end
                    found.append(
                        ClassDef(
                            qualified,
                            name,
                            restriction,
                            token.start,
                            end_offset,
                            after,
                            end_index,
                            line_of(text, token.start),
                            comment,
                            "partial" in words,
                            False,
                            children,
                        )
                    )
                    index = close + 1
                    continue
            index += 1
        return found, index

    classes, _ = parse(index, within, None)
    return classes


def flatten(classes: list[ClassDef]) -> list[ClassDef]:
    found = []
    for item in classes:
        found.append(item)
        found.extend(flatten(item.children))
    return found


def find(text: str, name: str) -> ClassDef | None:
    return next((item for item in flatten(outline(text)) if item.name == name), None)


# The policy --------------------------------------------------------------------------------

# Defense in depth: the runner container is the boundary (no network, no secret, limits).
# Shell commands, file access and C code are what no process model needs: every path through
# ``Utilities.System``, ``Utilities.Files`` or ``Utilities.Internal`` (however imported or
# renamed), any import of ``Utilities`` itself, and external functions are refused; an
# administrator may allow external functions (MODELCRAFT_ALLOW_EXTERNAL).
FORBIDDEN_AFTER_UTILITIES = {"System", "Files", "Internal"}


def _dotted(items: list[Token], index: int) -> list[str]:
    parts = [items[index].text.strip("'")]
    i = index + 1
    while i + 1 < len(items) and items[i].text == "." and items[i + 1].kind in ("ident", "keyword"):
        parts.append(items[i + 1].text.strip("'"))
        i += 2
    return parts


def policy(text: str, *, allow_external: bool = False) -> list[dict]:
    """What the policy refuses in one file: ``[{"line", "column", "text"}]``."""

    items = tokens(text)
    problems = []

    def refuse(token: Token, message: str) -> None:
        line = line_of(text, token.start)
        column = token.start - (text.rfind("\n", 0, token.start) + 1) + 1
        problems.append({"line": line, "column": column, "text": message})

    for index, token in enumerate(items):
        if token.kind == "keyword" and token.text == "external" and not allow_external:
            refuse(token, t("External functions (C code) are turned off on this server."))
            continue
        if token.kind != "ident" or (index and items[index - 1].text == "."):
            continue
        parts = _dotted(items, index)
        pairs = list(zip(parts, parts[1:]))
        if any(a == "Utilities" and b in FORBIDDEN_AFTER_UTILITIES for a, b in pairs):
            refuse(
                token,
                t(
                    "Files and system commands (Modelica.Utilities.System, Files) are not available here."
                ),
            )
        elif parts[-1] == "Utilities" and len(parts) > 1:
            refuse(token, t("Use the packages of Modelica.Utilities by name (Strings, Streams)."))
    return problems
