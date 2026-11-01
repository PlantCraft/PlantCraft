"""Help as the suite's help browser reads it: guides and method pages, each one Markdown.

``GET /api/help/docs`` lists ``{id, title, category}``; a category ``A/B`` is a folder in the
browser. ``GET /api/help/docs/<id>`` returns the page's Markdown:

- ``guides/<name>``: the guides in ``methods/help/guides/<name>.md`` (one per page of the app).
  ``guides/loop-types`` is written by the API from the loop-type defaults.
- ``methods/<id>``: a method's page. Loop methods come from ``methods/help/<id>.md`` (parsed by
  ``catalog.help``); Data quality checks from the check's own metadata (``catalog.signal_checks``).
  Both show this site's configured defaults next to the method's own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plantcraft_sdk.i18n import localized

from linkcraft.catalog import signal_checks
from linkcraft.catalog.help import HELP_DIR, format_default, method_help
from linkcraft.catalog.registry import GROUPS, METHOD_GROUP, METHOD_SPECS
from linkcraft.i18n import t

GUIDES_DIR = HELP_DIR / "guides"
# Guides in reading order, with the folder each one sits in.
GUIDES: tuple[tuple[str, str], ...] = (
    ("overview", "Guides"),
    ("results", "Guides"),
    ("signals", "Guides/Signals"),
    ("signal", "Guides/Signals"),
    ("asset", "Guides"),
    ("signal-quality", "Guides/Signals"),
    ("loops", "Guides/Loops"),
    ("loop-types", "Guides/Loops"),
    ("runs", "Guides"),
    ("algorithms", "Guides"),
    ("blocks", "Guides"),
)
LOOP_TYPES_TITLE = "Analysis defaults per loop type"


def _title(path: Path) -> str:
    for line in localized(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _reference(item: dict[str, Any]) -> str:
    authors = item.get("authors") or []
    text = ", ".join(authors) if isinstance(authors, list) else str(authors)
    text += f" ({item['year']}). " if item.get("year") else ". "
    text += f"*{item.get('title') or ''}*"
    if item.get("venue"):
        text += f". {item['venue']}"
    text += "."
    if item.get("doi"):
        text += f" [doi:{item['doi']}](https://doi.org/{item['doi']})"
    elif item.get("url"):
        text += f" [{item['url']}]({item['url']})"
    return text


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def docs() -> list[dict[str, str]]:
    """Every help page: guides first, then the methods by group."""

    found = []
    for name, category in GUIDES:
        path = GUIDES_DIR / f"{name}.md"
        title = t(LOOP_TYPES_TITLE) if name == "loop-types" else _title(path)
        found.append({"id": f"guides/{name}", "title": title, "category": t(category)})
    data_quality = f"{t('Methods')}/{t(signal_checks.GROUP['name'])}"
    for check_id, block in signal_checks.CHECKS.items():
        found.append(
            {
                "id": f"methods/{check_id}",
                "title": t(block.metadata.name),
                "category": data_quality,
            }
        )
    for group_id, group in GROUPS.items():
        for method_id in METHOD_SPECS:
            if METHOD_GROUP.get(method_id) != group_id:
                continue
            page = method_help(method_id)
            if page is None:
                continue
            found.append(
                {
                    "id": f"methods/{method_id}",
                    "title": page["label"],
                    "category": f"{t('Methods')}/{t(group['name'])}",
                }
            )
    return found


def guide(name: str) -> str | None:
    if not any(name == known for known, _ in GUIDES) or name == "loop-types":
        return None
    return localized(GUIDES_DIR / f"{name}.md").read_text(encoding="utf-8")


def loop_method_markdown(method_id: str, configured: dict[str, Any] | None = None) -> str | None:
    page = method_help(method_id, configured)
    if page is None:
        return None
    lines = [f"# {page['title']}", "", f"`{method_id}`", ""]
    for section in page["sections"]:
        lines += [f"## {t(section['title'])}", ""]
        for block in section["blocks"]:
            if block["type"] == "ul":
                lines += [f"- {item}" for item in block.get("items", [])]
            else:
                lines.append(block.get("text", ""))
            lines.append("")
        if section["id"] == "reference" and page["references"]:
            lines += [f"### {t('Full references')}", ""]
            lines += [f"- {_reference(item)}" for item in page["references"]]
            lines.append("")
        if section["id"] == "reference":
            lines += _parameter_table(
                [
                    (item["key"], item["default"], item["configured"], item["meaning"])
                    for item in page["parameters"]
                ]
            )
    if page.get("formula"):
        lines += [f"## {t('Formula as implemented')}", "", f"`{page['formula']}`", ""]
    return "\n".join(lines).rstrip() + "\n"


def _parameter_table(rows: list[tuple[str, str, str | None, str]]) -> list[str]:
    lines = [f"## {t('Parameters')}", ""]
    if not rows:
        return lines + [t("This method has no parameters."), ""]
    lines += [
        f"| {t('Parameter')} | {t('Default')} | {t('This site')} | {t('Meaning')} |",
        "|---|---|---|---|",
    ]
    for key, default, configured, meaning in rows:
        lines.append(
            f"| `{key}` | {_cell(default)} | {_cell(configured or '')} | {_cell(meaning)} |"
        )
    return lines + [
        "",
        t("An algorithm, a signal or a loop can override a default; the method's page sets it."),
        "",
    ]


def check_markdown(check_id: str, configured: dict[str, Any] | None = None) -> str | None:
    if signal_checks.check(check_id) is None:
        return None
    info = signal_checks.describe(check_id, configured)
    lines = [f"# {info['name']}", "", f"`{check_id}`", "", info["description"], ""]
    if info.get("formula"):
        lines += [f"## {t('How it judges')}", "", info["formula"], ""]
    lines += _parameter_table(
        [
            (
                item["name"],
                format_default(item["default"]),
                format_default(item["value"]) if item["value"] != item["default"] else None,
                item.get("help") or "",
            )
            for item in info["parameters"]
        ]
    )
    for title, key in (("Assumptions", "assumptions"), ("Limitations", "limitations")):
        if info.get(key):
            lines += [f"## {t(title)}", ""] + [f"- {item}" for item in info[key]] + [""]
    if info.get("action"):
        lines += [f"## {t('What to do')}", "", info["action"], ""]
    if not info.get("text_signals"):
        lines += [t("Text signals are not checked by it."), ""]
    if info.get("references"):
        lines += [f"## {t('References')}", ""]
        lines += [f"- {_reference(item)}" for item in info["references"]] + [""]
    return "\n".join(lines).rstrip() + "\n"


def loop_types_markdown(rows: list[dict[str, Any]]) -> str:
    """The loop-type defaults table (rows of ``GET /api/help/loop-types``) as a guide."""

    lines = [
        f"# {t(LOOP_TYPES_TITLE)}",
        "",
        t(
            "The algorithm and parameters each loop type of the asset record starts a loop with. "
            "A setting changed on the loop page wins over these."
        ),
        "",
        f"| {t('Loop type')} | {t('Starting algorithm')} | {t('Parameters from the loop type')} "
        f"| {t('Why')} |",
        "|---|---|---|---|",
    ]
    for row in rows:
        parameters = "; ".join(
            f"**{item['method']}**: "
            + ", ".join(f"`{key} = {value}`" for key, value in item["values"].items())
            for item in row["parameters"]
        )
        lines.append(
            f"| `{row['loop_type']}` | {_cell(row['profile_name'])} | "
            f"{_cell(parameters or t('method defaults'))} | {_cell(row['why'])} |"
            if row["loop_type"]
            else f"| {t('missing or unknown')} | {_cell(row['profile_name'])} | "
            f"{_cell(parameters or t('method defaults'))} | {_cell(row['why'])} |"
        )
    return "\n".join(lines) + "\n"
