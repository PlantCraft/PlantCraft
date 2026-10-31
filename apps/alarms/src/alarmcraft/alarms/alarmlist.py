"""A DCS alarm list (the master alarm database exported as CSV or Excel) read as a draft: each
row one alarm on one signal (tag, alarm type, limit, priority, deadband, on-delay, cause,
consequence, action), compared with the rules an earlier import made.

``read`` turns the file into rows and problems (never raises on a bad file: every problem has its
line); ``compare`` gives what an apply would do: new rules, changed ones (field by field),
removed ones (turned off, never deleted) and the ones that stay as they are. Nothing is written
here: ``AlarmListStore`` keeps the draft until a person who edits rules reviews and applies it.

An imported rule carries ``external_id`` = ``<tag>/<type>`` (``FIC-1001.PV/HI``), the alarm's
identity in the DCS, so the next export of the same list is matched alarm by alarm.
"""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any
from xml.etree import ElementTree

from plantcraft_sdk.server.store import Store

from alarmcraft.i18n import t

MAX_BYTES = 5 * 2**20
MAX_ROWS = 20000
# An .xlsx is a zip: what one part may unpack to (a sheet of 20 000 rows is a few MB).
MAX_PART = 50 * 2**20

KINDS = {
    "high_high": ("hh", "hihi", "pvhh", "pvhihi", "highhigh", "ahh", "h2", "hhi", "veryhigh"),
    "high": ("h", "hi", "pvhi", "high", "ah", "h1", "pvh"),
    "low": ("l", "lo", "pvlo", "low", "al", "l1", "pvl"),
    "low_low": ("ll", "lolo", "pvll", "pvlolo", "lowlow", "all", "l2", "llo", "verylow"),
}
KIND_OF = {
    alias: kind for kind, aliases in KINDS.items() for alias in (kind.replace("_", ""), *aliases)
}
KIND_LABEL = {"high_high": "HH", "high": "HI", "low": "LO", "low_low": "LL"}
# DCS priorities: words, or 1 (the most urgent) to 4.
PRIORITY_OF = {
    "critical": "critical", "emergency": "critical", "urgent": "critical", "1": "critical",
    "high": "high", "2": "high",
    "medium": "medium", "med": "medium", "normal": "medium", "3": "medium",
    "low": "low", "4": "low", "journal": "low",
}  # fmt: skip
OFF = {"off", "no", "false", "0", "disabled", "inhibited", "suppressed", "outofservice", "oos"}
# Column names as DCS exports write them (lower case, without spaces, dots, dashes or _).
COLUMNS = {
    "tag": ("tag", "tagname", "signal", "signalid", "point", "pointname", "item", "block", "module"),
    "kind": ("type", "alarmtype", "alarm", "condition", "kind", "attribute", "parameter"),
    "limit": ("limit", "alarmlimit", "setpoint", "alarmsetpoint", "trip", "trippoint", "value", "sp"),
    "unit": ("unit", "units", "eu", "engunits", "engineeringunits", "engineeringunit"),
    "deadband": ("deadband", "hysteresis", "db"),
    "delay": ("ondelay", "ondelays", "ondelayseconds", "delay", "delays", "delayseconds", "debounce"),
    "priority": ("priority", "prio", "severity", "alarmpriority"),
    "name": ("name", "alarmname", "description", "desc", "message", "alarmtext", "text"),
    "cause": ("cause", "causes", "probablecause"),
    "consequence": ("consequence", "consequences", "consequenceofinaction"),
    "action": ("action", "actions", "response", "operatoraction", "correctiveaction"),
    "enabled": ("enabled", "state", "status", "inservice", "active"),
}  # fmt: skip
COLUMN_OF = {alias: key for key, aliases in COLUMNS.items() for alias in aliases}
# What a change compares, in the order the review shows it.
FIELDS = ("name", "signal_id", "kind", "limit", "unit", "deadband", "on_delay_seconds",
          "priority", "enabled", "cause", "consequence", "action")  # fmt: skip
TEMPLATE = (
    "tag,type,limit,unit,priority,deadband,on_delay,description,cause,consequence,action\n"
    "FIC-1001.PV,HI,55,m3/h,high,0.5,10,Feed flow high,Feed valve stuck open,"
    "Column flooding,Close FV-1001 by hand\n"
)


@dataclass
class Row:
    line: int
    tag: str
    signal_id: str
    kind: str
    limit: float
    name: str
    unit: str = ""
    deadband: float = 0.0
    on_delay_seconds: float = 0.0
    priority: str = "medium"
    enabled: bool = True
    cause: str = ""
    consequence: str = ""
    action: str = ""

    @property
    def external_id(self) -> str:
        return f"{self.tag}/{KIND_LABEL[self.kind]}"

    def fields(self) -> dict[str, Any]:
        found = asdict(self)
        found.pop("line")
        found.pop("tag")
        return found


@dataclass
class Read:
    rows: list[Row] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)
    format: str = ""

    def problem(self, line: int, message: str) -> None:
        self.problems.append({"line": line, "message": message})


def _key(text: Any) -> str:
    return re.sub(r"[\s._\-/()]+", "", str(text or "").strip().lower())


def _text(value: Any, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(value if value is not None else ""))
    return text.strip()[:limit]


def _number(value: Any, decimal_comma: bool) -> float | None:
    text = str(value if value is not None else "").strip().replace(" ", "")
    if not text:
        return None
    if decimal_comma:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _seconds(value: Any, decimal_comma: bool) -> float | None:
    """A delay: 10, 10 s, 2 min, 00:00:10."""

    text = str(value if value is not None else "").strip().lower()
    if not text:
        return 0.0
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text):
        parts = [int(part) for part in text.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    match = re.fullmatch(r"([0-9.,]+)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hours?)?", text)
    if not match:
        return None
    number = _number(match.group(1), decimal_comma)
    if number is None:
        return None
    unit = (match.group(2) or "s")[0]
    return number * {"s": 1, "m": 60, "h": 3600}[unit]


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")


def _csv_cells(content: bytes) -> tuple[list[list[str]], bool]:
    text = _decode(content)
    sample = text[:4096]
    delimiter = max((";", ",", "\t", "|"), key=lambda sep: sample.split("\n", 1)[0].count(sep))
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    return rows, delimiter == ";"


_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _part(book: zipfile.ZipFile, name: str) -> bytes:
    info = book.getinfo(name)
    if info.file_size > MAX_PART:
        raise ValueError(
            t("A part of the workbook is larger than {size} MB.", size=MAX_PART // 2**20)
        )
    return book.read(name)


def _column(ref: str) -> int:
    number = 0
    for char in re.match(r"[A-Z]+", ref).group(0):  # type: ignore[union-attr]
        number = number * 26 + ord(char) - 64
    return number - 1


def _xlsx_cells(content: bytes) -> list[list[str]]:
    """The first sheet of an .xlsx as text cells, with the standard library only (shared
    strings, inline strings, numbers, booleans; formulas as their last value)."""

    book = zipfile.ZipFile(io.BytesIO(content))
    names = set(book.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for item in ElementTree.fromstring(_part(book, "xl/sharedStrings.xml")).iter(f"{_NS}si"):
            shared.append("".join(node.text or "" for node in item.iter(f"{_NS}t")))
    sheets = sorted(name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
    if not sheets:
        raise ValueError(t("The workbook has no sheet."))
    first = "xl/worksheets/sheet1.xml" if "xl/worksheets/sheet1.xml" in names else sheets[0]
    rows: list[list[str]] = []
    for row in ElementTree.fromstring(_part(book, first)).iter(f"{_NS}row"):
        cells: list[str] = []
        for cell in row.iter(f"{_NS}c"):
            index = _column(cell.get("r") or "A") if cell.get("r") else len(cells)
            kind = cell.get("t") or "n"
            value_node = cell.find(f"{_NS}v")
            raw = value_node.text if value_node is not None and value_node.text else ""
            if kind == "s":
                value = shared[int(raw)] if raw.isdigit() and int(raw) < len(shared) else ""
            elif kind == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter(f"{_NS}t"))
            elif kind == "b":
                value = "true" if raw == "1" else "false"
            else:
                value = raw
            while len(cells) < index:
                cells.append("")
            cells.append(value)
        rows.append(cells)
        if len(rows) > MAX_ROWS + 1:
            break
    return rows


def _signals_index(signals: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    exact = {str(item.get("id")): str(item.get("id")) for item in signals if item.get("id")}
    by_tag: dict[str, list[str]] = {}
    for item in signals:
        signal_id = str(item.get("id") or "")
        if not signal_id:
            continue
        names = {str(item.get("name") or "")}
        # plantcraft:CPM.Loops.FIC-1001.PV is FIC-1001.PV, Loops.FIC-1001.PV, ... in a DCS list.
        tail = signal_id.partition(":")[2] or signal_id
        parts = tail.split(".")
        names.update(".".join(parts[i:]) for i in range(len(parts)))
        for name in names:
            if name:
                by_tag.setdefault(name.lower(), []).append(signal_id)
    return exact, by_tag


def read(content: bytes, filename: str, signals: list[dict[str, Any]]) -> Read:
    """The rows of a DCS alarm list (``.csv`` or ``.xlsx``), each tag resolved to a signal."""

    found = Read()
    if len(content) > MAX_BYTES:
        found.problem(0, t("The file is larger than {size} MB.", size=MAX_BYTES // 2**20))
        return found
    name = (filename or "").lower()
    decimal_comma = False
    try:
        if name.endswith((".xlsx", ".xlsm")):
            found.format = "xlsx"
            cells = _xlsx_cells(content)
        elif name.endswith((".csv", ".txt", ".tsv")):
            found.format = "csv"
            cells, decimal_comma = _csv_cells(content)
        else:
            found.problem(0, t("Use a .csv or .xlsx file (Excel: save as .xlsx)."))
            return found
    except (zipfile.BadZipFile, ElementTree.ParseError, ValueError, KeyError) as exc:
        found.problem(0, t("The file could not be read: {error}", error=exc))
        return found
    # The header: the first row naming a tag and a type column.
    header_at = None
    for index, row in enumerate(cells[:20]):
        keys = {COLUMN_OF.get(_key(cell)) for cell in row}
        if {"tag", "kind"} <= keys:
            header_at = index
            break
    if header_at is None:
        found.problem(
            0,
            t(
                "No header row with a tag column and an alarm type column (tag, type, limit, "
                "priority, ...): download the template to see one."
            ),
        )
        return found
    where: dict[str, int] = {}
    for index, cell in enumerate(cells[header_at]):
        key = COLUMN_OF.get(_key(cell))
        if key and key not in where:
            where[key] = index
            found.columns[key] = str(cell).strip()
    exact, by_tag = _signals_index(signals)
    seen: dict[str, int] = {}
    data = cells[header_at + 1 :]
    if len(data) > MAX_ROWS:
        found.problem(0, t("Only the first {count} rows are read.", count=MAX_ROWS))
        data = data[:MAX_ROWS]
    for offset, row in enumerate(data):
        line = header_at + offset + 2

        def cell(key: str, row: list[str] = row) -> str:
            index = where.get(key)
            return str(row[index]).strip() if index is not None and index < len(row) else ""

        if not any(str(value).strip() for value in row):
            continue
        tag = _text(cell("tag"), 200)
        raw_kind = cell("kind")
        kind = KIND_OF.get(_key(raw_kind))
        if not tag:
            found.problem(line, t("No tag."))
            continue
        if kind is None:
            found.problem(
                line,
                t("{tag}: alarm type {kind} is not one Alarms imports (HH, HI, LO, LL).",
                  tag=tag, kind=raw_kind or "''"),
            )  # fmt: skip
            continue
        limit = _number(cell("limit"), decimal_comma)
        if limit is None:
            found.problem(
                line, t("{tag} {kind}: no limit, or not a number.", tag=tag, kind=raw_kind)
            )
            continue
        signal_id = exact.get(tag)
        if signal_id is None:
            matches = sorted(set(by_tag.get(tag.lower(), [])))
            if len(matches) == 1:
                signal_id = matches[0]
            elif matches:
                found.problem(
                    line,
                    t("{tag}: more than one signal has this name ({signals}); write its id.",
                      tag=tag, signals=", ".join(matches[:3])),
                )  # fmt: skip
                continue
            else:
                found.problem(line, t("{tag}: no signal of this name in PlantCraft.", tag=tag))
                continue
        deadband = _number(cell("deadband"), decimal_comma)
        delay = _seconds(cell("delay"), decimal_comma)
        if deadband is not None and deadband < 0 or delay is None or delay < 0:
            found.problem(line, t("{tag} {kind}: a negative or unreadable deadband or delay.",
                                  tag=tag, kind=raw_kind))  # fmt: skip
            continue
        raw_priority = cell("priority")
        priority = PRIORITY_OF.get(_key(raw_priority), "" if raw_priority else "medium")
        if not priority:
            found.problem(line, t("{tag} {kind}: priority {priority} is not critical, high, "
                                  "medium, low or 1 to 4.", tag=tag, kind=raw_kind,
                                  priority=raw_priority))  # fmt: skip
            continue
        item = Row(
            line=line,
            tag=tag,
            signal_id=signal_id,
            kind=kind,
            limit=limit,
            name=_text(cell("name"), 120) or f"{tag} {KIND_LABEL[kind]}"[:120],
            unit=_text(cell("unit"), 40),
            deadband=deadband or 0.0,
            on_delay_seconds=float(delay),
            priority=priority,
            enabled=_key(cell("enabled")) not in OFF,
            cause=_text(cell("cause"), 2000),
            consequence=_text(cell("consequence"), 2000),
            action=_text(cell("action"), 2000),
        )
        if item.external_id in seen:
            found.problem(line, t("{alarm} is also on line {other}: the first one is kept.",
                                  alarm=item.external_id, other=seen[item.external_id]))  # fmt: skip
            continue
        seen[item.external_id] = line
        found.rows.append(item)
    if not found.rows and not found.problems:
        found.problem(0, t("The file has a header but no alarm."))
    return found


def rule_fields(rule: dict[str, Any]) -> dict[str, Any] | None:
    """What an imported rule says, in the fields an alarm list has (None: not one of its form)."""

    simple = rule.get("simple") or {}
    conditions = simple.get("conditions") or []
    if rule.get("editor") != "simple" or len(conditions) != 1:
        return None
    [condition] = conditions
    value = condition.get("value") or {}
    kind = str(rule.get("external_id") or "").rpartition("/")[2]
    kind = {label: name for name, label in KIND_LABEL.items()}.get(kind)
    if condition.get("input") != "value" or kind is None:
        return None
    return {
        "name": rule.get("name"),
        "signal_id": value.get("signal") or "",
        "kind": kind,
        "limit": condition.get("limit"),
        "unit": value.get("unit") or "",
        "deadband": condition.get("deadband") or 0.0,
        "on_delay_seconds": condition.get("for_seconds") or 0.0,
        "priority": rule.get("priority") or "medium",
        "enabled": bool(rule.get("enabled", True)),
        "cause": rule.get("cause") or "",
        "consequence": rule.get("consequence") or "",
        "action": rule.get("action") or "",
    }


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float) and not isinstance(a, bool):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def compare(rows: list[Row], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each alarm of the list against the rule an earlier import made: new, changed (with the
    fields), same; and every imported rule the list no longer has: removed (an apply turns it
    off). Rules written by hand (no ``external_id``) are never touched."""

    imported = {str(rule["external_id"]): rule for rule in rules if rule.get("external_id")}
    items: list[dict[str, Any]] = []
    for row in rows:
        after = row.fields()
        rule = imported.pop(row.external_id, None)
        item = {"key": row.external_id, "line": row.line, "after": after, "rule_id": None,
                "rule_updated_at": None, "before": None, "fields": []}  # fmt: skip
        if rule is None:
            items.append({**item, "change": "new"})
            continue
        before = rule_fields(rule)
        item.update(rule_id=rule["rule_id"], rule_updated_at=rule.get("updated_at"), before=before)
        if before is None:
            # Someone rewrote it in Blocks or Python: the list's values replace it only if chosen.
            items.append({**item, "change": "changed", "fields": ["editor"]})
            continue
        changed = [name for name in FIELDS if not _same(before.get(name), after.get(name))]
        items.append({**item, "change": "changed" if changed else "same", "fields": changed})
    for key, rule in sorted(imported.items()):
        before = rule_fields(rule)
        if before is not None and not before["enabled"]:
            continue  # turned off by an earlier import (or by hand): nothing left to do
        items.append({"key": key, "line": None, "change": "removed", "after": None,
                      "before": before, "rule_id": rule["rule_id"],
                      "rule_updated_at": rule.get("updated_at"), "fields": ["enabled"]})  # fmt: skip
    order = {"new": 0, "changed": 1, "removed": 2, "same": 3}
    items.sort(key=lambda item: (order[item["change"]], item["key"].lower()))
    return items


def counts(items: list[dict[str, Any]]) -> dict[str, int]:
    found = {"new": 0, "changed": 0, "removed": 0, "same": 0}
    for item in items:
        found[item["change"]] += 1
    return found


def legacy_of(after: dict[str, Any], external_id: str) -> dict[str, Any]:
    """The row as ``rules.from_legacy`` takes it (a Simple rule on one signal's limit)."""

    return {
        "name": after["name"],
        "signal_id": after["signal_id"],
        "kind": after["kind"],
        "limit": after["limit"],
        "unit": after["unit"],
        "deadband": after["deadband"],
        "on_delay_seconds": after["on_delay_seconds"],
        "priority": after["priority"],
        "enabled": after["enabled"],
        "cause": after["cause"],
        "consequence": after["consequence"],
        "action": after["action"],
        "external_id": external_id,
    }


class AlarmListStore(Store):
    """The drafts: one per file read, until it is applied or thrown away."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS alarm_list_imports (
        import_id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        report_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'draft',
        done_at TEXT,
        done_by TEXT,
        result_json TEXT
    );
    """
    KEEP = 50

    def _record(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        report = self._loads(item.pop("report_json"), {})
        result = self._loads(item.pop("result_json"), None)
        return {**item, **report, "result": result}

    def create(self, filename: str, report: dict[str, Any], *, by: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO alarm_list_imports (filename, report_json, created_at, created_by)"
                " VALUES (?,?,?,?)",
                (filename[:200], self._json(report), self._now(), by),
            )
            import_id = int(cursor.lastrowid or 0)
            connection.execute(
                "DELETE FROM alarm_list_imports WHERE import_id <= ?", (import_id - self.KEEP,)
            )
        return self.get(import_id) or {}

    def get(self, import_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alarm_list_imports WHERE import_id = ?", (import_id,)
            ).fetchone()
        return self._record(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alarm_list_imports ORDER BY import_id DESC LIMIT 20"
            ).fetchall()
        return [self._record(row) for row in rows]

    def claim(self, import_id: int, state: str, *, by: str) -> bool:
        """Applied or discarded, once: False when someone did it already."""

        with self._lock, self._connect() as connection:
            done = connection.execute(
                "UPDATE alarm_list_imports SET state = ?, done_at = ?, done_by = ?"
                " WHERE import_id = ? AND state = 'draft'",
                (state, self._now(), by, import_id),
            ).rowcount
        return bool(done)

    def record_result(self, import_id: int, result: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE alarm_list_imports SET result_json = ? WHERE import_id = ?",
                (self._json(result), import_id),
            )
