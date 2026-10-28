"""The diagram's edits, made on the Modelica text (the text stays the model's only source).

Each edit takes a file's text and the class it changes, and answers the new text; anything it
cannot do safely is an ``EditError`` with words a person can act on, and the text is left as
it was. Placements and lines are written as the Modelica specification's annotations::

    Modelica.Blocks.Continuous.PID PID(k=2) annotation(Placement(transformation(extent={{-10,-10},{10,10}})));
    connect(a.y, b.u) annotation(Line(points={{-20,0},{20,0}}, color={0,0,127}));
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from modelcraft.modelica.source import ClassDef, Token, find, flatten, outline, tokens

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TYPE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
# A Bitmap graphic that carries its picture (``set_image``): no parentheses inside its arguments.
BITMAP_CALL = re.compile(r'Bitmap\s*\([^()]*?imageSource\s*=\s*"[^"]*"[^()]*\)', re.S)
CONNECTOR_REF = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\[[0-9]{1,5}\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[[0-9]{1,5}\])?)*$"
)
# A modifier's value: a number, a boolean, a string, an enumeration or a short expression.
VALUE = re.compile(r"""^[A-Za-z0-9_.+\-*/^(){}\[\], "'<>=:]{1,400}$""")


class EditError(ValueError):
    pass


def _number(value: float) -> str:
    rounded = round(float(value), 3)
    return str(int(rounded)) if rounded == int(rounded) else repr(rounded)


def _extent(extent) -> str:
    try:
        (x1, y1), (x2, y2) = extent
    except (TypeError, ValueError) as exc:
        raise EditError("An extent is two points.") from exc
    for value in (x1, y1, x2, y2):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or abs(value) > 1e6:
            raise EditError("An extent is made of numbers.")
    return "{{%s,%s},{%s,%s}}" % tuple(_number(v) for v in (x1, y1, x2, y2))


def _points(points) -> str:
    if not isinstance(points, list) or len(points) > 200:
        raise EditError("A line is a list of up to 200 points.")
    out = []
    for point in points:
        if not (isinstance(point, list) and len(point) == 2) or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e6 for v in point
        ):
            raise EditError("A point is two numbers.")
        out.append("{%s,%s}" % (_number(point[0]), _number(point[1])))
    return "{" + ",".join(out) + "}"


def placement(extent, rotation: float = 0.0, origin=None) -> str:
    parts = [f"extent={_extent(extent)}"]
    if origin and any(origin):
        parts.append("origin={%s,%s}" % (_number(origin[0]), _number(origin[1])))
    if rotation:
        parts.append(f"rotation={_number(rotation)}")
    return f"Placement(transformation({', '.join(parts)}))"


# Finding things in a class -----------------------------------------------------------------


def _class(text: str, name: str) -> tuple[ClassDef, list[Token]]:
    found = find(text, name)
    if found is None:
        raise EditError(f"Class {name} is not in this file.")
    if found.short_class:
        raise EditError(f"{name} is a short class definition: it has no diagram to edit.")
    return found, tokens(text)


def _own(items: list[Token], cls: ClassDef) -> list[int]:
    """Token indexes of the class's own body (nested classes skipped)."""

    nested = [(c.start, c.end) for c in flatten(cls.children)]
    return [
        i
        for i in range(cls.body_start, cls.body_end)
        if not any(start <= items[i].start < end for start, end in nested)
    ]


def _statements(items: list[Token], indexes: list[int]) -> list[list[int]]:
    """The class body split into statements (each up to its ``;`` outside brackets), section
    keywords as their own one-token statements."""

    statements: list[list[int]] = []
    current: list[int] = []
    depth = 0
    for i in indexes:
        token = items[i]
        if (
            depth == 0
            and not current
            and token.kind == "keyword"
            and token.text
            in (
                "equation",
                "algorithm",
                "public",
                "protected",
            )
        ):
            statements.append([i])
            continue
        if (
            depth == 0
            and not current
            and token.text == "initial"
            and i + 1 < len(items)
            and items[i + 1].text in ("equation", "algorithm")
        ):
            statements.append([i])
            continue
        if not current and token.kind == "string" and not statements:
            continue  # the class comment
        current.append(i)
        if token.text in ("(", "{", "["):
            depth += 1
        elif token.text in (")", "}", "]"):
            depth = max(0, depth - 1)
        elif token.text == ";" and depth == 0:
            statements.append(current)
            current = []
    if current:
        statements.append(current)
    return statements


def _section_of(items: list[Token], statements: list[list[int]]) -> list[str]:
    section = "public"
    found = []
    for statement in statements:
        first = items[statement[0]].text
        if len(statement) == 1 and first in ("equation", "algorithm", "public", "protected"):
            previous = found and items[statements[len(found) - 1][0]].text == "initial"
            section = ("initial " if previous else "") + first
        found.append(section)
    return found


def _declares(items: list[Token], statement: list[int], name: str) -> bool:
    """Whether the statement is a component declaration whose (first) name is ``name``."""

    words = [items[i] for i in statement]
    if not words or words[0].text in (
        "extends",
        "import",
        "connect",
        "annotation",
        "equation",
        "algorithm",
    ):
        return False
    depth = 0
    for position, token in enumerate(words):
        if token.text in ("(", "{", "["):
            depth += 1
        elif token.text in (")", "}", "]"):
            depth -= 1
        elif depth == 0 and token.kind == "ident" and token.text == name and position > 0:
            before = words[position - 1]
            after = words[position + 1].text if position + 1 < len(words) else ";"
            if before.kind in ("ident", "keyword") or before.text in ("]", ","):
                if (
                    after in ("(", "[", "=", ";", "annotation", ",", "if")
                    or words[position + 1].kind == "string"
                ):
                    return True
    return False


def _connect(items: list[Token], statement: list[int]) -> tuple[str, str] | None:
    words = [items[i].text for i in statement]
    if len(words) < 6 or words[0] != "connect" or words[1] != "(":
        return None
    depth = 0
    for position in range(1, len(words)):
        if words[position] in ("(", "["):
            depth += 1
        elif words[position] in (")", "]"):
            depth -= 1
            if depth == 0:
                inside = "".join(words[2:position])
                left, _, right = inside.partition(",")
                return left, right
    return None


def _insert_points(text: str, items: list[Token], cls: ClassDef) -> tuple[int, int]:
    """(where a declaration goes, where an equation goes) in the class."""

    indexes = _own(items, cls)
    statements = _statements(items, indexes)
    sections = _section_of(items, statements)
    end_offset = items[cls.body_end].start
    annotation_at = None
    if statements:
        last = statements[-1]
        if items[last[0]].text == "annotation":
            annotation_at = items[last[0]].start
    tail = annotation_at if annotation_at is not None else end_offset
    declaration = None
    for statement, section in zip(statements, sections, strict=True):
        if section != "public":
            break
        if items[statement[0]].text in ("public",) or items[statement[0]].text == "annotation":
            continue
        declaration = items[statement[-1]].end
    if declaration is None:
        first_section = next(
            (
                items[s[0]].start
                for s, sec in zip(statements, sections, strict=True)
                if sec != "public"
            ),
            tail,
        )
        # Right after the class header (name and comment) when the class has no element yet.
        declaration = first_section if any(sec != "public" for sec in sections) else tail
        if declaration == tail and cls.body_start < len(items):
            header = items[cls.body_start]
            declaration = (
                header.end
                if header.kind == "string"
                else _line_end(text, items[cls.body_start - 1].end)
            )
    equation = tail
    return declaration, equation


def _line_end(text: str, offset: int) -> int:
    newline = text.find("\n", offset)
    return len(text) if newline < 0 else newline


def _has_equation_section(items: list[Token], cls: ClassDef) -> bool:
    statements = _statements(items, _own(items, cls))
    sections = _section_of(items, statements)
    return (
        bool(sections)
        and sections[-1] == "equation"
        or (
            bool(statements)
            and items[statements[-1][0]].text == "annotation"
            and len(sections) > 1
            and sections[-2] == "equation"
        )
    )


def _indent(text: str, cls: ClassDef) -> str:
    line_start = text.rfind("\n", 0, cls.start) + 1
    base = text[line_start : cls.start]
    return (base if base.strip() == "" else "") + "  "


# The edits ---------------------------------------------------------------------------------


def add_component(
    text: str, cls_name: str, type_name: str, name: str, extent, rotation: float = 0.0
) -> str:
    if not TYPE_NAME.match(type_name or ""):
        raise EditError("Not a class name.")
    if not IDENT.match(name or ""):
        raise EditError("A component name is letters, digits and _, starting with a letter.")
    cls, items = _class(text, cls_name)
    if any(_declares(items, s, name) for s in _statements(items, _own(items, cls))):
        raise EditError(f"{name} already exists in {cls_name}.")
    declaration, _ = _insert_points(text, items, cls)
    indent = _indent(text, cls)
    declared = f"{indent}{type_name} {name} annotation({placement(extent, rotation)});"
    line_start = text.rfind("\n", 0, declaration) + 1
    if declaration > 0 and not text[line_start:declaration].strip():
        # Before a section keyword (``equation``) that starts its line: a line of its own.
        return text[:line_start] + declared + "\n" + text[line_start:]
    return text[:declaration] + "\n" + declared + text[declaration:]


def unique_name(text: str, cls_name: str, base: str) -> str:
    """``base`` (or ``base1``, ``base2``...) not yet declared in the class."""

    stem = re.sub(r"[^A-Za-z0-9_]", "", base) or "component"
    if not stem[0].isalpha():
        stem = "c" + stem
    stem = stem[0].lower() + stem[1:]
    cls, items = _class(text, cls_name)
    statements = _statements(items, _own(items, cls))
    for number in range(0, 1000):
        candidate = stem if number == 0 else f"{stem}{number}"
        if not any(_declares(items, s, candidate) for s in statements):
            return candidate
    raise EditError("No free name.")


def connect(text: str, cls_name: str, left: str, right: str, points, color=(0, 0, 127)) -> str:
    for ref in (left, right):
        if not CONNECTOR_REF.match(ref or ""):
            raise EditError("A connection joins two connectors (component.connector).")
    if left == right:
        raise EditError("A connector cannot be connected to itself.")
    cls, items = _class(text, cls_name)
    for statement in _statements(items, _own(items, cls)):
        pair = _connect(items, statement)
        if pair and set(pair) == {left, right}:
            raise EditError("These connectors are already connected.")
    _, equation = _insert_points(text, items, cls)
    indent = _indent(text, cls)
    red, green, blue = (max(0, min(255, int(c))) for c in color)
    line = (
        f"{indent}connect({left}, {right}) annotation(Line(points={_points(points)}, "
        f"color={{{red},{green},{blue}}}));\n"
    )
    head = "" if _has_equation_section(items, cls) else f"{indent[:-2]}equation\n"
    start = text.rfind("\n", 0, equation) + 1
    if text[start:equation].strip():
        head = "\n" + head
        start = equation
    return text[:start] + head + line + text[start:]


def _statement_span(text: str, items: list[Token], statement: list[int]) -> tuple[int, int]:
    """The statement's whole lines when it has them to itself, else just its tokens."""

    start, end = items[statement[0]].start, items[statement[-1]].end
    line_start = text.rfind("\n", 0, start) + 1
    line_end = _line_end(text, end)
    if not text[line_start:start].strip() and not text[end:line_end].strip():
        return line_start, min(len(text), line_end + 1)
    return start, end


def delete_component(text: str, cls_name: str, name: str) -> str:
    if not IDENT.match(name or ""):
        raise EditError("Not a component name.")
    cls, items = _class(text, cls_name)
    statements = _statements(items, _own(items, cls))
    spans = []
    for statement in statements:
        if _declares(items, statement, name):
            if any(items[i].text == "," for i in statement if True) and _commas_at_top(
                items, statement
            ):
                raise EditError(
                    f"{name} is declared together with other components: delete it in the text."
                )
            spans.append(_statement_span(text, items, statement))
        pair = _connect(items, statement)
        if pair and any(
            ref == name or ref.startswith(name + ".") or ref.startswith(name + "[") for ref in pair
        ):
            spans.append(_statement_span(text, items, statement))
    if not spans:
        raise EditError(f"{name} is not declared in {cls_name} (it may be inherited).")
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + text[end:]
    return text


def _commas_at_top(items: list[Token], statement: list[int]) -> bool:
    depth = 0
    for i in statement:
        if items[i].text in ("(", "{", "["):
            depth += 1
        elif items[i].text in (")", "}", "]"):
            depth -= 1
        elif items[i].text == "," and depth == 0:
            return True
    return False


def delete_connection(text: str, cls_name: str, left: str, right: str) -> str:
    cls, items = _class(text, cls_name)
    for statement in _statements(items, _own(items, cls)):
        pair = _connect(items, statement)
        if pair and set(pair) == {left, right}:
            start, end = _statement_span(text, items, statement)
            return text[:start] + text[end:]
    raise EditError("This connection is not in the class's text (it may be inherited).")


def _matching(items: list[Token], open_index: int) -> int:
    depth = 0
    for i in range(open_index, len(items)):
        if items[i].text in ("(", "{", "["):
            depth += 1
        elif items[i].text in (")", "}", "]"):
            depth -= 1
            if depth == 0:
                return i
    raise EditError("Unbalanced brackets.")


def _declaration(text: str, cls_name: str, name: str) -> tuple[list[Token], list[int], int]:
    """The tokens, the declaration statement of ``name`` and the index of its name token."""

    if not IDENT.match(name or ""):
        raise EditError("Not a component name.")
    cls, items = _class(text, cls_name)
    for statement in _statements(items, _own(items, cls)):
        if _declares(items, statement, name):
            depth = 0
            for i in statement:
                if items[i].text in ("(", "{", "["):
                    depth += 1
                elif items[i].text in (")", "}", "]"):
                    depth -= 1
                elif depth == 0 and items[i].text == name and i != statement[0]:
                    return items, statement, i
    raise EditError(f"{name} is not declared in {cls_name} (it may be inherited).")


def move(text: str, cls_name: str, name: str, extent, rotation: float = 0.0, origin=None) -> str:
    """Set the component's placement (its transformation; an iconTransformation is kept)."""

    items, statement, _ = _declaration(text, cls_name, name)
    new = placement(extent, rotation, origin)
    annotation = next((i for i in statement if items[i].text == "annotation"), None)
    if annotation is None:
        end = items[statement[-1]].start  # the ";"
        return text[:end] + f" annotation({new})" + text[end:]
    open_index = annotation + 1
    close = _matching(items, open_index)
    for i in range(open_index, close):
        if items[i].text == "Placement" and items[i + 1].text == "(":
            placement_close = _matching(items, i + 1)
            inner = text[items[i + 1].end : items[placement_close].start]
            icon = re.search(r"iconTransformation\s*\(", inner)
            keep = ""
            if icon:
                start = icon.start()
                depth = 0
                for position in range(icon.end() - 1, len(inner)):
                    if inner[position] == "(":
                        depth += 1
                    elif inner[position] == ")":
                        depth -= 1
                        if depth == 0:
                            keep = ", " + inner[start : position + 1]
                            break
            replacement = new[:-1] + keep + ")"
            return text[: items[i].start] + replacement + text[items[placement_close].end :]
    insert = items[open_index].end
    return text[:insert] + new + ", " + text[insert:]


def set_modifiers(text: str, cls_name: str, name: str, values: Mapping[str, str | None]) -> str:
    """Set (or, with an empty value, remove) the component's modifiers ``name(k=2, T=1)``."""

    for key, value in values.items():
        if not CONNECTOR_REF.match(key or "") or "[" in key:
            raise EditError(f"Not a parameter name: {key}")
        if value not in (None, "") and (not VALUE.match(str(value)) or ";" in str(value)):
            raise EditError(f"Not a value Models can write for {key}.")
    items, statement, name_index = _declaration(text, cls_name, name)
    after = name_index + 1
    while after < len(items) and items[after].text == "[":
        after = _matching(items, after) + 1
    existing: list[tuple[str, str]] = []
    span = None
    if after < len(items) and items[after].text == "(":
        close = _matching(items, after)
        span = (items[after].start, items[close].end)
        inner = text[items[after].end : items[close].start]
        depth, current, parts = 0, "", []
        for char in inner:
            if char in "({[":
                depth += 1
            elif char in ")}]":
                depth -= 1
            if char == "," and depth == 0:
                parts.append(current)
                current = ""
            else:
                current += char
        if current.strip():
            parts.append(current)
        for part in parts:
            key, sep, value = part.partition("=")
            existing.append((key.strip(), value.strip()) if sep else (part.strip(), ""))
    merged = list(existing)
    for key, value in values.items():
        index = next(
            (i for i, (k, _) in enumerate(merged) if k == key or k.split()[-1:] == [key]), None
        )
        if value in (None, ""):
            if index is not None:
                merged.pop(index)
        elif index is not None:
            merged[index] = (merged[index][0], str(value).strip())
        else:
            merged.append((key, str(value).strip()))
    body = ", ".join(f"{k}={v}" if v else k for k, v in merged)
    replacement = f"({body})" if merged else ""
    if span is None:
        insert = items[after - 1].end
        return text[:insert] + replacement + text[insert:]
    return text[: span[0]] + replacement + text[span[1] :]


def set_binding(text: str, cls_name: str, name: str, value: str) -> str:
    """Set the value a declaration is bound to, ``parameter Real k = <value> "Gain";``: a block's
    default (owner, 2026-10-27: a block's defaults change on its page, as a new version). Its
    modifiers, comment and annotation stay."""

    value = value.strip()
    if not value or not VALUE.match(value) or ";" in value or '"' in value:
        raise EditError(f"Not a value Models can write for {name}.")
    items, statement, name_index = _declaration(text, cls_name, name)
    after = name_index + 1
    while after < len(items) and items[after].text in ("[", "("):
        after = _matching(items, after) + 1
    if after < len(items) and items[after].text == "=":
        start = items[after].end
        end_index = after + 1
        depth = 0
        while end_index <= statement[-1]:
            item = items[end_index]
            if item.text in ("(", "{", "["):
                depth += 1
            elif item.text in (")", "}", "]"):
                depth -= 1
            elif depth == 0 and (item.kind == "string" or item.text in ("annotation", ";")):
                break
            end_index += 1
        end = items[end_index - 1].end
        return text[:start] + f" {value}" + text[end:]
    insert = items[after - 1].end
    return text[:insert] + f" = {value}" + text[insert:]


def rename_class(text: str, old: str, new: str, *, within: str) -> str:
    """The text of one top-level class file under another name and package: ``within``, the
    class's own name and its ``end`` (a block duplicated into another library)."""

    if not IDENT.match(new or ""):
        raise EditError("Not a class name.")
    body = re.sub(r"^\s*within\b[^;]*;\s*", "", text, count=1)
    body = re.sub(rf"\b(block|model|class)\s+{re.escape(old)}\b", rf"\1 {new}", body, count=1)
    body = re.sub(rf"\bend\s+{re.escape(old)}\s*;", f"end {new};", body)
    return f"within {within};\n{body.lstrip()}"


def set_image(text: str, cls_name: str, data_url: str) -> str:
    """Put a picture in the class's ``Icon`` (a ``Bitmap`` with ``imageSource``) or take it out
    (``data_url`` ""). Other graphics of the icon stay; the image is checked before
    (``plantcraft_sdk.images.block_image``)."""

    cls, items = _class(text, cls_name)
    source = data_url.partition(",")[2] if data_url else ""
    bitmap = f'Bitmap(extent={{{{-100,-100}},{{100,100}}}}, imageSource="{source}")'
    statement = next(
        (s for s in _statements(items, _own(items, cls)) if items[s[0]].text == "annotation"),
        None,
    )
    if statement is None:
        if not source:
            return text
        end = items[cls.body_end].start
        line_start = text.rfind("\n", 0, end) + 1
        indent = _indent(text, cls)
        added = f"{indent}annotation(Icon(graphics={{{bitmap}}}));\n"
        if text[line_start:end].strip():
            return text[:end] + "\n" + added + text[end:]
        return text[:line_start] + added + text[line_start:]
    open_index = statement[0] + 1
    close = _matching(items, open_index)
    inner = (items[open_index].end, items[close].start)
    body = text[inner[0] : inner[1]]
    old = BITMAP_CALL.search(body)
    if old:
        if source:
            body = body[: old.start()] + bitmap + body[old.end() :]
        else:
            # Out with the comma that joined it to the next graphic, or the one before it.
            after = re.match(r"\s*,\s*", body[old.end() :])
            before = re.search(r",\s*$", body[: old.start()])
            if after:
                body = body[: old.start()] + body[old.end() + after.end() :]
            elif before:
                body = body[: before.start()] + body[old.end() :]
            else:
                body = body[: old.start()] + body[old.end() :]
            if re.fullmatch(r"\s*Icon\s*\(\s*graphics\s*=\s*\{\s*\}\s*\)\s*", body):
                # The annotation held only the picture (as set_image wrote it): out it goes.
                start = text.rfind("\n", 0, items[statement[0]].start) + 1
                end = _line_end(text, items[statement[-1]].end)
                if text[start : items[statement[0]].start].strip():
                    start = items[statement[0]].start
                return text[:start] + text[min(len(text), end + 1) :]
        return text[: inner[0]] + body + text[inner[1] :]
    if not source:
        return text
    graphics = re.search(r"\bIcon\s*\((?:[^()]|\([^()]*\))*?\bgraphics\s*=\s*\{", body, re.S)
    icon = re.search(r"\bIcon\s*\(", body)
    if graphics:
        at = graphics.end()
        rest = body[at:].lstrip()
        body = body[:at] + bitmap + ("" if rest.startswith("}") else ", ") + body[at:]
    elif icon:
        at = icon.end()
        rest = body[at:].lstrip()
        body = (
            body[:at]
            + f"graphics={{{bitmap}}}"
            + ("" if rest.startswith(")") else ", ")
            + body[at:]
        )
    else:
        joined = ", " if body.strip() else ""
        body = f"Icon(graphics={{{bitmap}}}){joined}{body.lstrip()}"
    return text[: inner[0]] + body + text[inner[1] :]


def classes(text: str) -> list[ClassDef]:
    return flatten(outline(text))
