"""A PDF of the results a filter keeps: the weekly report of 0.3, for any algorithm.

What the Results page shows, on paper: which filter made it, how many results in each status,
each algorithm's count, and every result worst first (asset, type, algorithm and version, status,
measure, finding, when). A filter on the tag "control loop" gives the loop portfolio report; any
other filter gives the report of what it keeps.
"""

from __future__ import annotations

import io
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from linkcraft.i18n import t
from linkcraft.report.weekly import MUTED, _date, _date_format, _styles, _table_style, local

# The suite's statuses, worst first, with the colour each one is printed in.
STATUS = {
    "alarm": ("Alarm", colors.HexColor("#c23b4b")),
    "warning": ("Warning", colors.HexColor("#9a6c0c")),
    "unknown": ("Unknown", MUTED),
    "ok": ("OK", colors.HexColor("#167a5a")),
}
FILTER_NAMES = {
    "status": "Status",
    "algorithm": "Algorithm",
    "tag": "Tag",
    "asset_type": "Asset type",
    "group": "Group",
    "q": "Search",
}
# Rows printed in the table; the counts above it cover every result the filter keeps.
MAX_ROWS = 500


def _measure(measure: dict[str, Any]) -> str:
    value = measure.get("value")
    if value is None:
        return "—"
    if measure.get("format") == "percent":
        return f"{float(value):.0f}%"
    return f"{float(value):.0f}" if float(value) > 1 else f"{float(value):.2f}"


def _filters(filters: dict[str, Any]) -> str:
    parts = []
    for key, label in FILTER_NAMES.items():
        value = filters.get(key)
        if not value:
            continue
        if key == "status":
            value = [t(STATUS[item][0]) for item in value if item in STATUS]
        text = value if isinstance(value, str) else ", ".join(str(item) for item in value)
        parts.append(f"{t(label)}: {escape(text)}")
    return " · ".join(parts) or t("Every result")


def results_report_pdf(
    rows: list[dict[str, Any]], *, filters: dict[str, Any], now: datetime | None = None
) -> tuple[bytes, str]:
    """The PDF and the day it was made (for the file name)."""

    now = local(now or datetime.now(UTC))
    style = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=t("PlantCraft Analytics · Results report"),
        author="PlantCraft Analytics",
    )
    width = A4[0] - 28 * mm
    by_status = Counter(row["status"] for row in rows)
    by_algorithm = Counter(
        (row["algorithm"].get("name") or row["algorithm"].get("id") or "—") for row in rows
    )
    story: list[Any] = [
        Paragraph(t("PLANTCRAFT LINK · RESULTS"), style["eyebrow"]),
        Spacer(1, 3),
        Paragraph(t("Results report"), style["title"]),
        Paragraph(
            t(
                "{filters} · generated on {generated}",
                filters=_filters(filters),
                generated=now.strftime(f"{_date_format()} %H:%M"),
            ),
            style["subtitle"],
        ),
        Spacer(1, 10),
    ]
    kpis = [
        [Paragraph(str(len(rows)), style["kpi"])],
        [Paragraph(t("Results"), style["kpi_label"])],
    ]
    cells = [kpis]
    for key, (label, colour) in STATUS.items():
        cells.append(
            [
                [
                    Paragraph(
                        f'<font color="{colour.hexval()}">{by_status.get(key, 0)}</font>',
                        style["kpi"],
                    )
                ],
                [Paragraph(t(label), style["kpi_label"])],
            ]
        )
    story += [
        Table([cells], colWidths=[width / len(cells)] * len(cells)),
        Spacer(1, 8),
        Paragraph(t("By algorithm"), style["h2"]),
    ]
    algorithm_rows = [
        [Paragraph(t("Algorithm"), style["cell_bold"]), Paragraph(t("Results"), style["cell_bold"])]
    ]
    algorithm_rows += [
        [Paragraph(escape(name), style["cell"]), Paragraph(str(count), style["cell"])]
        for name, count in sorted(by_algorithm.items(), key=lambda item: (-item[1], item[0]))
    ]
    story += [
        Table(
            algorithm_rows, colWidths=[width * 0.8, width * 0.2], style=_table_style(), repeatRows=1
        ),
        Paragraph(t("Results, worst first"), style["h2"]),
    ]
    if not rows:
        story.append(Paragraph(t("No result matches this filter."), style["body"]))
    else:
        header = [
            t("Status"),
            t("Asset"),
            t("Type"),
            t("Algorithm"),
            t("Result"),
            t("Finding"),
            t("When"),
        ]
        table = [[Paragraph(text, style["cell_bold"]) for text in header]]
        for row in rows[:MAX_ROWS]:
            label, colour = STATUS.get(row["status"], STATUS["unknown"])
            algorithm = row["algorithm"]
            version = algorithm.get("version")
            table.append(
                [
                    Paragraph(
                        f'<font color="{colour.hexval()}"><b>{t(label)}</b></font>', style["cell"]
                    ),
                    Paragraph(
                        f"<b>{escape(str(row['name']))}</b><br/>{escape(str(row.get('caption') or ''))}",
                        style["cell"],
                    ),
                    Paragraph(escape(str(row.get("asset_type_label") or "")), style["cell"]),
                    Paragraph(
                        escape(str(algorithm.get("name") or algorithm.get("id") or ""))
                        + (f" · v{version}" if version else ""),
                        style["cell"],
                    ),
                    Paragraph(
                        f"{escape(str(row['measure'].get('label') or ''))} {_measure(row['measure'])}",
                        style["cell"],
                    ),
                    Paragraph(escape(str(row.get("finding") or "—"))[:400], style["cell"]),
                    Paragraph(_date(row.get("at")), style["cell"]),
                ]
            )
        story.append(
            Table(
                table,
                colWidths=[w * width for w in (0.09, 0.19, 0.1, 0.16, 0.11, 0.25, 0.1)],
                style=_table_style(),
                repeatRows=1,
            )
        )
        if len(rows) > MAX_ROWS:
            story.append(
                Paragraph(
                    t(
                        "And {count} more: narrow the filter to print them.",
                        count=len(rows) - MAX_ROWS,
                    ),
                    style["small"],
                )
            )

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(14 * mm, 8 * mm, t("PlantCraft Analytics · results of the algorithms"))
        canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, t("Page {page}", page=doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue(), now.strftime("%Y-%m-%d")
