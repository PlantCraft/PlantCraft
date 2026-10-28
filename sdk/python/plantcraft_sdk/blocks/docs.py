"""Descriptions in one format: checked, served to the editor, written for the assistants.

Every block, port, parameter and algorithm of the suite is described the same way, because the
same text is the help people read and the context the suite's assistants answer from:

- ``check_block`` / ``check_algorithm`` list what is missing or too thin (an app's test suite
  fails on any; ``check_catalog`` runs them all);
- ``describe_block`` is the JSON the editor's palette and inspector read;
- ``block_markdown`` / ``algorithm_markdown`` are the texts published to the assistants, always
  with the same headings in the same order.

Texts are English source; ``t`` serves them in the reader's language.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from plantcraft_sdk.blocks.contract import (
    BLOCK_ID,
    ID,
    TYPE_DESCRIPTIONS,
    Block,
    BlockSpec,
    Port,
    parameter_unit,
)
from plantcraft_sdk.blocks.graph import Plan, label_of
from plantcraft_sdk.i18n import t

# Lengths (characters) each field is held to.
NAME = (3, 48)
SUMMARY = (20, 240)
DESCRIPTION = 80
READING = 30
PORT = 15
PARAMETER = 15
PURPOSE = (20, 240)
ALGORITHM_TEXT = 40


class AlgorithmDocs(BaseModel):
    """What an algorithm is for, in the format every algorithm follows.

    - ``purpose``: one sentence: the question it answers.
    - ``assets``: which assets it runs on and the signal roles it reads.
    - ``when``: when to use it, and when another algorithm fits better.
    - ``reading``: how its blocks combine into the final verdict.
    - ``assistant``: what an assistant checks before concluding, and what it must not claim.
    """

    model_config = ConfigDict(extra="ignore")

    purpose: str = ""
    assets: str = ""
    when: str = ""
    reading: str = ""
    assistant: str = ""


ALGORITHM_FIELDS = ("purpose", "assets", "when", "reading", "assistant")


def _sentence(text: str) -> bool:
    text = text.strip()
    return text.endswith((".", "?", "!")) and text.count(". ") == 0


def _port_problems(spec: BlockSpec, ports: tuple[Port, ...], side: str) -> list[str]:
    problems = []
    seen: set[str] = set()
    for port in ports:
        where = f"{spec.block_id} {side} {port.port_id}"
        if not ID.match(port.port_id):
            problems.append(f"{where}: the id is lower case, digits and _")
        if port.port_id in seen:
            problems.append(f"{where}: two ports with this id")
        seen.add(port.port_id)
        if not port.label.strip():
            problems.append(f"{where}: no label")
        if len(port.description.strip()) < PORT:
            problems.append(f"{where}: describe it in at least {PORT} characters")
        if side == "output" and len(port.types) != 1:
            problems.append(f"{where}: an output has exactly one type")
        for item in port.types:
            if item not in TYPE_DESCRIPTIONS:
                problems.append(f"{where}: unknown type {item}")
    return problems


def check_block(spec: BlockSpec) -> list[str]:
    """What the block's contract lacks; empty when it is complete."""

    problems: list[str] = []
    where = spec.block_id
    if not BLOCK_ID.match(spec.block_id):
        problems.append(f"{where}: the id is dotted lower case (library.name)")
    elif spec.block_id.split(".")[0] != spec.library:
        problems.append(f"{where}: the id starts with its library ({spec.library})")
    if not NAME[0] <= len(spec.name.strip()) <= NAME[1]:
        problems.append(f"{where}: name of {NAME[0]} to {NAME[1]} characters")
    docs = spec.docs
    if not SUMMARY[0] <= len(docs.summary.strip()) <= SUMMARY[1] or not _sentence(docs.summary):
        problems.append(
            f"{where}: summary is one sentence of {SUMMARY[0]} to {SUMMARY[1]} characters"
        )
    if len(docs.description.strip()) < DESCRIPTION:
        problems.append(f"{where}: description of at least {DESCRIPTION} characters")
    if len(docs.reading.strip()) < READING:
        problems.append(f"{where}: say how to read it in at least {READING} characters")
    problems += _port_problems(spec, spec.inputs, "input")
    problems += _port_problems(spec, spec.outputs, "output")
    for name, info in spec.parameters.model_fields.items():
        if len((info.description or "").strip()) < PARAMETER:
            problems.append(
                f"{where} parameter {name}: describe it in at least {PARAMETER} characters"
            )
    return problems


def check_algorithm(name: str, docs: AlgorithmDocs | Mapping[str, Any]) -> list[str]:
    """What an algorithm's documentation lacks; empty when it is complete."""

    docs = docs if isinstance(docs, AlgorithmDocs) else AlgorithmDocs.model_validate(docs or {})
    problems = []
    if not PURPOSE[0] <= len(docs.purpose.strip()) <= PURPOSE[1] or not _sentence(docs.purpose):
        problems.append(
            f"{name}: purpose is one sentence of {PURPOSE[0]} to {PURPOSE[1]} characters"
        )
    for key in ALGORITHM_FIELDS[1:]:
        if len(getattr(docs, key).strip()) < ALGORITHM_TEXT:
            problems.append(f"{name}: {key} of at least {ALGORITHM_TEXT} characters")
    return problems


def check_catalog(catalog: Mapping[str, Block]) -> list[str]:
    problems = []
    for block_id, block in catalog.items():
        if block.spec.block_id != block_id:
            problems.append(f"{block_id}: listed under another id ({block.spec.block_id})")
        problems += check_block(block.spec)
    return problems


def _port(port: Port, translate: Callable[..., str]) -> dict[str, Any]:
    return {
        "port": port.port_id,
        "types": list(port.types),
        "type": port.type,
        "label": translate(port.label),
        "description": translate(port.description),
        "unit": port.unit,
        "required": port.required,
        "multiple": port.multiple,
        "record": port.record,
        "low": port.low,
        "high": port.high,
        "better": port.better,
    }


def parameters_of(model: type[BaseModel], translate: Callable[..., str] = t) -> list[dict]:
    """Each parameter with its title, description, unit, default and JSON schema."""

    schema = model.model_json_schema()
    properties = schema.get("properties") or {}
    found = []
    for name, info in model.model_fields.items():
        prop = dict(properties.get(name) or {})
        prop.pop("title", None)
        description = translate(info.description) if info.description else ""
        prop["description"] = description
        found.append(
            {
                "name": name,
                "title": translate(info.title or name.replace("_", " ").capitalize()),
                "description": description,
                "unit": parameter_unit(model, name),
                "default": (
                    None if info.is_required() else info.get_default(call_default_factory=True)
                ),
                "schema": prop,
            }
        )
    return found


def block_image_path(spec: BlockSpec, route: str = "/api/blocks/{block_id}/image") -> str | None:
    """The app path of a block's image (``route`` filled in, with a tag of its content so a new
    image is a new URL), ``None`` for a block without one (round 9 M2)."""

    if not spec.image:
        return None
    from urllib.parse import quote

    from plantcraft_sdk.images import image_tag

    return f"{route.format(block_id=quote(spec.block_id, safe='.@'))}?v={image_tag(spec.image)}"


def describe_block(
    spec: BlockSpec,
    translate: Callable[..., str] = t,
    *,
    image_route: str = "/api/blocks/{block_id}/image",
) -> dict[str, Any]:
    """The block as the editor reads it (palette, inspector, ports). ``image`` is the app path of
    its picture (``image_route``), not the picture: a catalog stays small."""

    docs = spec.docs
    return {
        "block_id": spec.block_id,
        "version": spec.version,
        "library": spec.library,
        "group": translate(spec.group) if spec.group else "",
        "name": translate(spec.name),
        "summary": translate(docs.summary),
        "description": translate(docs.description),
        "reading": translate(docs.reading),
        "assumptions": [translate(item) for item in docs.assumptions],
        "limitations": [translate(item) for item in docs.limitations],
        "formula": docs.formula,
        "references": list(docs.references),
        "inputs": [_port(port, translate) for port in spec.inputs],
        "outputs": [_port(port, translate) for port in spec.outputs],
        "parameters": parameters_of(spec.parameters, translate),
        "parameter_schema": spec.parameters.model_json_schema(),
        "runs_on_missing": spec.runs_on_missing,
        "image": block_image_path(spec, image_route),
    }


def _ports_markdown(ports: list[dict[str, Any]], *, inputs: bool) -> list[str]:
    lines = []
    for port in ports:
        bits = [f"`{port['port']}`", " or ".join(port["types"])]
        if port["unit"]:
            bits.append(port["unit"])
        if inputs:
            bits.append(t("required") if port["required"] else t("optional"))
            if port["multiple"]:
                bits.append(t("any number of wires"))
        elif port["better"]:
            bits.append(
                t("higher is better") if port["better"] == "higher" else t("lower is better")
            )
        lines.append(f"- **{port['label']}** ({', '.join(bits)}): {port['description']}")
    return lines


def block_markdown(spec: BlockSpec, translate: Callable[..., str] = t) -> str:
    """The block for people and assistants, always with the same headings in the same order."""

    item = describe_block(spec, translate)
    lines = [
        f"## {item['name']} (`{spec.block_id}`)",
        "",
        item["summary"],
        "",
        f"### {t('What it does')}",
        "",
        item["description"],
        "",
        f"### {t('How to read it')}",
        "",
        item["reading"],
        "",
        f"### {t('Inputs')}",
        "",
        *(_ports_markdown(item["inputs"], inputs=True) or [t("None.")]),
        "",
        f"### {t('Outputs')}",
        "",
        *(_ports_markdown(item["outputs"], inputs=False) or [t("None.")]),
        "",
        f"### {t('Parameters')}",
        "",
    ]
    if item["parameters"]:
        for parameter in item["parameters"]:
            bits = []
            if parameter["unit"]:
                bits.append(parameter["unit"])
            if parameter["default"] is not None:
                bits.append(t("default {value}", value=parameter["default"]))
            limits = [
                f"{key} {parameter['schema'][key]}"
                for key in ("minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum")
                if key in parameter["schema"]
            ]
            bits += limits
            extra = f" ({', '.join(str(bit) for bit in bits)})" if bits else ""
            lines.append(
                f"- **{parameter['title']}** (`{parameter['name']}`){extra}: "
                f"{parameter['description']}"
            )
    else:
        lines.append(t("None."))
    for title, items in (
        (t("Assumptions"), item["assumptions"]),
        (t("Limitations"), item["limitations"]),
    ):
        if items:
            lines += ["", f"### {title}", "", *(f"- {entry}" for entry in items)]
    if item["formula"]:
        lines += ["", f"### {t('Formula')}", "", item["formula"]]
    if item["references"]:
        lines += ["", f"### {t('References')}", "", *(f"- {entry}" for entry in item["references"])]
    return "\n".join(lines).strip() + "\n"


def algorithm_markdown(
    name: str,
    docs: AlgorithmDocs | Mapping[str, Any],
    plan: Plan,
    catalog: Mapping[str, Block],
    translate: Callable[..., str] = t,
) -> str:
    """An algorithm for people and assistants: its own docs, then its blocks in run order."""

    docs = docs if isinstance(docs, AlgorithmDocs) else AlgorithmDocs.model_validate(docs or {})
    lines = [f"# {name}", ""]
    titles = {
        "purpose": t("Purpose"),
        "assets": t("Assets and signals it reads"),
        "when": t("When to use it"),
        "reading": t("How to read the verdict"),
        "assistant": t("Instructions for the assistant"),
    }
    for key in ALGORITHM_FIELDS:
        text = getattr(docs, key).strip()
        if text:
            lines += [f"## {titles[key]}", "", translate(text), ""]
    lines += [f"## {t('Blocks, in the order they run')}", ""]
    for node_id in plan.order:
        node = plan.nodes[node_id]
        block = catalog.get(node["block"])
        if block is None:
            continue
        wired = []
        for port_id, wires in plan.inputs.get(node_id, {}).items():
            sources = ", ".join(
                f"{label_of(plan.nodes[wire.source], catalog)} › {wire.source_port}"
                for wire in wires
            )
            wired.append(f"{port_id} ← {sources}")
        recorded = plan.recorded.get(node_id) or []
        parts = [
            f"- **{label_of(node, catalog)}** (`{block.spec.block_id}`): "
            f"{translate(block.spec.docs.summary)}"
        ]
        if wired:
            parts.append(f" {t('Inputs')}: {'; '.join(wired)}.")
        if recorded:
            parts.append(f" {t('Recorded in the historian')}: {', '.join(recorded)}.")
        lines.append("".join(parts))
    return "\n".join(lines).strip() + "\n"


__all__ = [
    "ALGORITHM_FIELDS",
    "AlgorithmDocs",
    "algorithm_markdown",
    "block_image_path",
    "block_markdown",
    "check_algorithm",
    "check_block",
    "check_catalog",
    "describe_block",
    "parameters_of",
]
