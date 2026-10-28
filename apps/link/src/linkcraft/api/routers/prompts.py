"""Prompts for an AI assistant ("Copy as prompt", PlantCraft ``docs/design/copy-prompt.md``).

A method's prompt carries its Python source, its declaration (inputs, parameters, references)
and its help page; a block's, its description and ports; an algorithm's, its diagram as JSON (the
format the editor saves) and its documentation. Each answer is
``plantcraft_sdk.prompts.Prompt.render()``: the text the interface copies.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk import methods as sdk_methods
from plantcraft_sdk.blocks import block_markdown, describe_block
from plantcraft_sdk.prompts import Prompt, code_part, json_part, question_of, text_part

from linkcraft.api.deps import CurrentUser, RuntimeDep
from linkcraft.api.routers.catalog import _algorithm, _get, method_source, methods
from linkcraft.blocks import CATALOG
from linkcraft.blocks.guide import new_block_guide
from linkcraft.catalog import help_docs
from linkcraft.catalog.loop_types import algorithm_id as current_id
from linkcraft.catalog.signal_checks import CHECKS as SIGNAL_CHECKS
from linkcraft.i18n import t
from linkcraft.knowledge import algorithm_item

router = APIRouter(prefix="/api/prompts")

Question = Query(default=None, max_length=40)


def _method_questions() -> dict[str, str]:
    return {
        "explain": t(
            "Explain what this method computes, step by step, which plant situations it catches "
            "and which it misses, and how to read its result."
        ),
        "adapt": t(
            "I want to adapt this method to my plant. Say which parameters to change first and "
            "why, and if the code itself must change, answer with the whole new file and a "
            "pytest test with synthetic data that shows the change."
        ),
        "review": t(
            "Review this method's code: find mistakes, cases where it gives a confident wrong "
            "answer instead of saying inconclusive, and parameters without a sensible limit."
        ),
    }


def _block_questions() -> dict[str, str]:
    return {
        "explain": t(
            "Explain what this block does, what each input and output carries and how to choose "
            "its parameters."
        ),
        "use": t(
            "Show where this block fits in an algorithm: which blocks feed it, which read its "
            "outputs, and a small example diagram in the algorithm JSON format."
        ),
    }


def _algorithm_questions() -> dict[str, str]:
    return {
        "explain": t(
            "Explain this algorithm block by block: what it reads, what each block decides and "
            "how to read its result."
        ),
        "review": t(
            "Review this algorithm for the loop type it is meant for: missing checks, blocks in "
            "the wrong order, parameters that do not suit it. Answer with the corrected diagram "
            "as JSON in the same format."
        ),
        "extend": t(
            "Extend this algorithm with what I describe after this prompt. Use only blocks of "
            "the catalog and answer with the whole diagram as JSON in the same format."
        ),
    }


def _method_item(method_id: str, user: Any, rt: Any) -> dict[str, Any]:
    found = next((item for item in methods(user, rt) if item["method_id"] == method_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Method not found."))
    return found


@router.get("/method/{method_id}")
def method_prompt(
    method_id: str, user: CurrentUser, rt: RuntimeDep, question: str | None = Question
) -> dict[str, Any]:
    item = _method_item(method_id, user, rt)
    source = method_source(method_id, user)
    configured = item.get("configured_defaults") or None
    page = (
        help_docs.check_markdown(method_id, configured)
        if method_id in SIGNAL_CHECKS
        else help_docs.loop_method_markdown(method_id, configured)
    )
    declaration = {
        key: item.get(key)
        for key in (
            "method_id",
            "label",
            "version",
            "maturity",
            "description",
            "required_signals",
            "parameters",
            "configured_defaults",
            "references",
            "assumptions",
            "limitations",
            "formula",
        )
        if item.get(key) not in (None, "", [], {})
    }
    parts = [
        code_part(t("Source ({file})", file=source["filename"]), source["source"], "python"),
        json_part(t("Declaration: inputs, parameters, references"), declaration),
    ]
    if page:
        parts.append(text_part(t("Help page"), page))
    parts.append(text_part(t("The SDK's method contract"), sdk_methods.__doc__ or ""))
    prompt = Prompt(
        module="Analytics",
        title=t("Method: {name}", name=item["label"]),
        subject=t(
            "an Analytics method: Python code, written with the plantcraft-sdk @method decorator, "
            "that reads a control loop's or a signal's data and returns a finding"
        ),
        question=question_of(_method_questions(), question, "explain"),
        parts=parts,
        notes=[
            t("Keep the method id ({id}) and its inputs by role.", id=method_id),
            t("A method that cannot judge returns inconclusive (NotEnoughData), never a guess."),
        ],
    )
    return prompt.render()


@router.get("/block/{block_id}")
def block_prompt(
    block_id: str, _user: CurrentUser, question: str | None = Question
) -> dict[str, Any]:
    found = CATALOG.get(block_id)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Block not found."))
    described = describe_block(found.spec, t)
    prompt = Prompt(
        module="Analytics",
        title=t("Block: {name}", name=described.get("name") or block_id),
        subject=t(
            "a block of Analytics' catalog: a step with typed inputs and outputs that algorithms "
            "(block diagrams) wire together"
        ),
        question=question_of(_block_questions(), question, "explain"),
        parts=[
            text_part(t("Description"), block_markdown(found.spec, t)),
            json_part(t("Ports and parameters"), described),
        ],
        notes=[t("Refer to blocks by their id ({id}).", id=block_id)],
    )
    return prompt.render()


@router.get("/algorithm/{algorithm_id}")
def algorithm_prompt(
    algorithm_id: str, _user: CurrentUser, rt: RuntimeDep, question: str | None = Question
) -> dict[str, Any]:
    profile = _get(rt, current_id(algorithm_id))
    algorithm = _algorithm(profile)
    used = sorted({str(node.get("block") or "") for node in algorithm["diagram"].get("nodes", [])})
    catalog = {
        block_id: describe_block(CATALOG[block_id].spec, t)
        for block_id in used
        if block_id in CATALOG
    }
    prompt = Prompt(
        module="Analytics",
        title=t("Algorithm: {name}", name=algorithm["name"]),
        subject=t(
            "an Analytics algorithm: a block diagram that runs on a control loop or an asset and "
            "gives a result"
        ),
        question=question_of(_algorithm_questions(), question, "explain"),
        parts=[
            json_part(t("Diagram (the format the editor saves)"), algorithm["diagram"]),
            text_part(t("Documentation"), algorithm_item(profile, rt.root_path)["text"]),
            json_part(t("Blocks it uses"), catalog),
        ],
        notes=[
            t(
                "A diagram may use only blocks of the catalog; wires join an output to an input of "
                "the same type."
            ),
        ],
    )
    return prompt.render()


@router.get("/new-block")
def new_block_prompt(
    _user: CurrentUser, request: str = Query(default="", max_length=4000)
) -> dict[str, Any]:
    """The prompt to write a new block with an assistant: what it must do, then Link's block
    file format, its rules, a complete example and the catalog. The answer is imported as is."""

    prompt = Prompt(
        module="Analytics",
        title=t("New block"),
        subject=t(
            "a new Analytics block: one calculation with typed inputs, outputs and parameters, and "
            "its Python code, written as a block file (plantcraft-block/1)"
        ),
        question=request.strip()
        or t("Write the block I describe after this prompt, as a block file."),
        parts=[text_part(t("How to write a block for Analytics"), new_block_guide(request))],
        notes=[t("Answer with the block file only: one JSON object.")],
    )
    return prompt.render()
