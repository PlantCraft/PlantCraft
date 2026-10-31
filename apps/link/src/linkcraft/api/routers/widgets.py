"""Link's widgets: declared in ``app.toml`` (``[[contributes.widgets]]``), drawn on Link's
Overview and on Desk's Today alike (PlantCraft ``docs/widgets.md``).

``GET /api/widgets`` lists them; ``GET /api/widgets/<id>`` gives one's data, read with the
person's own session, in the suite's shapes (``plantcraft_sdk.widgets``); a widget about one
schedule or one subject lists its choices at ``/api/widgets/<id>/options``. Links are paths on
this host, under Link's prefix.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk import widgets as w

from linkcraft.api.deps import CurrentUser, RuntimeDep
from linkcraft.api.plant_widgets import STATUS_WORDS, alarm_history, health_map
from linkcraft.api.routers.groups import _algorithms, _group, _outputs, _rows
from linkcraft.api.routers.losses import loop_effective_control, loop_losses
from linkcraft.api.routers.results import BUILDERS, KIND_LABELS, KINDS, _key, scoped_rows
from linkcraft.api.routers.runs import run_rows
from linkcraft.api.scope import Scope
from linkcraft.api.subjects import kind_of, latest_jobs
from linkcraft.config import app_manifest
from linkcraft.i18n import t

router = APIRouter(prefix="/api")

# A schedule reads as its worst subject.
WORST = ("alarm", "warning", "ok")


def _results(rt: Any, scope: Any, kind: str | None = None) -> list[dict[str, Any]]:
    kinds = [kind] if kind in BUILDERS else list(BUILDERS)
    return sorted(scoped_rows(rt, scope, kinds), key=_key)


def _schedules(rt: Any, scope: Any) -> list[dict[str, Any]]:
    algorithms = _algorithms(rt)
    schedules = sorted(
        rt.jobs.list_schedules(),
        key=lambda item: (item.get("kind") != "round", str(item["name"]).lower()),
    )
    return [_group(rt, item, algorithms, _rows(rt, item, scope)) for item in schedules]


def _started(when: object) -> str | None:
    """A time with what happened then ("Started 5 min ago"), never a bare time: the line below a
    row's name (PlantCraft ``docs/widgets.md``)."""

    ago = w.ago(when, t)
    return t("Started {when}", when=ago) if ago else None


def _last_run(when: object) -> str:
    ago = w.ago(when, t)
    return t("Last run {when}", when=ago) if ago else t("Not run yet")


def _measure(measure: dict[str, Any]) -> str | None:
    """A result's headline measure as the Results page writes it ("Health 30 %"), never a bare
    number a person cannot read."""

    value = measure.get("value")
    if value is None:
        return None
    if measure.get("format") in {"percent", "score"}:
        return f"{measure['label']} {round(float(value))} %"
    unit = f" {measure['unit']}" if measure.get("unit") else ""
    return f"{measure['label']} {float(value):.3g}{unit}"


def _state(counts: dict[str, int]) -> str | None:
    return next((key for key in WORST if counts.get(key)), None)


@router.get("/widgets")
def widgets(_user: CurrentUser) -> dict[str, Any]:
    return w.catalog(app_manifest(), t)


@router.get("/widgets/{widget_id}/options")
def widget_options(widget_id: str, rt: RuntimeDep, scope: Scope) -> dict[str, Any]:
    if widget_id == "results":
        return w.options(w.option(kind, t(KIND_LABELS[kind])) for kind in KINDS)
    if widget_id == "schedule":
        return w.options(
            w.option(item["id"], item["name"], (item.get("algorithm") or {}).get("name"))
            for item in _schedules(rt, scope)
        )
    if widget_id == "subject":
        found = []
        for schedule in rt.jobs.list_schedules():
            for row in _rows(rt, schedule, scope):
                found.append(
                    w.option(
                        f"{schedule['schedule_id']}/{row['id']}", row["name"], schedule["name"]
                    )
                )
        return w.options(found)
    raise HTTPException(status_code=404, detail=t("Widget not found."))


def _share(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}%"


@router.get("/widgets/{widget_id}")
def widget(
    widget_id: str,
    rt: RuntimeDep,
    scope: Scope,
    item: str | None = Query(default=None, max_length=400),
) -> dict[str, Any]:
    root = rt.root_path
    if widget_id == "attention":
        rows = [row for row in _results(rt, scope) if row["status"] in {"alarm", "warning"}]
        alarms = sum(1 for row in rows if row["status"] == "alarm")
        return w.number(
            len(rows),
            label=t("{alarms} in alarm", alarms=alarms)
            if rows
            else t("Nothing in alarm or warning"),
            state="alarm" if alarms else "warning" if rows else "ok",
            href=f"{root}/results?status=alarm,warning",
        )
    if widget_id == "results":
        kind = item if item in BUILDERS else None
        rows = _results(rt, scope, kind)
        query = f"kind={kind}&" if kind else ""
        return w.split(
            [
                w.part(
                    t(STATUS_WORDS[status]),
                    sum(1 for row in rows if row["status"] == status),
                    status,
                    f"{root}/results?{query}status={status}",
                )
                for status in STATUS_WORDS
            ],
            label=t(KIND_LABELS[kind]).lower() if kind else t("results"),
            href=f"{root}/results" + (f"?kind={kind}" if kind else ""),
            empty=t("Nothing judged yet."),
        )
    if widget_id == "in-alarm-history":
        return alarm_history(rt, scope, root)
    if widget_id == "health-map":
        return health_map(rt, scope, root)
    if widget_id == "worst":
        # Ranked by the result itself (the lowest health, quality or score first), not by
        # alarm before warning: a warning at 5 % reads worse than an alarm at 60 %.
        rows = sorted(
            (row for row in _results(rt, scope) if row["status"] in {"alarm", "warning"}),
            key=lambda row: (
                101 if row["measure"]["value"] is None else float(row["measure"]["value"]),
                row["status"] != "alarm",
            ),
        )[:8]
        return w.items(
            [
                w.item(
                    row["name"],
                    detail=row["finding"] or row["caption"],
                    value=_measure(row["measure"]),
                    state=row["status"],
                    href=f"{root}{row['path']}",
                )
                for row in rows
            ],
            href=f"{root}/results?status=alarm,warning",
            empty=t("Nothing in alarm or warning."),
        )
    if widget_id == "loop-losses":
        answer = loop_losses(scope, rt, days=7, until=None, group_by="area")
        labels = {cause["key"]: cause["label"] for cause in answer["causes"]}
        return w.items(
            [
                w.item(
                    row["key"],
                    detail=" · ".join(
                        f"{labels[key]} {row[key]:.0f} h"
                        for key in sorted(labels, key=lambda key: -row[key])
                        if row[key] >= 0.5
                    )
                    or t("No loop-hours lost"),
                    value=f"{row['lost_h']:.0f} h",
                    state="alarm"
                    if (row["effective_control"] or 100) < 50
                    else "warning"
                    if (row["effective_control"] or 100) < 80
                    else None,
                    href=f"{root}/results?kind=loop",
                )
                for row in answer["rows"]
            ],
            href=f"{root}/results?kind=loop",
            empty=t("No loop monitored in the last 7 days."),
        )
    if widget_id == "effective-control":
        rows = [row for row in loop_effective_control(scope, rt) if row["score"] is not None][:8]
        return w.items(
            [
                w.item(
                    row["name"],
                    detail=t(
                        "Normal mode {mode} · in band {band} · output free {free}",
                        mode=_share(row["normal_mode"]),
                        band=_share(row["in_band"]),
                        free=_share(row["not_saturated"]),
                    ),
                    value=f"{row['score']:.0f}%",
                    state="alarm"
                    if row["score"] < 50
                    else "warning"
                    if row["score"] < 80
                    else None,
                    href=f"{root}/loops/{quote(row['loop_id'], safe='')}",
                )
                for row in rows
            ],
            href=f"{root}/results?kind=loop",
            empty=t("No loop measured yet."),
        )
    if widget_id == "runs":
        return w.items(
            [
                w.item(
                    row["algorithm"]["name"],
                    detail=" · ".join(
                        part for part in (row["subject"], _started(row.get("started_at"))) if part
                    ),
                    state=row["state"] if row["state"] in {"ok", "warning", "alarm"} else None,
                    href=f"{root}{row['path']}",
                )
                for row in run_rows(rt, 8, scope)
            ],
            href=f"{root}/results/runs",
            empty=t("No run yet."),
        )
    if widget_id == "last-run":
        rows = run_rows(rt, 1, scope)
        if not rows:
            return w.facts(None, [], empty=t("No algorithm has run yet."))
        row = rows[0]
        return w.facts(
            row["algorithm"]["name"],
            [
                w.fact(t("Target"), row["subject"]),
                w.fact(t("Started"), w.ago(row.get("started_at"), t)),
                w.fact(t("Finding"), row.get("finding") or "—"),
            ],
            status=row["status_label"],
            state=row["state"] if row["state"] in {"ok", "warning", "alarm"} else None,
            href=f"{root}{row['path']}",
        )
    if widget_id == "schedules":
        return w.items(
            [
                w.item(
                    row["name"],
                    detail=" · ".join(
                        part
                        for part in (
                            row["when"],
                            _last_run(row["last_run_at"]),
                        )
                        if part
                    ),
                    state=_state(row["counts"]) if row["enabled"] else "off",
                    href=f"{root}{row['path']}",
                )
                for row in _schedules(rt, scope)
            ],
            href=f"{root}/executions",
            empty=t("No monitor yet: a monitor runs an algorithm on assets."),
        )
    if widget_id == "schedule":
        rows = _schedules(rt, scope)
        row = next((entry for entry in rows if entry["id"] == item), rows[0] if rows else None)
        if row is None:
            return w.facts(
                None, [], empty=t("No monitor yet: a monitor runs an algorithm on assets.")
            )
        counts = row["counts"]
        return w.facts(
            row["name"],
            [
                w.fact(t("Targets"), row["subjects"]),
                w.fact(t("Last run"), w.ago(row["last_run_at"], t) or t("Not run yet")),
                w.fact(
                    t("In alarm"), counts.get("alarm", 0), "alarm" if counts.get("alarm") else None
                ),
                w.fact(
                    t("In warning"),
                    counts.get("warning", 0),
                    "warning" if counts.get("warning") else None,
                ),
                w.fact(t("OK"), counts.get("ok", 0)),
                w.fact(t("Next run"), w.ago(row["next_run_at"], t) or "—"),
                w.fact(t("Unknown"), counts.get("unknown", 0)),
                w.fact(t("Algorithm"), (row.get("algorithm") or {}).get("name") or "—"),
            ],
            status=t("Running") if row["enabled"] else t("Paused"),
            detail=row["when"],
            state=_state(counts) if row["enabled"] else "off",
            href=f"{root}{row['path']}",
        )
    if widget_id == "subject":
        return _subject(rt, root, item, scope)
    raise HTTPException(status_code=404, detail=t("Widget not found."))


def _subject(rt: Any, root: str, item: str | None, scope: Any) -> dict[str, Any]:
    """One subject of one schedule: its latest result and each output of it (a specific
    execution). Without a choice, the first subject in alarm or warning."""

    schedules = {entry["schedule_id"]: entry for entry in rt.jobs.list_schedules()}
    wanted_schedule, _, wanted_subject = (item or "").partition("/")
    found: tuple[dict[str, Any], dict[str, Any]] | None = None
    if wanted_schedule in schedules:
        rows = _rows(rt, schedules[wanted_schedule], scope)
        row = next((entry for entry in rows if entry["id"] == wanted_subject), None)
        found = (schedules[wanted_schedule], row) if row else None
    if found is None:
        candidates = [
            (schedule, row) for schedule in schedules.values() for row in _rows(rt, schedule, scope)
        ]
        order = {"alarm": 0, "warning": 1, "ok": 2}
        candidates.sort(key=lambda pair: order.get(pair[1]["state"], 3))
        found = candidates[0] if candidates else None
    if found is None:
        return w.facts(None, [], empty=t("No monitor yet: a monitor runs an algorithm on assets."))
    schedule, row = found
    kind = kind_of(schedule)
    summary: dict[str, Any] = {}
    if kind == "job":
        job = latest_jobs(rt, schedule["schedule_id"], [row["id"]]).get(row["id"])
        summary = (job or {}).get("summary") or {}
    outputs = _outputs(rt, kind, row["id"], summary)
    measure = row.get("measure") or {}
    rows = [
        w.fact(
            str(output.get("name") or output.get("key") or ""),
            output.get("status_label")
            or (
                round(float(output["value"]), 2)
                if isinstance(output.get("value"), int | float)
                else output.get("value")
            )
            or "—",
            output.get("state") if output.get("state") in {"ok", "warning", "alarm"} else None,
        )
        for output in outputs
    ]
    if not rows and measure.get("value") is not None:
        rows = [w.fact(t(str(measure.get("label") or "Value")), round(float(measure["value"]), 1))]
    return w.facts(
        row["name"],
        rows,
        status=row.get("status_label") or None,
        detail=" · ".join(part for part in (schedule["name"], w.ago(row.get("at"), t)) if part),
        state=row["state"] if row["state"] in {"ok", "warning", "alarm"} else None,
        href=f"{root}/executions/{quote(schedule['schedule_id'], safe='')}/{quote(row['id'], safe='')}",
    )
