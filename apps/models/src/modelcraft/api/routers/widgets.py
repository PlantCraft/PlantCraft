"""Models' widgets: declared in ``app.toml`` (``[[contributes.widgets]]``), drawn on Models'
Overview and on Desk's Today alike (PlantCraft ``docs/widgets.md``). Links are paths on this
host, under Models' prefix."""

from __future__ import annotations

from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk import utc
from plantcraft_sdk import widgets as w

from modelcraft.api.deps import CurrentUser, RuntimeDep, seen_runs, sees_study
from modelcraft.api.routers.models import list_models
from modelcraft.i18n import t
from modelcraft.meta import FILES

router = APIRouter(prefix="/api/widgets", tags=["widgets"])

STATE = {
    "done": "ok",
    "failed": "alarm",
    "running": "running",
    "queued": "queued",
    "cancelled": "off",
}
WORDS = {
    "done": "Done",
    "failed": "Failed",
    "running": "Running",
    "queued": "Queued",
    "cancelled": "Cancelled",
}
KIND = {"simulate": "Simulation", "fmu": "FMU export"}
# The activity's days and the stacks of each column (bottom first): the statuses they count.
DAYS = 14
ACTIVITY = (
    ("Done", "ok", ("done",)),
    ("Failed", "alarm", ("failed",)),
    ("Running or queued", "warning", ("running", "queued")),
    ("Cancelled", "unknown", ("cancelled",)),
)
# An optimization's objective, in the words of its study page (StudiesPage.tsx STATISTIC_WORDS).
STATISTIC_WORDS = {
    "final": "Final value",
    "overshoot": "Overshoot (%)",
    "settling": "Settling time (s)",
    "iae": "IAE",
    "min": "Smallest",
    "max": "Largest",
    "mean": "Mean",
    "integral": "Integral",
}


def _started(when: object) -> str | None:
    started = w.ago(when, t)
    return t("Started {when}", when=started) if started else None


@router.get("")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(FILES.manifest(), t)


def _model_href(root: str, item: dict[str, Any]) -> str:
    return f"{root}/models/{quote(item['project_id'], safe='')}/{quote(item['model'], safe='')}"


@router.get("/{widget_id}/options")
def widget_options(widget_id: str, rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    if widget_id != "model":
        raise HTTPException(404, t("Widget not found."))
    return w.options(
        w.option(f"{item['project_id']}/{item['model']}", item["name"], item.get("project"))
        for item in list_models(rt, user)
    )


@router.get("/{widget_id}")
def widget(
    widget_id: str,
    rt: RuntimeDep,
    user: CurrentUser,
    item: str | None = Query(default=None, max_length=500),
) -> dict[str, Any]:
    root = rt.settings.root_path
    # "projects" is the earlier name of "models": Overviews arranged before keep their widget.
    if widget_id in {"models", "projects"}:
        return w.items(
            [
                w.item(
                    entry["name"],
                    detail=t("Example") if entry["example"] else entry.get("description") or "",
                    value=t("{n} blocks", n=entry["blocks"]) if entry.get("diagram") else t("Code"),
                    href=_model_href(root, entry),
                )
                for entry in list_models(rt, user)[:8]
            ],
            href=f"{root}/models",
            empty=t("No model yet."),
        )
    if widget_id == "runs":
        return w.items(
            [
                w.item(
                    run.get("label") or run["model"],
                    detail=" · ".join(
                        part
                        for part in (
                            t(KIND.get(run["kind"], run["kind"])),
                            run.get("project_name"),
                            _started(run.get("created_at")),
                        )
                        if part
                    ),
                    state=STATE.get(run["status"]) if run["status"] in {"done", "failed"} else None,
                    href=f"{root}/runs/{quote(run['id'], safe='')}",
                )
                for run in seen_runs(rt, user, rt.runs.list(limit=8))
            ],
            href=f"{root}/executions",
            empty=t("No simulation yet."),
        )
    if widget_id == "run-status":
        runs = seen_runs(rt, user, rt.runs.list(limit=500))
        return w.split(
            [
                w.part(
                    t(WORDS[status]),
                    sum(1 for run in runs if run["status"] == status),
                    STATE[status],
                    f"{root}/executions",
                )
                for status in WORDS
            ],
            label=t("simulations"),
            href=f"{root}/executions",
            empty=t("No simulation yet."),
        )
    if widget_id == "studies":
        return w.items(
            [
                w.item(
                    study.get("name") or study["id"],
                    detail=study.get("model") or "",
                    value=t("{done} of {total}", done=study["done"], total=study["total"]),
                    state="alarm"
                    if study["failed"]
                    else "ok"
                    if study["total"] and study["done"] == study["total"]
                    else None,
                    href=f"{root}/studies/{quote(study['id'], safe='')}",
                )
                for study in _seen_studies(rt, user)[:8]
            ],
            href=f"{root}/studies",
            empty=t("No study yet: a study runs one model many times."),
        )
    if widget_id == "runner":
        runner = rt.workbench.runner()
        library = rt.workbench.library_state()
        libraries = ", ".join(
            f"{name} {version}" for name, version in (runner.get("libraries") or {}).items()
        )
        return w.facts(
            runner.get("omc") or t("Modelica runner"),
            [
                w.fact(t("Libraries"), libraries or "—"),
                w.fact(
                    t("Classes"),
                    library.get("classes")
                    if library.get("ready")
                    else t("Being read…")
                    if library.get("building")
                    else "—",
                ),
            ],
            status=t("Available") if runner.get("available") else t("Not available"),
            detail=None if runner.get("available") else runner.get("reason"),
            state="ok" if runner.get("available") else "alarm",
        )
    if widget_id == "model":
        return _model(rt, user, root, item)
    if widget_id == "activity":
        return _activity(rt, user, root)
    if widget_id == "latest-study":
        return _latest_study(rt, user, root)
    raise HTTPException(404, t("Widget not found."))


def _model(rt: Any, user: Any, root: str, item: str | None) -> dict[str, Any]:
    """One model: its diagram, its last run and how its runs went; without a choice, the first."""

    models = list_models(rt, user)
    project_id, _, model = (item or "").partition("/")
    found = next((m for m in models if m["project_id"] == project_id and m["model"] == model), None)
    found = found or (models[0] if models else None)
    if found is None:
        return w.facts(None, [], empty=t("No model yet."))
    runs = rt.runs.list(project_id=found["project_id"], model=found["model"], limit=200)
    last = runs[0] if runs else None
    return w.facts(
        found["name"],
        [
            w.fact(
                t("Diagram"),
                t("{n} blocks", n=found["blocks"]) if found.get("diagram") else t("Code"),
            ),
            w.fact(t("Simulations"), len(runs)),
            w.fact(
                t("Last simulation"), w.ago(last.get("created_at"), t) if last else t("Not run yet")
            ),
            w.fact(
                t("Failed"),
                sum(1 for run in runs if run["status"] == "failed"),
                "alarm" if any(run["status"] == "failed" for run in runs) else None,
            ),
        ],
        status=t(WORDS.get(last["status"], last["status"])) if last else t("Not run yet"),
        detail=found.get("project") or None,
        state=STATE.get(last["status"]) if last and last["status"] in {"done", "failed"} else None,
        href=_model_href(root, found),
    )


def _seen_studies(rt: Any, user: Any) -> list[dict[str, Any]]:
    """The studies on plant data the person sees, the latest run first."""

    scope = rt.asset_scope(user)
    return [study for study in rt.runs.studies() if sees_study(scope, study)]


def day_starts(now: datetime, zone: Any, days: int = DAYS) -> list[datetime]:
    """The midnights of the last ``days`` days on ``zone``'s clock, today's last."""

    today = now.astimezone(zone).date()
    return [
        datetime.combine(today - timedelta(days=back), datetime.min.time(), tzinfo=zone)
        for back in range(days - 1, -1, -1)
    ]


def _activity(rt: Any, user: Any, root: str, now: datetime | None = None) -> dict[str, Any]:
    """The simulations (single ones and studies') started each day of the last two weeks,
    stacked by status."""

    # The days of the installation's clock (the plant's); UTC while PlantCraft cannot say.
    zone = utc.resolve_zone(utc.LOCAL, rt.suite.time_zone())
    starts = day_starts(now or datetime.now(UTC), zone)
    edges = [start.timestamp() for start in starts]
    since = utc.utc_iso(starts[0])
    counts = [[0] * len(ACTIVITY) for _ in starts]
    for run in seen_runs(rt, user, rt.runs.simulations_since(since)):
        moment = utc.parse_instant(run.get("created_at"))
        stack = next((i for i, (_, _, has) in enumerate(ACTIVITY) if run["status"] in has), None)
        if moment is None or stack is None:
            continue
        counts[max(0, bisect_right(edges, moment.timestamp()) - 1)][stack] += 1
    return w.columns(
        [(edge * 1000, day) for edge, day in zip(edges, counts, strict=True)],
        stacks=[w.stack(t(label), state) for label, state, _ in ACTIVITY],
        step="day",
        value=sum(sum(day) for day in counts),
        label=t("simulations in {n} days", n=DAYS),
        href=f"{root}/executions",
        empty=t("No simulation in the last {n} days.", n=DAYS),
    )


def _number(value: Any) -> Any:
    return float(f"{value:.4g}") if isinstance(value, int | float) else value


def _latest_study(rt: Any, user: Any, root: str) -> dict[str, Any]:
    """The latest study or optimization that finished, and what it gave: the best values an
    optimization found, how many cases a sweep simulated. Quick simulations are not a study
    here (the latest simulations widget lists them)."""

    for study in _seen_studies(rt, user):
        if study.get("kind") == "quick" or not study["total"]:
            continue
        if study["queued"] or study["running"]:
            continue
        state = None
        if study.get("kind") == "optimization":
            state = rt.workbench.optimization(study["id"]) or {}
            if rt.workbench.optimizing(study["id"]) or state.get("status") in (
                "running",
                "waiting",
            ):
                continue
        return _study_facts(study, state, root)
    return w.facts(
        None, [], empty=t("No study has finished yet: a study runs one model many times.")
    )


def _study_facts(study: dict[str, Any], state: dict[str, Any] | None, root: str) -> dict[str, Any]:
    model = (study.get("model") or "").rpartition(".")[2]
    when = w.ago(study.get("last_run_at"), t)
    common = {
        "detail": f"{model} · {when}" if when else model,
        "href": f"{root}/studies/{quote(study['id'], safe='')}",
    }
    if state is not None:
        objective = ((study.get("spec") or {}).get("optimization") or {}).get("objective") or {}
        statistic = objective.get("statistic") or ""
        best = state.get("best") or {}
        rows = [
            w.fact(
                t(
                    "{statistic} of {variable}",
                    statistic=t(STATISTIC_WORDS.get(statistic, statistic)),
                    variable=objective.get("variable") or "",
                ),
                _number(best.get("objective")) if best else "—",
                # No simulation met every constraint: the closest, not a best.
                "warning" if best and not best.get("feasible") else None,
            ),
            *(w.fact(name, _number(value)) for name, value in (best.get("values") or {}).items()),
            w.fact(t("Simulations"), len(state.get("evaluations") or [])),
        ]
        failed = state.get("status") == "failed" or not best
        stopped = state.get("status") == "stopped"
        return w.facts(
            study.get("name") or study["id"],
            rows,
            status=t("Failed") if failed else t("Cancelled") if stopped else t("Best found"),
            state="alarm" if failed else None if stopped else "ok",
            **common,
        )
    swept = [str(item.get("name")) for item in (study.get("spec") or {}).get("sweep") or []]
    rows = [
        w.fact(t("Cases done"), t("{done} of {total}", done=study["done"], total=study["total"])),
        w.fact(t("Failed"), study["failed"], "alarm" if study["failed"] else None),
    ]
    if swept:
        rows.append(w.fact(t("Varied"), ", ".join(swept)))
    failed = study["failed"] and not study["done"]
    complete = study["done"] == study["total"]
    return w.facts(
        study.get("name") or study["id"],
        rows,
        status=t("Failed") if failed else t("Done") if complete else t("Partly done"),
        state="alarm" if failed else "ok" if complete else "warning",
        **common,
    )
