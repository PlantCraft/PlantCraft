"""A report as a Markdown file: the text cells as they were written, every card as the values it
read (a table of each line's lowest, mean, highest and last value for a chart), events as a table.
It pastes into a wiki, a notebook or a merge request and reads the same as plain text.
"""

from __future__ import annotations

from dashcraft.i18n import t
from dashcraft.reports.document import CardPart, Document, Part, Table

MEDIA_TYPE = "text/markdown; charset=utf-8"


def _cell(value: object) -> str:
    text = "".join(span.text for span in value) if isinstance(value, list) else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _table(table: Table) -> list[str]:
    if not table.head:
        return []
    marks = {"right": "---:", "center": ":---:"}
    align = [marks.get(a, "---") for a in (table.align + ["left"] * len(table.head))]
    lines = [
        "| " + " | ".join(_cell(head) for head in table.head) + " |",
        "| " + " | ".join(align[: len(table.head)]) + " |",
    ]
    lines.extend("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in table.rows)
    return [*lines, ""]


def _card(part: CardPart) -> list[str]:
    out: list[str] = []
    if part.title:
        out.extend([f"**{part.title}**", ""])
    if part.description:
        out.extend([f"*{part.description}*", ""])
    if part.show == "empty":
        out.extend([f"> {part.empty}", ""])
    elif part.show in ("chart", "scatter") and part.legend is not None:
        out.extend(_table(part.legend))
    elif part.show == "scatter":
        out.extend(
            _table(
                Table(
                    head=[t("Signal"), t("Min"), t("Mean"), t("Max"), t("Last")],
                    rows=[
                        [s.label, s.stats["min"], s.stats["mean"], s.stats["max"], s.stats["last"]]
                        for s in part.series
                    ],  # fmt: skip
                    align=["left", "right", "right", "right", "right"],
                )
            )
        )
    elif part.show == "tiles":
        out.extend(
            _table(
                Table(
                    head=[t("Signal"), t("Value"), t("State")],
                    rows=[
                        [tile.label, f"{tile.value} {tile.unit}".strip(), tile.detail]
                        for tile in part.tiles
                    ],
                    align=["left", "right", "left"],
                )
            )
        )
    elif part.show == "bars":
        out.extend(
            _table(
                Table(
                    head=[t("Signal"), t("Value")],
                    rows=[[bar.label, bar.text] for bar in part.bars],
                    align=["left", "right"],
                )
            )
        )
    elif part.show == "table" and part.table is not None:
        out.extend(_table(part.table))
    out.extend(f"*{note}*\n" for note in part.notes)
    out.extend(f"> {problem}\n" for problem in part.problems)
    return out


def _events(part: Part) -> list[str]:
    out = [f"**{part.title}**", ""]
    if part.error:
        return [*out, f"> {part.error}", ""]
    if part.counts:
        out.extend([part.counts, ""])
    if part.empty:
        out.extend([f"> {part.empty}", ""])
    elif part.table is not None:
        out.extend(_table(part.table))
    if part.note:
        out.extend([f"*{part.note}*", ""])
    return out


def render(document: Document, texts: list[str]) -> str:
    """The Markdown of ``document``; ``texts`` are the text cells' own Markdown, in order (written
    back as they were, not re-made from their blocks)."""

    lines = [f"# {document.name}", ""]
    if document.description:
        lines.extend([document.description, ""])
    lines.extend(f"- **{label}:** {value}" for label, value in document.meta if value)
    lines.append("")
    if document.problems:
        lines.extend([f"> {document.problems}", ""])
    pending = list(texts)
    for part in document.parts:
        if part.kind == "text":
            text = pending.pop(0) if pending else ""
            # The report's title is the file's only "#": the cells' headings go one level down.
            shifted = [f"#{line}" if line.startswith("#") else line for line in text.splitlines()]
            lines.extend([*shifted, ""])
        elif part.kind == "card" and part.card is not None:
            lines.extend(_card(part.card))
        elif part.kind == "events":
            lines.extend(_events(part))
        elif part.kind == "break":
            lines.extend(["---", ""])
    lines.append(f"*{t('Made by PlantCraft View on {made}.', made=document.made)}*")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["MEDIA_TYPE", "render"]
