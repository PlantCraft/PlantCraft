"""What LinkCraft explains to the suite's assistants (PlantCraft API v1 ``/knowledge``).

A specialist of PlantCraft answers about LinkCraft's objects from these texts:

- **Algorithms** (``algorithm:linkcraft/<id>``): what the algorithm is for, the assets and
  signals it reads, when to use it, how to read its verdict and what an assistant must check
  (``plantcraft_sdk.blocks.AlgorithmDocs``), then its blocks in the order they run, with their
  wires and the ports it records. People write the docs in the algorithm editor; a field left
  empty is generated from the diagram.
- **Blocks** (``block:linkcraft/<id>``): each block of the catalog, with the same headings for
  all of them (what it does, how to read it, inputs, outputs, parameters, limits).
- **Runs** (``run:linkcraft/<id>``): a loop run's report (status, window, the blocks' verdicts)
  and a Signal quality run's counts. Written when someone asks the assistant about the run, as
  transient texts PlantCraft drops after 90 days.

Publishing never fails the work around it: without an app key, or with a PlantCraft that does
not serve ``/knowledge`` yet, nothing is written (``SuiteClient.put_knowledge``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plantcraft_sdk.blocks import ALGORITHM_FIELDS, Plan, algorithm_markdown, block_markdown
from plantcraft_sdk.refs import asset_ref

from linkcraft.blocks.algorithms import SIGNAL_QUALITY
from linkcraft.blocks.catalog import CATALOG, HEALTH_ID, compile_algorithm, listed, method_of
from linkcraft.blocks.convert import diagram_of
from linkcraft.blocks.guide import new_block_guide
from linkcraft.catalog.labels import METHOD_LABELS
from linkcraft.i18n import t

APP_ID = "linkcraft"
DOC_FIELDS = ALGORITHM_FIELDS
MAX_DOC = 4000
SIGNAL_RUN_PREFIX = "signal-quality-"


def algorithm_ref(algorithm_id: str) -> str:
    return f"algorithm:{APP_ID}/{algorithm_id}"


def block_ref(block_id: str) -> str:
    return f"block:{APP_ID}/{block_id}"


def run_ref(run_id: str) -> str:
    return f"run:{APP_ID}/{run_id}"


def generated_docs(name: str, description: str, plan: Plan | None) -> dict[str, str]:
    """The documentation an algorithm gets from its diagram where nobody wrote one."""

    nodes = list(plan.nodes.values()) if plan else []
    blocks = [str(node.get("block") or "") for node in nodes]
    roles = [
        str((node.get("parameters") or {}).get("role") or "")
        for node in nodes
        if str(node.get("block") or "").startswith("input.")
    ]
    methods = [method_of(block) for block in blocks if method_of(block)]
    purpose = description.strip() or t("What does {name} find on its targets?", name=name)
    if not purpose.endswith((".", "?")):
        purpose += "."
    assets = t(
        "The assets it runs on, reading the signal roles {roles}; a role the asset lacks gives "
        "no data to the blocks that need it.",
        roles=", ".join(dict.fromkeys(role.upper() for role in roles if role)) or "PV",
    )
    when = t(
        "When its blocks answer the question above: it runs {count} methods. Compare with the "
        "algorithms Analytics ships before writing a new one.",
        count=len(methods),
    )
    if HEALTH_ID in blocks:
        reading = t(
            "The health (0 to 100, 100 = best) combines the results wired to Loop health; the "
            "limiting method explains a low score. No health when the data is not usable or "
            "the loop is in manual, which is not a fault of the loop."
        )
    else:
        reading = t(
            "Each result has a level (OK, Warning, Critical or Unknown), a score and a message; "
            "unknown means a block could not judge, which is not a fault."
        )
    assistant = t(
        "Explain the result in plain words for a process engineer: which block limits it, why, "
        "and what to verify in the plant. Never suggest changing controller settings yourself."
    )
    return {
        "purpose": purpose,
        "assets": assets,
        "when": when,
        "reading": reading,
        "assistant": assistant,
    }


def algorithm_plan(profile: Mapping[str, Any]) -> Plan:
    return compile_algorithm(diagram_of(profile.get("method_config") or {}))


def algorithm_docs(profile: Mapping[str, Any], plan: Plan | None = None) -> dict[str, str]:
    """What people wrote, completed with what the diagram says."""

    config = profile.get("method_config") or {}
    written = config.get("docs") if isinstance(config.get("docs"), Mapping) else {}
    generated = generated_docs(
        str(profile.get("name") or profile.get("profile_id")),
        str(profile.get("description") or ""),
        plan if plan is not None else algorithm_plan(profile),
    )
    return {key: t(str(written.get(key) or "").strip()) or generated[key] for key in DOC_FIELDS}


def algorithm_item(profile: Mapping[str, Any], root: str) -> dict[str, Any]:
    algorithm_id = str(profile["profile_id"])
    name = str(profile.get("name") or algorithm_id)
    plan = algorithm_plan(profile)
    return {
        "ref": algorithm_ref(algorithm_id),
        "kind": "algorithm",
        "title": t("Algorithm {name}", name=name)[:200],
        "text": algorithm_markdown(
            f"{t('Algorithm')}: {name}", algorithm_docs(profile, plan), plan, CATALOG, t
        ),
        "url": f"{root.rstrip('/')}/algorithms/{algorithm_id}",
    }


def block_items(root: str) -> list[dict[str, Any]]:
    """Every block of the catalog, as the assistant reads it."""

    return [
        {
            "ref": block_ref(block_id),
            "kind": "block",
            "title": t("Block {name}", name=t(block.spec.name))[:200],
            "text": block_markdown(block.spec, t),
            "url": f"{root.rstrip('/')}/blocks/{block_id}",
        }
        for block_id, block in list(CATALOG.items())
        if listed(block_id)
    ]


NEW_BLOCK = "new"


def new_block_item(root: str) -> dict[str, Any]:
    """How to write a new block, for the assistant asked to write one ("New block")."""

    return {
        "ref": block_ref(NEW_BLOCK),
        "kind": "block",
        "title": t("A new block"),
        "text": new_block_guide(),
        "url": f"{root.rstrip('/')}/blocks/new",
    }


def job_item(job: dict[str, Any], root: str, *, asset: bool = False) -> dict[str, Any]:
    """A loop run's report: what it read, what it found, why it failed."""

    summary = job.get("summary") or {}
    limiting = summary.get("limiting") or {}
    lines = [
        f"# {job.get('name') or t('Run')} ({t('loop')} {job['loop_id']})",
        t("Status of the run: {status}.", status=job.get("status")),
    ]
    if job.get("profile_id"):
        lines.append(t("Algorithm: {ref}.", ref=f"#{algorithm_ref(str(job['profile_id']))}"))
    if job.get("source_start"):
        lines.append(
            t("Data window: {start} to {end}.", start=job["source_start"], end=job["source_end"])
        )
    if job.get("error_message"):
        lines.append(t("Error: {error}", error=job["error_message"]))
    if summary.get("health") is not None:
        lines.append(
            t(
                "Loop health {health}/100, status {status}.",
                health=round(float(summary["health"])),
                status=summary.get("status"),
            )
        )
    elif summary.get("operating_state_reason"):
        lines.append(t("No health: {reason}", reason=summary["operating_state_reason"]))
    if limiting.get("method_id"):
        lines.append(
            t(
                "Limiting method: {method}. {finding}",
                method=METHOD_LABELS.get(limiting["method_id"]) or limiting["method_id"],
                finding=limiting.get("finding") or "",
            )
        )
    results = job.get("results") or []
    if results:
        lines.append(f"## {t('Methods')}")
        for item in results:
            label = METHOD_LABELS.get(item.get("method_id")) or item.get("method_id")
            finding = item.get("finding") or item.get("message") or ""
            lines.append(f"- {label}: {item.get('status')}. {finding}".rstrip())
    subjects = []
    if job.get("profile_id"):
        subjects.append(algorithm_ref(str(job["profile_id"])))
    if asset:
        subjects.append(asset_ref(str(job["loop_id"])))
    return {
        "ref": run_ref(str(job["job_id"])),
        "kind": "run_report",
        "title": f"{job.get('name') or t('Run')} · {job['loop_id']}"[:200],
        "text": "\n".join(lines),
        "subjects": subjects,
        "url": f"{root.rstrip('/')}/runs/{job['job_id']}",
        "transient": True,
    }


def signal_run_item(
    round_row: dict[str, Any], worst: list[dict[str, Any]], root: str
) -> dict[str, Any]:
    """A Signal quality run: its counts and the signals that did worst."""

    counts = round_row.get("counts") or {}
    run_id = f"{SIGNAL_RUN_PREFIX}{round_row['id']}"
    lines = [
        f"# {t('Signal quality')} #{round_row['id']}",
        t(
            "Status {status}, trigger {trigger}, started {started}, finished {finished}.",
            status=round_row.get("status"),
            trigger=round_row.get("trigger"),
            started=round_row.get("started_at"),
            finished=round_row.get("finished_at") or "—",
        ),
        t(
            "{signals} signals: {good} good, {suspect} suspect, {bad} bad, {unknown} unknown.",
            signals=round_row.get("signals") or 0,
            **{key: counts.get(key, 0) for key in ("good", "suspect", "bad", "unknown")},
        ),
    ]
    if round_row.get("error"):
        lines.append(t("Error: {error}", error=round_row["error"]))
    if worst:
        lines.append(f"## {t('Signals that need attention')}")
        for item in worst[:30]:
            lines.append(
                f"- {item.get('signal')}: {item.get('status')}. {item.get('message') or ''}".rstrip()
            )
    return {
        "ref": run_ref(run_id),
        "kind": "run_report",
        "title": f"{t('Signal quality')} #{round_row['id']}",
        "text": "\n".join(lines),
        "subjects": [algorithm_ref(SIGNAL_QUALITY)],
        "url": f"{root.rstrip('/')}/runs/{run_id}",
        "transient": True,
    }


def overview_item(
    rows: list[dict[str, Any]],
    algorithms: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    root: str,
) -> dict[str, Any]:
    """Everything Link judged, in a few lines: what the assistant page about all of Link reads
    first ("which loops are worst?", "which signals are bad?")."""

    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        by_status = counts.setdefault(row["kind"], {})
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    lines = [f"# {t('Analytics: everything it judged')}"]
    for kind, by_status in sorted(counts.items()):
        parts = ", ".join(f"{status} {count}" for status, count in sorted(by_status.items()))
        lines.append(
            t("- {kind}: {count} ({parts}).", kind=kind, count=sum(by_status.values()), parts=parts)
        )
    worst = [row for row in rows if row["status"] in {"alarm", "warning"}]
    if worst:
        lines.append(f"## {t('Worst first')}")
        for row in worst[:40]:
            value = row["measure"]["value"]
            measure = (
                f"{row['measure']['label']} {round(float(value))}" if value is not None else ""
            )
            limiting = METHOD_LABELS.get(row["limiting"] or "") or row["limiting"] or ""
            lines.append(
                f"- {row['kind']} {row['id']} ({row['caption'] or row['area'] or '—'}): "
                f"{row['status']}, {measure}. {limiting}: {row['finding']}".rstrip(" :.")
            )
    if algorithms:
        lines.append(f"## {t('Algorithms')}")
        for item in algorithms:
            lines.append(
                f"- #{algorithm_ref(str(item['profile_id']))} {item['name']}: "
                f"{item.get('description') or ''}".rstrip(": ")
            )
    if runs:
        lines.append(f"## {t('Latest runs')}")
        for job in runs[:15]:
            lines.append(
                f"- #{run_ref(str(job['job_id']))} {job.get('name') or ''} "
                f"({job.get('loop_id')}): {job.get('status')}, {job.get('created_at') or ''}"
            )
    return {
        "ref": f"app:{APP_ID}",
        "kind": "overview",
        "title": t("Analytics: everything it judged"),
        "text": "\n".join(lines),
        "subjects": [],
        "url": f"{root.rstrip('/')}/results",
        "transient": True,
    }
