"""A block's interface for the diagram editor: its inputs, outputs and parameters.

A block of a library is placed in a model's diagram and wired by its signals. Its signals are
its real inputs and outputs (``Modelica.Blocks.Interfaces.RealInput``/``RealOutput``
connectors, ``input Real``/``output Real``, or those of the Modelica Standard Library's
interfaces it extends: ``SISO``, ``SI2SO``, ``SO``...); its parameters are its public
``parameter`` declarations. The interface is written in the catalog format every editor of the
suite reads (``@plantcraft/ui`` ``BlockSpec``), with the type ``real`` on every signal.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from typing import Any

from plantcraft_sdk.images import raw_image

from modelcraft.i18n import t
from modelcraft.modelica.declarations import ClassElements, class_elements, literal
from modelcraft.modelica.source import ClassDef, flatten, outline

SIGNAL = "real"
INPUTS = ("RealInput",)
OUTPUTS = ("RealOutput",)
# Connectors a diagram cannot wire yet: a block that has one is left out of the catalog.
UNSUPPORTED = ("BooleanInput", "BooleanOutput", "IntegerInput", "IntegerOutput")
# The Modelica Standard Library's interfaces a block may extend: (inputs, outputs).
BASES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "SO": ((), ("y",)),
    "SI": (("u",), ()),
    "SISO": (("u",), ("y",)),
    "SI2SO": (("u1", "u2"), ("y",)),
    "SignalSource": ((), ("y",)),
}
PARAMETER_TYPES = {"Real": "number", "Integer": "integer", "Boolean": "boolean"}


def _short(type_name: str) -> str:
    return type_name.rpartition(".")[2]


def _unquote(text: str | None) -> str:
    if not text:
        return ""
    value = text.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def _number(text: str | None) -> float | None:
    ok, value = literal(text)
    return (
        float(value)
        if ok and isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


# The picture of a block (round 9 M2): the Modelica ``Icon`` annotation's ``Bitmap`` with the
# image in ``imageSource`` (base64), as OMEdit and Dymola read it too.
BITMAP = re.compile(r'Bitmap\s*\([^()]*?imageSource\s*=\s*"([A-Za-z0-9+/=\s]*)"', re.S)


def icon_image(annotation: str) -> str:
    """The block's picture as a checked data URL, "" for none (``edit.set_image`` writes it)."""

    match = BITMAP.search(annotation or "")
    if not match:
        return ""
    try:
        data = base64.b64decode(re.sub(r"\s+", "", match.group(1)), validate=True)
    except (binascii.Error, ValueError):
        return ""
    return raw_image(data)


def _info(annotation: str) -> str:
    """The HTML of the class's ``Documentation(info = "<html>...</html>")``, "" for none."""

    match = re.search(
        r'Documentation\s*\(\s*info\s*=\s*"((?:\\.|[^"\\])*)"', annotation or "", re.S
    )
    return match.group(1).replace('\\"', '"') if match else ""


def _text(raw: str) -> str:
    """HTML as plain text: sub- and superscripts inline, paragraphs and line breaks kept."""

    raw = re.sub(r"<br\s*/?>", "\n", raw)
    raw = re.sub(r"<sub>(.*?)</sub>", r"\1", raw, flags=re.S)
    raw = re.sub(r"<sup>(.*?)</sup>", r"^\1", raw, flags=re.S)
    raw = re.sub(r"</p>\s*<p>", "\n\n", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    return " ".join(html.unescape(raw).split(" ")).strip()


# The parts of a block's documentation the Blocks page shows (as Analytics'
# blocks): the text before the first heading is what it does; an ``<h4>`` names each other part.
SECTIONS = {"how to read it": "reading", "formula": "formula"}


def documentation(annotation: str) -> str:
    """The text of the class's documentation, without tags (all of it, headings included)."""

    return _text(re.sub(r"<h4>(.*?)</h4>", r"\n\n\1\n", _info(annotation), flags=re.S))


def doc_sections(annotation: str) -> dict[str, str]:
    """``{"description", "reading", "formula"}`` of the documentation: what it does (the text
    before the first ``<h4>``), How to read it and Formula; "" for a part it lacks."""

    found = {"description": "", "reading": "", "formula": ""}
    parts = re.split(r"<h4>(.*?)</h4>", _info(annotation), flags=re.S)
    found["description"] = _text(parts[0])
    for title, body in zip(parts[1::2], parts[2::2], strict=False):
        key = SECTIONS.get(_text(title).lower())
        if key:
            found[key] = _text(body)
    return found


def humanize(short: str) -> str:
    """``ControlValve`` as ``Control valve``, ``PID`` and ``CSTR`` as they are."""

    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", short) or [short]
    first, rest = words[0], [word if word.isupper() else word.lower() for word in words[1:]]
    return " ".join([first[:1].upper() + first[1:], *rest])


def names(short: str, comment: str) -> tuple[str, str]:
    """(name, summary) of a block from its class comment: ``"Step: a value that jumps"`` gives
    ``("Step", "A value that jumps")``; a comment without such a name keeps the class's."""

    head, sep, rest = comment.partition(": ")
    if sep and 0 < len(head) <= 40 and rest.strip():
        rest = rest.strip()
        return head.strip(), rest[:1].upper() + rest[1:]
    return humanize(short), comment


def _port(declaration, *, direction: str) -> dict[str, Any]:
    return {
        "port": declaration.name,
        "types": [SIGNAL],
        "type": SIGNAL,
        "label": declaration.comment or declaration.name,
        "description": declaration.comment,
        "unit": _unquote(declaration.modifiers.get("unit")),
        "required": direction == "input",
        "multiple": False,
        "record": False,
    }


def _base_port(name: str, *, direction: str) -> dict[str, Any]:
    words = {"u": "Input", "u1": "First input", "u2": "Second input", "y": "Output"}
    return {
        "port": name,
        "types": [SIGNAL],
        "type": SIGNAL,
        "label": t(words[name]) if name in words else name,
        "description": "",
        "unit": "",
        "required": direction == "input",
        "multiple": False,
        "record": False,
    }


def _parameter(declaration) -> dict[str, Any] | None:
    kind = PARAMETER_TYPES.get(declaration.type)
    if kind is None:
        return None
    schema: dict[str, Any] = {"type": kind}
    if declaration.dims:
        schema = {"type": "array", "items": {"type": kind}}
    else:
        low = _number(declaration.modifiers.get("min"))
        high = _number(declaration.modifiers.get("max"))
        if low is not None and kind != "boolean":
            schema["minimum"] = low
        if high is not None and kind != "boolean":
            schema["maximum"] = high
    ok, default = literal(declaration.binding)
    unit = _unquote(declaration.modifiers.get("unit"))
    return {
        "name": declaration.name,
        "title": declaration.name,
        "description": declaration.comment,
        "unit": "" if unit == "1" else unit,
        # An expression (h_start = level0 * 2) is shown as written.
        "default": default if ok else (declaration.binding or None),
        "schema": schema,
    }


def interface(found: ClassElements) -> dict[str, Any]:
    """``{"inputs", "outputs", "parameters", "unsupported"}`` of a class's own elements."""

    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    unsupported: list[str] = []
    for base in found.extends:
        short = _short(base)
        if base.startswith("Modelica.Blocks.Interfaces.") and short in BASES:
            names_in, names_out = BASES[short]
            inputs += [_base_port(name, direction="input") for name in names_in]
            outputs += [_base_port(name, direction="output") for name in names_out]
        else:
            unsupported.append(f"extends {base}")
    for declaration in found.declarations:
        if declaration.section != "public":
            continue
        short = _short(declaration.type)
        if "parameter" in declaration.prefixes:
            item = _parameter(declaration)
            if item is not None and "final" not in declaration.prefixes:
                parameters.append(item)
            continue
        if "constant" in declaration.prefixes:
            continue
        if short in UNSUPPORTED or (
            ("input" in declaration.prefixes or "output" in declaration.prefixes)
            and declaration.type != "Real"
        ):
            unsupported.append(declaration.name)
            continue
        if declaration.dims and (short in INPUTS + OUTPUTS or declaration.type == "Real"):
            if (
                short in INPUTS + OUTPUTS
                or "input" in declaration.prefixes
                or "output" in declaration.prefixes
            ):
                unsupported.append(declaration.name)
                continue
        if short in INPUTS or (declaration.type == "Real" and "input" in declaration.prefixes):
            inputs.append(_port(declaration, direction="input"))
        elif short in OUTPUTS or (declaration.type == "Real" and "output" in declaration.prefixes):
            outputs.append(_port(declaration, direction="output"))
    return {
        "inputs": inputs,
        "outputs": outputs,
        "parameters": parameters,
        "unsupported": unsupported,
    }


def block_spec(
    item: ClassDef,
    text: str,
    *,
    library: str,
    library_name: str,
) -> dict[str, Any] | None:
    """The catalog entry of one class (None for a class that is not a block of signals)."""

    if item.restriction not in ("block", "model") or item.partial or item.short_class:
        return None
    found = class_elements(text, item.name)
    if found is None:
        return None
    ports = interface(found)
    if ports["unsupported"] or not (ports["inputs"] or ports["outputs"]):
        return None
    docs = doc_sections(found.annotation)
    name, summary = names(item.short, item.comment)
    return {
        "block_id": item.name,
        "library": library,
        "group": library_name,
        "name": name,
        "summary": summary,
        "description": docs["description"],
        "reading": docs["reading"],
        "assumptions": [],
        "limitations": [],
        "formula": docs["formula"] or None,
        "references": [],
        "inputs": ports["inputs"],
        "outputs": ports["outputs"],
        "parameters": ports["parameters"],
        "image": icon_image(found.annotation),
    }


def library_blocks(
    files: dict[str, str], *, library: str, library_name: str
) -> list[dict[str, Any]]:
    """Every block of a library's files, in the order its packages list them."""

    found = []
    for path in sorted(files):
        if not path.endswith(".mo"):
            continue
        text = files[path]
        for item in flatten(outline(text)):
            spec = block_spec(item, text, library=library, library_name=library_name)
            if spec is not None:
                found.append(spec)
    orders = {
        path.rpartition("/")[0].replace("/", "."): [
            line.strip() for line in text.splitlines() if line.strip()
        ]
        for path, text in files.items()
        if path.endswith("package.order")
    }

    def place(spec: dict[str, Any]) -> tuple:
        package, _, short = spec["block_id"].rpartition(".")
        order = orders.get(package, [])
        return (package, order.index(short) if short in order else len(order), short)

    return sorted(found, key=place)
