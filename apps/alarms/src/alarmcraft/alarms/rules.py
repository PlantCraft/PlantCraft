"""Rules: what a person writes in Alarms (round 11). A rule says **where** (assets, a branch of
the asset tree, an asset type, a Link execution, or any asset the events name), **when** (its
diagram: inputs, logic, persistence and one Raise an alarm, ``engine.blocks``), **what it makes**
(an alarm or a notice), **who hears** (``notify``) and **why** (the rationalization).

The diagram is written in one of three editors: the **Simple** form (``alarms.simple``, up to
three conditions read as a sentence), **Blocks** (the diagram itself) or **Python** (a diagram
whose logic is a Python block). The rule keeps ``editor`` and, for Simple, the form.

A rule makes one alarm per subject it covers (``per`` asset by default, or per execution, or one
for the whole rule). The alarms keep their ISA-18.2 life (raised, acknowledged, shelved, out of
service) in ``alarms.store``; the rule is their single configuration. A rule with one subject
makes one alarm with the rule's own id.

| Table | Holds |
|---|---|
| ``rules`` | each rule (``RuleDraft``) |
| ``rule_meta`` | small values of the rules' machinery, such as the last event read |
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from plantcraft_sdk.server.store import Migration, Store
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alarmcraft.alarms.blocks import (
    ALARM_BLOCK,
    EVENT_BLOCKS,
    PYTHON_BLOCK,
    VALUE_BLOCK,
    check,
    nodes,
    relative,
)
from alarmcraft.alarms.model import (
    NAME,
    OWNER,
    Creates,
    Discipline,
    Priority,
    _text,
)
from alarmcraft.alarms.notices import NotifyDraft
from alarmcraft.alarms.records import ALARM_ID, Conflict, slug
from alarmcraft.alarms.simple import SimpleLogic, to_diagram

RULE_ID = ALARM_ID
MAX_ASSETS = 500
Editor = Literal["simple", "blocks", "python"]
Per = Literal["asset", "execution", "rule"]
EXECUTION = re.compile(r"^[a-z][a-z0-9_-]{0,39}:[^\x00-\x1f\x7f]{1,200}$")


def _ids(values: list[str], limit: int = 300) -> list[str]:
    found: list[str] = []
    for value in values:
        value = str(value or "").strip()
        if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
            raise ValueError("ids of 1 to 300 characters")
        if value not in found:
            found.append(value)
    return found


class Where(BaseModel):
    """Where a rule applies. Assets named, every asset under some branches, every asset of some
    types, the assets of some Link executions (``<app>:<schedule id>``), or ``anywhere``: any
    asset the events name (an alarm is made when the first event about it comes). Nothing:
    the rule reads only named values and makes one alarm."""

    model_config = ConfigDict(extra="forbid")

    assets: list[str] = Field(default_factory=list, max_length=MAX_ASSETS)
    under: list[str] = Field(default_factory=list, max_length=50)
    types: list[str] = Field(default_factory=list, max_length=20)
    executions: list[str] = Field(default_factory=list, max_length=20)
    anywhere: bool = False
    # One alarm per asset (default), per execution, or one for the whole rule.
    per: Per = "asset"

    @field_validator("assets", "under", "types")
    @classmethod
    def _assets(cls, value: list[str]) -> list[str]:
        return _ids(value)

    @field_validator("executions")
    @classmethod
    def _executions(cls, value: list[str]) -> list[str]:
        found = _ids(value)
        if any(not EXECUTION.match(item) for item in found):
            raise ValueError("an execution is <app>:<id>, like linkcraft:valve-health")
        return found

    @model_validator(mode="after")
    def _per(self) -> Where:
        if self.per == "execution" and not self.executions:
            raise ValueError("one alarm per execution needs the executions")
        if self.anywhere and (self.assets or self.under or self.types or self.executions):
            raise ValueError("any asset, or the assets chosen, not both")
        return self

    @property
    def empty(self) -> bool:
        return not (self.assets or self.under or self.types or self.executions or self.anywhere)


class RuleDraft(BaseModel):
    """One rule as a person writes it (the API's create and update body)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=120)
    enabled: bool = True
    creates: Creates = "alarm"
    priority: Priority = "medium"
    where: Where = Field(default_factory=Where)
    editor: Editor = "simple"
    # The Simple form (editor "simple"); the diagram is written from it.
    simple: SimpleLogic | None = None
    diagram: dict[str, Any] = Field(default_factory=dict)
    # Who answers for it (``user:<name>`` or ``group:<id>``); the creator when left out. An
    # alarm on an execution answers to the owner the app names in its events (Link: the
    # execution's).
    owner: str | None = Field(default=None, max_length=110)
    area: str | None = Field(default=None, max_length=300)
    discipline: Discipline | None = None
    notify: NotifyDraft = Field(default_factory=NotifyDraft)
    # Its alarms colour their assets and show in the Active alarms widgets (View, Overview).
    dashboards: bool = True
    cause: str = Field(default="", max_length=2000)
    consequence: str = Field(default="", max_length=2000)
    action: str = Field(default="", max_length=2000)
    # The alarm's id in the system it was imported from (a DCS alarm list: ``<tag>/<type>``,
    # ``alarms.alarmlist``); the next import of that list matches the rule by it.
    external_id: str | None = Field(default=None, max_length=210)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = (value or "").strip()
        if not NAME.match(value):
            raise ValueError("a name of 1 to 120 characters")
        return value

    @field_validator("owner")
    @classmethod
    def _owner(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if value and not OWNER.match(value):
            raise ValueError("an owner is user:<username> or group:<id>")
        return value or None

    @field_validator("cause", "consequence", "action")
    @classmethod
    def _words(cls, value: str) -> str:
        return _text(value, 2000)

    @model_validator(mode="after")
    def _logic(self) -> RuleDraft:
        self.area = (self.area or "").strip() or None
        if self.editor == "simple":
            if self.simple is None:
                raise ValueError("the Simple form needs at least one condition")
            self.diagram = to_diagram(self.simple)
        else:
            self.simple = None
        plan = check(self.diagram)
        if not plan.valid:
            raise ValueError(" ".join(plan.errors[:3]))
        if self.editor == "python" and not nodes(self.diagram, PYTHON_BLOCK):
            raise ValueError("a Python rule has a Python block")
        if relative(self.diagram) and self.where.empty:
            raise ValueError("this asset's values and events need a rule over assets")
        return self

    @property
    def single(self) -> bool:
        """Whether the rule makes one alarm only (its id is the rule's)."""

        where = self.where
        if where.per == "rule" or where.empty:
            return True
        if where.anywhere or where.under or where.types or where.executions:
            return False
        return len(where.assets) == 1

    def sentence(self) -> str:
        """The rule's condition in words."""

        if self.simple is not None:
            return self.simple.sentence()
        return diagram_words(self.diagram)

    def fingerprint(self) -> str:
        """Changes when the diagram's logic does (not its layout or labels)."""

        logic = {
            "nodes": sorted(
                (
                    node.get("id"),
                    node.get("block"),
                    json.dumps(node.get("parameters") or {}, sort_keys=True),
                )
                for node in self.diagram.get("nodes") or []
            ),
            "edges": sorted(
                json.dumps(edge, sort_keys=True) for edge in self.diagram.get("edges") or []
            ),
        }
        return hashlib.sha256(json.dumps(logic).encode()).hexdigest()[:16]

    def hears(self) -> list[str]:
        """The event kinds its event blocks hear."""

        found: list[str] = []
        for node in nodes(self.diagram, EVENT_BLOCKS):
            for kind in (node.get("parameters") or {}).get("kinds") or []:
                if kind not in found:
                    found.append(kind)
        return found[:40]

    def code(self) -> list[str]:
        """The Python blocks' code (only administrators change it)."""

        return [
            str((node.get("parameters") or {}).get("code") or "")
            for node in nodes(self.diagram, PYTHON_BLOCK)
        ]

    def config(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def diagram_words(diagram: dict[str, Any]) -> str:
    """A diagram in a few words: "Python on Health, Oscillation" or "Diagram of 6 blocks
    (Value pv, Compare, For at least)"."""

    values = [
        str(node.get("label") or (node.get("parameters") or {}).get("role") or "value")
        for node in nodes(diagram, VALUE_BLOCK)
    ]
    if nodes(diagram, PYTHON_BLOCK):
        return "Python: " + (", ".join(values) if values else "no value wired")
    count = len([node for node in diagram.get("nodes") or [] if node.get("block") != ALARM_BLOCK])
    return f"Diagram of {count} blocks" + (f" on {', '.join(values[:4])}" if values else "")


def alarm_id_for(rule_id: str, key: str, *, single: bool) -> str:
    """The id of the rule's alarm on ``key`` (an asset id, ``execution:<app>:<id>``): the rule's
    own when it makes one alarm, else ``<rule>--<key>``, cut with a short hash to fit 63."""

    if single:
        return rule_id
    tail = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-") or "x"
    found = f"{rule_id}--{tail}"
    # Kept readable when it fits and the key was plain (no two keys share the readable id).
    if len(found) <= 63 and re.fullmatch(r"[A-Za-z0-9:-]+", key):
        return found.lower()
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"{rule_id[:40]}--{tail[:12].strip('-')}-{digest}"


def alarm_config(
    rule_id: str,
    rule: RuleDraft,
    *,
    subject: str,
    asset_id: str | None,
    label: str | None,
    owner: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """The configuration of the rule's alarm on one subject (what ``AlarmDraft`` validates)."""

    name = rule.name if not label else f"{rule.name} · {label}"
    return {
        "name": name[:120],
        "rule_id": rule_id,
        "subject": subject,
        "asset_id": asset_id,
        "label": label,
        "priority": rule.priority,
        "creates": rule.creates,
        "sentence": rule.sentence()[:2000],
        "logic": rule.fingerprint(),
        "hears": rule.hears(),
        "cause": rule.cause,
        "consequence": rule.consequence,
        "action": rule.action,
        "enabled": enabled,
        "rule_enabled": rule.enabled,
        "owner": owner or rule.owner,
        "area": rule.area,
        "discipline": rule.discipline,
        "notify": rule.notify.enabled,
        "dashboards": rule.dashboards,
    }


# From the rules of Alarms before round 11 ------------------------------------------------

UPPER = {"high_high": ">=", "high": ">="}
LOWER = {"low_low": "<=", "low": "<="}
SHARED = ("name", "enabled", "creates", "priority", "owner", "area", "discipline", "notify")
WORDS = ("cause", "consequence", "action")


def from_legacy(old: dict[str, Any]) -> dict[str, Any]:
    """A rule of an older Alarms (a kind: high, low, no data, app verdict, repeated event) as a
    Simple rule over the same subjects; best effort, the person checks it in the editor."""

    rule: dict[str, Any] = {key: old[key] for key in SHARED + WORDS if old.get(key) is not None}
    kind = str(old.get("kind") or "high")
    where: dict[str, Any] = {
        "assets": list(old.get("assets") or []),
        "under": list(old.get("under") or []),
    }
    value: dict[str, Any] = (
        {"signal": old["signal_id"]} if old.get("signal_id") else {"role": old.get("role") or "pv"}
    )
    if old.get("unit"):
        value["unit"] = old["unit"]
    seconds = float(old.get("on_delay_seconds") or 0)
    condition: dict[str, Any]
    if kind in UPPER or kind in LOWER:
        condition = {
            "input": "value",
            "value": value,
            "op": UPPER.get(kind) or LOWER[kind],
            "limit": float(old.get("limit") or 0.0),
            "deadband": float(old.get("deadband") or 0.0),
            "for_seconds": seconds,
        }
    elif kind == "no_data":
        # The Historian reports a point without data; the rule says for how long.
        condition = {
            "input": "event",
            "event": {"kinds": ["histcraft.point.no_data"]},
            "test": "open",
            "for_seconds": max(seconds, 60.0),
        }
        if old.get("signal_id"):
            condition["event"]["about"] = f"signal:{old['signal_id']}"
    elif kind == "verdict":
        app = str(old.get("result") or "linkcraft:").partition(":")[0] or "linkcraft"
        severities = ["critical"] if old.get("verdict_status") != "warning" else []
        condition = {
            "input": "event",
            "event": {"kinds": [f"{app}.status.changed"], "severities": severities},
            "test": "open",
            "for_seconds": seconds,
        }
    else:
        events = old.get("events") or {}
        found: dict[str, Any] = {"kinds": list(events.get("kinds") or ["linkcraft.run.failed"])}
        if events.get("severities"):
            found["severities"] = list(events["severities"])
        if not where["assets"] and not where["under"]:
            where["anywhere"] = True
        if old.get("open_minutes"):
            condition = {
                "input": "event",
                "event": found,
                "test": "open",
                "for_seconds": float(old["open_minutes"]) * 60,
            }
        else:
            condition = {
                "input": "event",
                "event": found,
                "test": "count",
                "count": int(old.get("count") or 1),
                "window_minutes": int(old.get("window_minutes") or 60),
            }
    if old.get("signal_id"):
        where = {}
    rule.update(
        where=where,
        editor="simple",
        simple={
            "conditions": [condition],
            "clear_after_seconds": float(old.get("off_delay_seconds") or 0.0),
        },
    )
    return rule


def _from_legacy(connection: Any) -> None:
    """Rewrite every rule of an older Alarms as a Simple rule (``from_legacy``), once."""

    rows = connection.execute("SELECT rule_id, config_json FROM rules").fetchall()
    for row in rows:
        config = json.loads(row["config_json"] or "{}")
        if "diagram" in config:
            continue
        rule = from_legacy(config)
        try:
            draft = RuleDraft.model_validate(rule)
        except ValueError:
            # Kept, off, for the person to rewrite: its old form no longer runs.
            draft = None
        written = draft.config() if draft is not None else {**config, "enabled": False}
        connection.execute(
            "UPDATE rules SET config_json = ? WHERE rule_id = ?",
            (json.dumps(written), row["rule_id"]),
        )


# Blocks retired (owner's review, 2026-10-27) ------------------------------------------------

FROZEN_CHAIN = ("alarm.value", "alarm.changed", "alarm.not", "alarm.for", ALARM_BLOCK)
PYTHON_SHAPE = {"alarm.value", PYTHON_BLOCK, ALARM_BLOCK}


def from_blocks(config: dict[str, Any]) -> dict[str, Any] | None:
    """A rule drawn in the retired Blocks editor as a Python rule (value blocks wired into one
    Python block) or a Simple one (a value that did not change for a time), or None when its
    diagram says more: it keeps running as drawn, and the editor asks to rewrite it."""

    diagram = config.get("diagram") or {}
    found = diagram.get("nodes") or []
    kinds = [node.get("block") for node in found]
    if kinds and set(kinds) <= PYTHON_SHAPE and kinds.count(PYTHON_BLOCK) == 1:
        return {**config, "editor": "python", "simple": None}
    if len(found) != len(FROZEN_CHAIN) or sorted(kinds) != sorted(FROZEN_CHAIN):
        return None
    by_block = {node.get("block"): node for node in found}
    order = {node.get("id"): node.get("block") for node in found}
    chain = [
        (order.get(edge.get("source")), order.get(edge.get("target")))
        for edge in diagram.get("edges") or []
    ]
    if chain and chain != list(zip(FROZEN_CHAIN, FROZEN_CHAIN[1:], strict=False)):
        return None
    value = by_block["alarm.value"].get("parameters") or {}
    held = by_block["alarm.for"].get("parameters") or {}
    raised = by_block[ALARM_BLOCK].get("parameters") or {}
    condition = {
        "input": "value",
        "value": {
            "signal": value.get("signal") or "",
            "role": value.get("role") or "",
            "unit": value.get("unit") or "",
            "name": by_block["alarm.value"].get("label") or "",
        },
        "op": "unchanged",
        "for_seconds": float(held.get("seconds") or 0.0),
        "for_points": int(held.get("points") or 0),
    }
    simple = {
        "conditions": [condition],
        "clear_after_seconds": float(raised.get("clear_after_seconds") or 0.0),
    }
    return {**config, "editor": "simple", "simple": simple}


def _from_blocks(connection: Any) -> None:
    """Rewrite each Blocks rule that fits Simple or Python (``from_blocks``), once."""

    rows = connection.execute("SELECT rule_id, config_json FROM rules").fetchall()
    for row in rows:
        config = json.loads(row["config_json"] or "{}")
        if config.get("editor") != "blocks":
            continue
        rule = from_blocks(config)
        if rule is None:
            continue
        try:
            fields = {key: value for key, value in rule.items() if key in RuleDraft.model_fields}
            written = RuleDraft.model_validate(fields).config()
        except ValueError:
            continue
        connection.execute(
            "UPDATE rules SET config_json = ? WHERE rule_id = ?",
            (json.dumps({**config, **written}), row["rule_id"]),
        )


class RuleStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS rules (
        rule_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        config_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS rule_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """

    MIGRATIONS = (
        Migration("rules-as-diagrams", _from_legacy),
        Migration("blocks-retired", _from_blocks),
    )

    def _rule(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        return {**self._loads(item.pop("config_json"), {}), **item}

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM rules ORDER BY name COLLATE NOCASE").fetchall()
        return [self._rule(row) for row in rows]

    def get(self, rule_id: str) -> dict[str, Any] | None:
        if not RULE_ID.match(rule_id or ""):
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM rules WHERE rule_id = ?", (rule_id,)).fetchone()
        return self._rule(row) if row else None

    def create(
        self,
        config: dict[str, Any],
        *,
        by: str,
        rule_id: str | None = None,
        taken: set | None = None,
    ) -> dict[str, Any]:
        """A new rule; its id from the name, unless ``rule_id`` is given. ``taken``: other ids
        it must not take (the alarms' own)."""

        now = self._now()
        taken = taken or set()
        with self._lock, self._connect() as connection:
            if rule_id is None:
                base = slug(config["name"])[:40]
                rule_id, number = base, 2
                while (
                    rule_id in taken
                    or connection.execute(
                        "SELECT 1 FROM rules WHERE rule_id = ?", (rule_id,)
                    ).fetchone()
                ):
                    rule_id, number = f"{base}-{number}", number + 1
            connection.execute(
                "INSERT INTO rules (rule_id, name, config_json, created_at, created_by,"
                " updated_at, updated_by) VALUES (?,?,?,?,?,?,?)",
                (rule_id, config["name"], self._json(config), now, by, now, by),
            )
        return self.get(rule_id) or {}

    def update(
        self, rule_id: str, config: dict[str, Any], *, by: str, base_updated_at: str | None = None
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT updated_at FROM rules WHERE rule_id = ?", (rule_id,)
            ).fetchone()
            if row is None:
                return None
            if base_updated_at and base_updated_at != row["updated_at"]:
                raise Conflict(rule_id)
            connection.execute(
                "UPDATE rules SET name = ?, config_json = ?, updated_at = ?, updated_by = ?"
                " WHERE rule_id = ?",
                (config["name"], self._json(config), self._now(), by, rule_id),
            )
        return self.get(rule_id)

    def delete(self, rule_id: str) -> bool:
        with self._lock, self._connect() as connection:
            gone = connection.execute("DELETE FROM rules WHERE rule_id = ?", (rule_id,)).rowcount
        return bool(gone)

    def meta(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM rule_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO rule_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
