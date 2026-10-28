"""Weekly PDF for management: where the portfolio stands and what changed.

One A4 document built from what LinkCraft already knows: the current snapshot
(score and its explanation per loop), the runs of the last seven days (score
trend) and, when given, the engineering actions (none are kept in LinkCraft yet).
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from linkcraft.catalog.labels import METHOD_LABELS
from linkcraft.engine.zones import zone_of
from linkcraft.i18n import current_language, t

INK = colors.HexColor("#10262d")
MUTED = colors.HexColor("#6b7e85")
LINE = colors.HexColor("#dfe7e9")
TEAL = colors.HexColor("#087e85")
PALE = colors.HexColor("#f3f7f8")
# Labels are English; they go through t() when the report is built.
STATUS = {
    "critical": ("Critical", colors.HexColor("#c23b4b")),
    "high": ("High", colors.HexColor("#c45d1d")),
    "medium": ("Medium", colors.HexColor("#9a6c0c")),
    "normal": ("Low", colors.HexColor("#167a5a")),
    "inactive": ("Inactive", MUTED),
    "no_data": ("No data", MUTED),
    "pending": ("Pending", MUTED),
}
ACTION_STATUS = {"open": "Open", "in_progress": "In progress", "blocked": "Blocked", "done": "Done"}
PRIORITY = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}


def _date_format() -> str:
    return "%Y-%m-%d" if current_language() == "en" else "%d/%m/%Y"


def _day(day: str) -> str:
    """A ``YYYY-MM-DD`` day as a short chart label: "05-31" (en) or "31/05" (pt-BR)."""

    return f"{day[5:7]}-{day[8:10]}" if current_language() == "en" else f"{day[8:10]}/{day[5:7]}"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]

    def make(name: str, **kw: Any) -> ParagraphStyle:
        return ParagraphStyle(
            name, parent=base, **{"fontName": "Helvetica", "textColor": INK, **kw}
        )

    return {
        "eyebrow": make(
            "eyebrow", fontName="Helvetica-Bold", fontSize=8, textColor=TEAL, leading=10
        ),
        "title": make("title", fontName="Helvetica-Bold", fontSize=20, leading=24),
        "subtitle": make("subtitle", fontSize=9.5, textColor=MUTED, leading=13),
        "h2": make(
            "h2",
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            spaceBefore=10,
            spaceAfter=4,
            keepWithNext=1,
        ),
        "body": make("body", fontSize=9, leading=12.5, alignment=TA_LEFT),
        "cell": make("cell", fontSize=8, leading=10.5),
        "cell_bold": make("cell_bold", fontName="Helvetica-Bold", fontSize=8, leading=10.5),
        "small": make("small", fontSize=7.5, textColor=MUTED, leading=10, keepWithNext=1),
        "kpi": make("kpi", fontName="Helvetica-Bold", fontSize=18, leading=21),
        "kpi_label": make("kpi_label", fontSize=7.5, textColor=MUTED, leading=9.5),
    }


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.0f}%"


def local(moment: datetime) -> datetime:
    """An instant on the installation's wall clock: what a report shows a person (owner,
    2026-10-27: every time in the user's time zone; stored times stay UTC)."""

    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(zone_of(None))


def _stamp(value: Any, form: str = "") -> str:
    """An ISO instant from the store as local text ("—" when missing)."""

    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return local(moment).strftime(form or f"{_date_format()} %H:%M")


def _date(value: Any) -> str:
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    # A due day is a day as written; an instant is the day where the plant is.
    return (local(moment) if moment.tzinfo else moment).strftime(_date_format())


def _reason(row: dict[str, Any]) -> str:
    limiting = row.get("limiting")
    if row.get("health") is None:
        return escape(row.get("state_reason") or t("No score in the period."))
    if not limiting:
        return t("No criterion below 100%.")
    label = METHOD_LABELS.get(limiting["method_id"], limiting["method_id"])
    # Paragraph reads markup: everything that comes from data is escaped.
    text = t("{method} at {value}.", method=label, value=_pct(limiting["value"]))
    return escape(f"{text} {limiting.get('finding') or ''}".strip())


def daily_scores(jobs: list[dict[str, Any]], since: datetime) -> list[tuple[str, float]]:
    """Average portfolio score per day: the last score of each loop on each day."""

    last: dict[tuple[str, str], tuple[str, float]] = {}
    for job in jobs:
        summary = job.get("summary") or {}
        health = summary.get("health")
        stamp = str(job.get("source_end") or job.get("completed_at") or "")
        if (
            job.get("status") != "completed"
            or health is None
            or not stamp
            or summary.get("kind") == "data_quality"
        ):
            continue
        day = stamp[:10]
        if day < since.date().isoformat():
            continue
        key = (day, job["loop_id"])
        if key not in last or stamp > last[key][0]:
            last[key] = (stamp, float(health))
    by_day: dict[str, list[float]] = defaultdict(list)
    for (day, _loop), (_stamp, health) in last.items():
        by_day[day].append(health)
    return [(day, sum(values) / len(values)) for day, values in sorted(by_day.items())]


def score_change(jobs: list[dict[str, Any]], since: datetime) -> dict[str, float]:
    """Each loop's score change over the week: current minus the first score in the window."""

    first: dict[str, tuple[str, float]] = {}
    for job in jobs:
        summary = job.get("summary") or {}
        stamp = str(job.get("source_end") or job.get("completed_at") or "")
        if (
            job.get("status") != "completed"
            or summary.get("health") is None
            or stamp[:10] < since.date().isoformat()
        ):
            continue
        if summary.get("kind") == "data_quality":
            continue
        current = first.get(job["loop_id"])
        if current is None or stamp < current[0]:
            first[job["loop_id"]] = (stamp, float(summary["health"]))
    return {loop_id: health for loop_id, (_stamp, health) in first.items()}


def _trend_chart(points: list[tuple[str, float]], width: float) -> Drawing:
    height = 120
    drawing = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 30, 22, width - 40, height - 34
    chart.data = [[round(value, 1) for _, value in points]]
    chart.categoryAxis.categoryNames = [_day(day) for day, _ in points]
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor = MUTED
    chart.categoryAxis.strokeColor = LINE
    chart.valueAxis.valueMin, chart.valueAxis.valueMax, chart.valueAxis.valueStep = 0, 100, 25
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fillColor = MUTED
    chart.valueAxis.strokeColor = LINE
    chart.valueAxis.gridStrokeColor = LINE
    chart.valueAxis.visibleGrid = True
    chart.bars[0].fillColor = TEAL
    chart.bars[0].strokeColor = None
    chart.barLabelFormat = "%.0f"
    chart.barLabels.fontSize = 7
    chart.barLabels.nudge = 6
    for labels in (chart.categoryAxis.labels, chart.valueAxis.labels, chart.barLabels):
        labels.fontName = "Helvetica"
    drawing.add(chart)
    drawing.add(
        String(
            30,
            height - 8,
            t("Average portfolio score per day (0 to 100)"),
            fontName="Helvetica",
            fontSize=7.5,
            fillColor=MUTED,
        )
    )
    return drawing


def weekly_report_pdf(
    *,
    scenario_name: str,
    loops: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    now: datetime | None = None,
    top: int = 10,
) -> bytes:
    now = local(now or datetime.now(UTC))
    since = now - timedelta(days=7)
    style = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=t("PlantCraft Analytics · Weekly portfolio report"),
        author="PlantCraft Analytics",
    )
    width = A4[0] - 32 * mm
    story: list[Any] = []

    scored = [row for row in loops if row.get("health") is not None]
    average = sum(row["health"] for row in scored) / len(scored) if scored else None
    attention = [row for row in loops if row.get("status") in {"critical", "high", "medium"}]
    open_actions = [
        item for item in actions if item.get("status") in {"open", "in_progress", "blocked"}
    ]
    done_week = [
        item
        for item in actions
        if item.get("status") == "done"
        and str(item.get("completed_at") or item.get("updated_at") or "")[:10]
        >= since.date().isoformat()
    ]

    story += [
        Paragraph(t("LINKCRAFT · CONTROL LOOP PERFORMANCE"), style["eyebrow"]),
        Spacer(1, 3),
        Paragraph(t("Weekly portfolio report"), style["title"]),
        Paragraph(
            t(
                "{scenario} · week from {start} to {end} · generated on {generated}",
                scenario=escape(scenario_name),
                start=since.strftime(_date_format()),
                end=now.strftime(_date_format()),
                generated=now.strftime(f"{_date_format()} %H:%M"),
            ),
            style["subtitle"],
        ),
        Spacer(1, 10),
    ]

    def plural(count: int, one: str, many: str) -> str:
        return t(one) if count == 1 else t(many)

    kpis = [
        (str(len(loops)), plural(len(loops), "loop monitored", "loops monitored")),
        (_pct(average), t("average portfolio score")),
        (
            str(len(attention)),
            plural(
                len(attention),
                "needs attention (score up to 75%)",
                "need attention (score up to 75%)",
            ),
        ),
        (str(len(open_actions)), plural(len(open_actions), "open action", "open actions")),
        (
            str(len(done_week)),
            plural(len(done_week), "action done this week", "actions done this week"),
        ),
    ]
    kpi_table = Table(
        [
            [Paragraph(value, style["kpi"]) for value, _ in kpis],
            [Paragraph(label, style["kpi_label"]) for _, label in kpis],
        ],
        colWidths=[width / len(kpis)] * len(kpis),
    )
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("LINEBEFORE", (1, 0), (-1, -1), 0.6, colors.white),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story += [kpi_table, Spacer(1, 6)]

    lead = (
        t("{count} of {total} loops need attention. ", count=len(attention), total=len(loops))
        if len(attention) != 1
        else t("1 of {total} loops needs attention. ", total=len(loops))
    ) + (
        t(
            "Priority number 1 is {loop} ({name}): {reason}",
            loop=escape(attention_first["loop_id"]),
            name=escape(attention_first["name"]),
            reason=_reason(attention_first),
        )
        if (attention_first := max(loops, key=lambda row: row.get("priority") or 0, default=None))
        and (attention_first.get("priority") or 0) > 0
        else t("No loop with a relevant priority.")
    )
    story.append(Paragraph(lead, style["body"]))

    points = daily_scores(jobs, since)
    if len(points) >= 2:
        story += [Spacer(1, 6), _trend_chart(points, width)]

    first_scores = score_change(jobs, since)
    ranked = sorted(
        (row for row in loops if (row.get("priority") or 0) > 0),
        key=lambda row: -(row.get("priority") or 0),
    )[:top]
    rows = [
        [
            Paragraph("#", style["cell_bold"]),
            Paragraph(t("Loop"), style["cell_bold"]),
            Paragraph(t("Score"), style["cell_bold"]),
            Paragraph(t("This week"), style["cell_bold"]),
            Paragraph(t("Why it is here"), style["cell_bold"]),
        ]
    ]
    for index, row in enumerate(ranked, start=1):
        start = first_scores.get(row["loop_id"])
        delta = None if start is None or row.get("health") is None else row["health"] - start
        change = (
            "—"
            if delta is None
            else t("stable")
            if abs(delta) < 0.5
            else t("{delta} pp", delta=f"{delta:+.0f}")
        )
        label, color = STATUS.get(row.get("status"), ("—", MUTED))
        label = t(label)
        rows.append(
            [
                Paragraph(str(index), style["cell"]),
                Paragraph(
                    f"<b>{escape(row['loop_id'])}</b><br/><font color='#6b7e85'>{escape(row['name'])} · {escape(row['area'])}</font>",
                    style["cell"],
                ),
                Paragraph(
                    f"<b>{_pct(row.get('health'))}</b><br/><font color='{color.hexval()[2:].join(['#', ''])}'>{label}</font>",
                    style["cell"],
                ),
                Paragraph(change, style["cell"]),
                Paragraph(_reason(row), style["cell"]),
            ]
        )
    priority_table = Table(
        rows, colWidths=[8 * mm, 42 * mm, 18 * mm, 18 * mm, width - 86 * mm], repeatRows=1
    )
    priority_table.setStyle(_table_style())
    # The heading stays with the table's first rows; the table itself may split across pages.
    story += [
        Paragraph(
            t("The {count} priority loops", count=len(ranked))
            if len(ranked) != 1
            else t("The priority loop"),
            style["h2"],
        ),
        Paragraph(
            t(
                "Priority order: score points lost multiplied by the weight of the loop's criticality."
            ),
            style["small"],
        ),
        Spacer(1, 4),
        priority_table,
    ]

    suspects = [row for row in loops if row.get("alerts")]
    if suspects:
        suspect_rows = [
            [
                Paragraph(t(text), style["cell_bold"])
                for text in ("Loop", "Score", "Sign to confirm in the field")
            ]
        ]
        for row in sorted(suspects, key=lambda item: -(item.get("priority") or 0)):
            alert = row["alerts"][0]
            label = METHOD_LABELS.get(alert["method_id"], alert["method_id"])
            suspect_rows.append(
                [
                    Paragraph(
                        f"<b>{escape(row['loop_id'])}</b><br/><font color='#6b7e85'>{escape(row.get('name') or '')}</font>",
                        style["cell"],
                    ),
                    Paragraph(_pct(row.get("health")), style["cell"]),
                    Paragraph(
                        f"<b>{escape(label)}.</b> {escape(alert['finding'] or '')}", style["cell"]
                    ),
                ]
            )
        suspect_table = Table(
            suspect_rows, colWidths=[44 * mm, 16 * mm, width - 60 * mm], repeatRows=1
        )
        suspect_table.setStyle(_table_style())
        story += [
            Paragraph(t("Diagnoses to confirm ({count})", count=len(suspects)), style["h2"]),
            Paragraph(
                t(
                    "Signs outside the score, such as valve stiction and oscillation: the score may be good and the valve not."
                ),
                style["small"],
            ),
            Spacer(1, 4),
            suspect_table,
        ]

    order = {"blocked": 0, "open": 1, "in_progress": 2}
    open_rows = [
        [
            Paragraph(t(text), style["cell_bold"])
            for text in ("Action", "Loop", "Owner", "Priority", "Due date", "Status")
        ]
    ]
    today = now.date().isoformat()
    late_rows: list[int] = []
    for item in sorted(
        open_actions,
        key=lambda action: (order.get(action["status"], 9), str(action.get("due_at") or "9999")),
    ):
        due = item.get("due_at")
        late = bool(due) and str(due)[:10] < today
        if late:
            late_rows.append(len(open_rows))
        open_rows.append(
            [
                Paragraph(escape(item.get("title") or ""), style["cell"]),
                Paragraph(escape(item.get("loop_id") or "—"), style["cell"]),
                Paragraph(
                    escape(item.get("owner_name") or item.get("owner") or t("No owner")),
                    style["cell"],
                ),
                Paragraph(_label(PRIORITY, item.get("priority")) or "—", style["cell"]),
                Paragraph(
                    t("{date} (late)", date=_date(due)) if late else _date(due), style["cell"]
                ),
                Paragraph(_label(ACTION_STATUS, item.get("status")), style["cell"]),
            ]
        )
    actions_block: list[Any] = [Paragraph(t("Open actions"), style["h2"])]
    if len(open_rows) > 1:
        action_table = Table(
            open_rows,
            colWidths=[width - 120 * mm, 20 * mm, 32 * mm, 20 * mm, 26 * mm, 22 * mm],
            repeatRows=1,
        )
        table_style = _table_style()
        for index in late_rows:
            table_style.add("TEXTCOLOR", (4, index), (4, index), colors.HexColor("#c23b4b"))
        action_table.setStyle(table_style)
        actions_block.append(action_table)
    else:
        actions_block.append(Paragraph(t("No open actions."), style["body"]))
    story += [KeepTogether(actions_block), Spacer(1, 10)]

    story.append(
        Paragraph(
            t(
                "How to read the score: each loop gets 0 to 100, the product of the control performance criteria "
                "(PV–SP error, saturation, attenuation, operating band, sampling). Setpoint changes and time "
                "in manual are operating context and do not count toward the score. No analysis changes the process."
            ),
            style["small"],
        )
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _label(labels: dict[str, str], key: Any) -> str:
    """The translated label of a code, or the code itself when unknown."""

    return t(labels[key]) if key in labels else str(key or "")


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), PALE),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
    )


def _footer(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        16 * mm,
        8 * mm,
        t("PlantCraft Analytics · report generated automatically from the analyses of the loops"),
    )
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, t("Page {page}", page=document.page))
    canvas.restoreState()
