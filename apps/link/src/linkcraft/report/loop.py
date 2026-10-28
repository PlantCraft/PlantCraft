"""Per-loop diagnosis PDF: one loop's score, what limits it, its trends, its likely causes and
every finding.

Built from the loop's latest analysis (summary and method results) and the
samples of that window. Every number and sentence comes from the methods
(``describe(metrics)`` wording); the likely causes are a fixed rule table over those findings
(``report.causes``).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from linkcraft.catalog.labels import METHOD_LABELS
from linkcraft.i18n import t
from linkcraft.report.causes import likely_causes
from linkcraft.report.weekly import (
    MUTED,
    PALE,
    STATUS,
    TEAL,
    _date_format,
    _pct,
    _stamp,
    _styles,
    _table_style,
    local,
)

SERIES = {"pv": colors.HexColor("#1762b6"), "sp": colors.HexColor("#e06d00")}
OUTPUT = colors.HexColor("#00958f")
RESULT_STATUS = {
    "ok": "OK",
    "warning": "Warning",
    "bad": "Bad",
    "insufficient_data": "Insufficient data",
    "not_applicable": "Not applicable",
}
OPERATING_STATE = {
    "active": "In operation",
    "manual": "Manual",
    "possibly_inactive": "Possibly inactive",
    "insufficient_samples": "Not enough samples",
    "unusable_data": "Data not usable",
}
MAX_POINTS = 600


def _performance(result: dict[str, Any]) -> float | None:
    component = (result.get("metrics") or {}).get("performance_component")
    if isinstance(component, (int, float)):
        return float(component)
    score = result.get("score")
    return None if score is None else max(0.0, 100.0 - float(score))


def _thin(frame: pd.DataFrame, limit: int = MAX_POINTS) -> pd.DataFrame:
    if len(frame) <= limit:
        return frame
    step = int(np.ceil(len(frame) / limit))
    return frame.iloc[::step]


def _points(frame: pd.DataFrame, column: str, origin: pd.Timestamp) -> list[tuple[float, float]]:
    if column not in frame:
        return []
    values = pd.to_numeric(frame[column], errors="coerce")
    times = pd.to_datetime(frame["timestamp"], errors="coerce")
    hours = (times - origin).dt.total_seconds() / 3600.0
    return [
        (float(h), float(v))
        for h, v in zip(hours, values, strict=False)
        if np.isfinite(h) and np.isfinite(v)
    ]


def _chart(
    frame: pd.DataFrame, columns: dict[str, colors.Color], title: str, width: float
) -> Drawing | None:
    if frame.empty or "timestamp" not in frame:
        return None
    thin = _thin(frame)
    times = pd.to_datetime(thin["timestamp"], errors="coerce").dropna()
    if times.empty:
        return None
    origin = times.min()
    data, used = [], []
    for column, color in columns.items():
        points = _points(thin, column, origin)
        if len(points) >= 2:
            data.append(points)
            used.append((column, color))
    if not data:
        return None
    height = 130
    drawing = Drawing(width, height)
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 34, 24, width - 110, height - 40
    plot.data = data
    for index, (_column, color) in enumerate(used):
        plot.lines[index].strokeColor = color
        plot.lines[index].strokeWidth = 0.9
    plot.xValueAxis.labels.fontSize = 7
    plot.xValueAxis.labels.fillColor = MUTED
    plot.xValueAxis.labelTextFormat = "%.0f h"
    plot.yValueAxis.labels.fontSize = 7
    plot.yValueAxis.labels.fillColor = MUTED
    drawing.add(plot)
    legend = Legend()
    legend.x, legend.y = width - 66, height - 30
    legend.fontName, legend.fontSize = "Helvetica", 7
    legend.colorNamePairs = [(color, column.upper()) for column, color in used]
    drawing.add(legend)
    drawing.add(String(34, height - 10, title, fontName="Helvetica", fontSize=7.5, fillColor=MUTED))
    return drawing


def loop_report_pdf(
    *,
    loop: dict[str, Any],
    summary: dict[str, Any] | None,
    results: list[dict[str, Any]],
    frame: pd.DataFrame,
    source_start: str | None,
    source_end: str | None,
    now: datetime | None = None,
) -> bytes:
    """The A4 diagnosis report of one loop."""

    now = local(now or datetime.now(UTC))
    summary = summary or {}
    style = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=t("PlantCraft Analytics · Loop report {loop}", loop=loop.get("loop_id", "")),
        author="PlantCraft Analytics",
    )
    width = A4[0] - 32 * mm
    story: list[Any] = [
        Paragraph(t("LINKCRAFT · CONTROL LOOP DIAGNOSIS"), style["eyebrow"]),
        Spacer(1, 3),
        Paragraph(
            f"{escape(str(loop.get('loop_id', '')))} · {escape(str(loop.get('name', '')))}",
            style["title"],
        ),
        Paragraph(
            t(
                "{area} · analysed window {start} to {end} · generated on {generated}",
                area=escape(str(loop.get("area") or "")),
                start=escape(_stamp(source_start)),
                end=escape(_stamp(source_end)),
                generated=now.strftime(f"{_date_format()} %H:%M"),
            ),
            style["subtitle"],
        ),
        Spacer(1, 10),
    ]

    label, color = STATUS.get(summary.get("status"), ("Pending", MUTED))
    quality = summary.get("data_quality") or {}
    kpis = [
        (_pct(summary.get("health")), t("loop score (0 to 100)")),
        (t(label), t("status")),
        (
            t(OPERATING_STATE.get(summary.get("operating_state") or "", "—")),
            t("operating state"),
        ),
        (t("usable") if quality.get("apt", True) else t("not usable"), t("data quality")),
        (_pct((summary.get("valid_fraction") or 0) * 100), t("valid PV samples")),
    ]
    kpi_table = Table(
        [
            [Paragraph(value, style["kpi"]) for value, _ in kpis],
            [Paragraph(text, style["kpi_label"]) for _, text in kpis],
        ],
        colWidths=[width / len(kpis)] * len(kpis),
    )
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("TEXTCOLOR", (1, 0), (1, 0), color),
                ("LINEBEFORE", (1, 0), (-1, -1), 0.6, colors.white),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story += [kpi_table, Spacer(1, 8)]

    if not summary:
        story.append(Paragraph(t("This loop has not been analysed yet."), style["body"]))
    else:
        limiting = summary.get("limiting")
        if summary.get("health") is None:
            lead = summary.get("operating_state_reason") or t("No score in the period.")
        elif limiting:
            lead = t(
                "The score is limited by {method} at {value}. {finding}",
                method=METHOD_LABELS.get(limiting["method_id"], limiting["method_id"]),
                value=_pct(limiting.get("value")),
                finding=limiting.get("finding") or "",
            )
        else:
            lead = t("No criterion below 100%.")
        story.append(Paragraph(escape(lead), style["body"]))
        for reason in quality.get("reasons") or []:
            story.append(Paragraph(escape(str(reason)), style["small"]))

    trend = _chart(frame, SERIES, t("PV and SP over the analysed window"), width)
    output = _chart(frame, {"op": OUTPUT}, t("Controller output (OP) over the window"), width)
    if trend or output:
        story += [Paragraph(t("Trends"), style["h2"])]
        story += [item for item in (trend, Spacer(1, 4), output) if item is not None]

    alerts = summary.get("alerts") or []
    if alerts:
        rows = [[Paragraph(t(text), style["cell_bold"]) for text in ("Sign", "Finding")]]
        for alert in alerts:
            rows.append(
                [
                    Paragraph(
                        escape(METHOD_LABELS.get(alert["method_id"], alert["method_id"])),
                        style["cell_bold"],
                    ),
                    Paragraph(escape(alert.get("finding") or ""), style["cell"]),
                ]
            )
        table = Table(rows, colWidths=[44 * mm, width - 44 * mm], repeatRows=1)
        table.setStyle(_table())
        story += [
            Paragraph(t("Diagnoses to confirm in the field"), style["h2"]),
            Paragraph(
                t("Signs outside the score, such as valve stiction and oscillation."),
                style["small"],
            ),
            Spacer(1, 4),
            table,
        ]

    causes = likely_causes(results)
    if causes:
        rows = [
            [
                Paragraph(t(text), style["cell_bold"])
                for text in ("Likely cause", "Why", "First step")
            ]
        ]
        for cause in causes:
            why = "<br/>".join(
                escape(
                    f"{METHOD_LABELS.get(item['method_id'], item['method_id'])}: {item['finding']}"
                )
                for item in cause["evidence"]
            )
            rows.append(
                [
                    Paragraph(escape(cause["cause"]), style["cell_bold"]),
                    Paragraph(why, style["cell"]),
                    Paragraph(escape(cause["action"]), style["cell"]),
                ]
            )
        table = Table(
            rows, colWidths=[34 * mm, (width - 34 * mm) / 2, (width - 34 * mm) / 2], repeatRows=1
        )
        table.setStyle(_table())
        story += [
            Paragraph(t("Likely causes and what to do first"), style["h2"]),
            Paragraph(
                t(
                    "Ranked by how many findings point to each cause and how strongly; confirm "
                    "in the field before acting."
                ),
                style["small"],
            ),
            Spacer(1, 4),
            table,
        ]

    rows = [
        [
            Paragraph(t(text), style["cell_bold"])
            for text in ("Method", "Result", "Performance", "Finding")
        ]
    ]
    for result in results:
        method_id = str(result.get("method_id"))
        rows.append(
            [
                Paragraph(escape(METHOD_LABELS.get(method_id, method_id)), style["cell_bold"]),
                Paragraph(
                    escape(t(RESULT_STATUS.get(result.get("status"), str(result.get("status"))))),
                    style["cell"],
                ),
                Paragraph(_pct(_performance(result)), style["cell"]),
                Paragraph(
                    escape(str(result.get("finding") or result.get("message") or "")),
                    style["cell"],
                ),
            ]
        )
    method_table = Table(rows, colWidths=[38 * mm, 24 * mm, 22 * mm, width - 84 * mm], repeatRows=1)
    method_table.setStyle(_table())
    story += [Paragraph(t("Every method run"), style["h2"]), Spacer(1, 2), method_table]

    signals = loop.get("signals") or {}
    signal_text = ", ".join(
        f"{role.upper()} = {escape(str(value))}" for role, value in signals.items() if value
    )
    story += [
        Spacer(1, 10),
        Paragraph(
            t(
                "Signals (PlantCraft ids): {signals}. Algorithm: {algorithm}.",
                signals=signal_text or "—",
                algorithm=escape(str(loop.get("profile_id") or "loop_health")),
            ),
            style["small"],
        ),
        Paragraph(
            t(
                "How to read the score: 0 to 100, the product of the control performance criteria. "
                "Data quality runs first; when it rejects the data, no criterion is judged. "
                "Setpoint changes and time in manual are context and do not count toward the score. "
                "No analysis changes the process."
            ),
            style["small"],
        ),
    ]
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _table() -> TableStyle:
    table = _table_style()
    table.add("LINEABOVE", (0, 0), (-1, 0), 0.8, TEAL)
    return table


def _footer(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        16 * mm, 8 * mm, t("PlantCraft Analytics · loop diagnosis generated from its analyses")
    )
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, t("Page {page}", page=document.page))
    canvas.restoreState()
