"""HTTP routes: prompts for an AI assistant ("Copy as prompt", ``docs/design/copy-prompt.md``).

Each answer is ``plantcraft_sdk.prompts.Prompt.render()``: the text the interface copies, its
parts and what was left out for length. The asset tree prompt (Assets › Import) asks for the
asset file's own JSON, the format that carries everything an import reads. The plant map prompt carries the file's format, an
example and the asset types, never a source's address, user name or password: sources are set up
in Settings, and the assistant is asked only for assets, signals, loops and relations.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from plantcraft_sdk.assets import RELATION_TYPES
from plantcraft_sdk.prompts import Prompt, json_part, question_of, text_part
from processcraft.api.deps import CurrentUser, Runtime
from processcraft.i18n import t
from processcraft.platform import assetfile, plantmap

router = APIRouter(prefix="/api/prompts")

# Sections the assistant fills in; sources (addresses, sign-in) stay in Setup.
SKIPPED_SECTIONS = {"sources"}


def _map_questions() -> dict[str, str]:
    return {
        "build": t(
            "Build the plant map from the documents I attach (equipment manuals, I/O lists, "
            "P&IDs, data sheets). Answer only with one JSON object in the format below, "
            "without comments. Use the tags exactly as they appear in the documents and never "
            "invent one: when a tag is missing, leave the field empty and say so in the asset's "
            "description. Each control loop (FIC, PIC, TIC, LIC...) becomes a row in loops with "
            "its PV, SP, OP and mode tags."
        ),
        "review": t(
            "Review this plant map file that I paste after this prompt: say which rows break the "
            "format below, which assets have no parent, which loops miss a PV, SP or OP, and "
            "answer with the corrected JSON."
        ),
    }


def _format_text(reference: list[dict[str, Any]]) -> str:
    """The sections and columns as a short list (as JSON it was most of the size limit)."""

    lines: list[str] = []
    for section in reference:
        lines += ["", f"### {section['name']} ({section['label']})"]
        for column in section["columns"]:
            needed = f" ({t('required')})" if column["required"] else ""
            lines.append(f"- `{column['name']}`{needed}: {column['description']}")
    return "\n".join(lines).strip()


@router.get("/plant-map")
def plant_map_prompt(
    _user: CurrentUser,
    rt: Runtime,
    question: str | None = Query(default=None, max_length=40),
) -> dict[str, Any]:
    """The plant map's import format, an example and the asset types, as a prompt."""

    reference = [
        section
        for section in plantmap.format_reference(rt.platform)
        if section["name"] not in SKIPPED_SECTIONS
    ]
    example = {
        key: value
        for key, value in plantmap.template(rt.platform).items()
        if key not in SKIPPED_SECTIONS
    }
    kinds = [
        {"kind": item["kind"], "label": item["label"], "parent": item["parent"]}
        for item in rt.workspace.assets.kinds()
    ]
    prompt = Prompt(
        module="PlantCraft",
        title=t("Plant map import"),
        subject=t(
            "the format of the plant map file, which creates the plant's assets, signals and "
            "control loops in one import"
        ),
        question=question_of(_map_questions(), question, "build"),
        parts=[
            text_part(t("File format: every section and column"), _format_text(reference)),
            json_part(t("Example file"), example),
            json_part(t("Asset types of this installation"), kinds),
        ],
        notes=[
            t('The file starts with "format": "{format}".', format=plantmap.FORMAT),
            t("asset_id has no spaces; parent_id names another asset_id of the file or is empty."),
            t(
                "Never write passwords, addresses or user names: data sources are set up in Settings."
            ),
        ],
    )
    return prompt.render()


def _tree_questions() -> dict[str, str]:
    return {
        "build": t(
            "Build the asset tree from the documents I attach (equipment lists, P&IDs, data "
            "sheets, maintenance plans, a spreadsheet). Answer only with one JSON object in the "
            "format below, without comments. Use the tags and names exactly as they appear in the "
            "documents and never invent one: when something is missing, leave the field empty "
            "and say so in the asset's description."
        ),
        "convert": t(
            "Convert the export of another system that I paste after this prompt (a spreadsheet, "
            "a CMMS or EAM equipment list, a PI AF or ISA-95 file) into the JSON format below. "
            "Keep its hierarchy, map each level to one of the asset types listed, and put the "
            "columns that have no field of their own in attributes."
        ),
        "review": t(
            "Review this asset file that I paste after this prompt: say which assets break the "
            "format below, which have a type that does not exist or a parent that is not in the "
            "file, and answer with the corrected JSON."
        ),
    }


def _type_summary(resolved: dict[str, Any]) -> dict[str, Any]:
    """A type as the assistant needs it: where it goes, its fields and its signal roles."""

    return {
        "type": resolved["id"],
        "name": resolved["name"],
        "parent_type": resolved.get("parent"),
        "children": resolved.get("children") or [],
        "attributes": [
            {
                key: entry[key]
                for key in ("key", "data_type", "unit", "options")
                if entry.get(key) not in (None, "", [])
            }
            for entry in resolved.get("attributes") or []
        ],
        "signal_roles": [entry["key"] for entry in resolved.get("roles") or []],
    }


@router.get("/asset-tree")
def asset_tree_prompt(
    _user: CurrentUser,
    rt: Runtime,
    question: str | None = Query(default=None, max_length=40),
) -> dict[str, Any]:
    """The asset file's JSON format, an example and this installation's types, as a prompt."""

    example = {
        "format": assetfile.FORMAT,
        "version": assetfile.VERSION,
        "assets": [
            {
                "asset_id": "U-100",
                "name": "Crude distillation",
                "type": "unit",
                "parent_id": "",
                "description": "",
                "attributes": {"unit_code": "100"},
                "signals": [],
            },
            {
                "asset_id": "P-101A",
                "name": "Crude charge pump A",
                "type": "equipment",
                "parent_id": "U-100",
                "description": "Centrifugal pump, 250 m³/h.",
                "attributes": {},
                "signals": [{"role": "flow", "tag": "FI-101.PV"}],
            },
        ],
        "relations": [{"from": "P-101A", "type": "feeds", "to": "U-100"}],
    }
    fields = "\n".join(
        [
            t("- `asset_id` (required): the asset's tag or code, unique, without spaces."),
            t("- `name` (required): what people call it."),
            t("- `type` (required): one of the asset types below."),
            t(
                "- `parent_id`: the asset_id of the asset it sits in, in the file or already in "
                "the tree; empty puts it at the top."
            ),
            t("- `description`: free text."),
            t("- `attributes`: the type's fields, by key, with values of their data type."),
            t(
                "- `signals`: the measurements the asset uses, each with its `role` (one of the "
                "type's signal roles) and the `tag` as the historian knows it."
            ),
            t(
                "- `relations`: links between two assets of the file or the tree; `type` is one "
                "of {types}.",
                types=", ".join(f"`{key}`" for key in RELATION_TYPES),
            ),
        ]
    )
    types = [_type_summary(item) for item in rt.workspace.assets.types.all_resolved()]
    prompt = Prompt(
        module="PlantCraft",
        title=t("Asset tree import"),
        subject=t(
            "the format of the asset file, which adds the plant's asset tree (each asset with "
            "its type, parent, record, signals by role and relations) in Assets › Import"
        ),
        question=question_of(_tree_questions(), question, "build"),
        parts=[
            text_part(t("Fields of each asset"), fields),
            json_part(t("Example file"), example),
            json_part(t("Asset types of this installation"), types),
        ],
        notes=[
            t('The file starts with "format": "{format}".', format=assetfile.FORMAT),
            t(
                "Save the answer as a .json file and choose it in Assets › Import: it is reviewed "
                "before anything changes."
            ),
            t(
                "Never write passwords, addresses or user names: data sources are set up in the "
                "Historian."
            ),
        ],
    )
    return prompt.render()
