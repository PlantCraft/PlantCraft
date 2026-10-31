"""The DCS alarm list: read a CSV or Excel export as a draft, show what it would change (new,
changed, removed, the same) and apply it, the alarms the reviewer kept, only when a person who
edits rules says so (``alarms.alarmlist``). Every rule it writes is audited like one written by
hand, with the import's number."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from alarmcraft.alarms import alarmlist
from alarmcraft.alarms.records import Conflict
from alarmcraft.alarms.rules import RuleDraft, from_legacy
from alarmcraft.api.deps import EditorUser, RuntimeDep, guarded
from alarmcraft.api.routers.rules import _changed, create_rule
from alarmcraft.i18n import t

router = APIRouter(prefix="/api", tags=["alarm list"])


class AlarmListFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=200)
    # The file's bytes in base64 (at most alarmlist.MAX_BYTES once decoded).
    content: str = Field(min_length=1, max_length=alarmlist.MAX_BYTES * 4 // 3 + 8)


class Apply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The alarms (``key``) the reviewer left out; the rest of new, changed and removed apply.
    skip: list[str] = Field(default_factory=list, max_length=alarmlist.MAX_ROWS)


def _draft_or_404(rt: Any, import_id: int) -> dict[str, Any]:
    found = rt.alarm_lists.get(import_id)
    if found is None:
        raise HTTPException(404, t("No such alarm list import."))
    return found


@router.get("/alarm-list/template.csv", response_class=PlainTextResponse)
def template(_user: EditorUser) -> PlainTextResponse:
    """A file to start from: the columns Alarms reads, one example row."""

    return PlainTextResponse(
        alarmlist.TEMPLATE,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="alarm-list-template.csv"'},
    )


@router.get("/alarm-list")
def list_imports(rt: RuntimeDep, _user: EditorUser) -> list[dict[str, Any]]:
    return [
        {
            key: item[key]
            for key in (
                "import_id",
                "filename",
                "created_at",
                "created_by",
                "state",
                "done_at",
                "done_by",
                "counts",
            )
        }  # fmt: skip
        for item in rt.alarm_lists.list()
    ]


@router.post("/alarm-list", status_code=201)
def read_alarm_list(body: AlarmListFile, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """The file as a draft: its alarms against the rules earlier imports made. Nothing changes
    until the draft is applied."""

    try:
        content = base64.b64decode(body.content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, t("The file did not arrive whole; choose it again.")) from exc
    client = rt.user_client(user)
    signals = guarded(lambda: client.signals(), service=False)
    found = alarmlist.read(content, body.filename, [dict(item) for item in signals])
    items = alarmlist.compare(found.rows, rt.rules.list())
    report = {
        "format": found.format,
        "columns": found.columns,
        "rows": len(found.rows),
        "problems": found.problems,
        "counts": alarmlist.counts(items),
        "items": items,
    }
    draft = rt.alarm_lists.create(body.filename, report, by=user.username)
    rt.audit(user, "alarm_list.read", str(draft["import_id"]),
             {"filename": body.filename, "counts": report["counts"]})  # fmt: skip
    return draft


@router.get("/alarm-list/{import_id}")
def get_import(import_id: int, rt: RuntimeDep, _user: EditorUser) -> dict[str, Any]:
    return _draft_or_404(rt, import_id)


@router.post("/alarm-list/{import_id}/discard")
def discard_import(import_id: int, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    _draft_or_404(rt, import_id)
    if not rt.alarm_lists.claim(import_id, "discarded", by=user.username):
        raise HTTPException(409, t("This import was applied or thrown away already."))
    rt.audit(user, "alarm_list.discarded", str(import_id))
    return _draft_or_404(rt, import_id)


def _updated(rule: dict[str, Any], after: dict[str, Any] | None, key: str) -> RuleDraft:
    """The rule with the list's values (or only turned off, ``after`` None); what people set
    in Alarms itself (where, who is notified, owner, area, discipline, dashboards) stays."""

    config = {name: value for name, value in rule.items() if name in RuleDraft.model_fields}
    if after is None:
        config["enabled"] = False
    else:
        made = from_legacy(alarmlist.legacy_of(after, key))
        config.update({name: made[name] for name in ("name", "priority", "enabled", "cause",
                                                    "consequence", "action", "simple")})  # fmt: skip
        config.update(editor="simple", diagram={}, external_id=key)
    return RuleDraft.model_validate(config)


@router.post("/alarm-list/{import_id}/apply")
def apply_import(import_id: int, body: Apply, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """The reviewed draft written: new rules created, changed ones updated, removed ones turned
    off (never deleted). A rule someone changed after the file was read is left as it is and
    listed, so a second read shows the difference again."""

    draft = _draft_or_404(rt, import_id)
    if not rt.alarm_lists.claim(import_id, "applied", by=user.username):
        raise HTTPException(409, t("This import was applied or thrown away already."))
    skip = set(body.skip)
    done = {"created": 0, "changed": 0, "turned_off": 0, "left_out": 0}
    stale: list[dict[str, str]] = []
    for item in draft.get("items") or []:
        key, change = item["key"], item["change"]
        if change == "same":
            continue
        if key in skip:
            done["left_out"] += 1
            continue
        try:
            if change == "new":
                legacy = alarmlist.legacy_of(item["after"], key)
                made = RuleDraft.model_validate({**from_legacy(legacy), "external_id": key})
                create_rule(made, rt, user)
                done["created"] += 1
                continue
            rule = rt.rules.get(item["rule_id"] or "")
            if rule is None:
                stale.append({"key": key, "reason": t("the rule was deleted since")})
                continue
            updated = _updated(rule, item["after"] if change == "changed" else None, key)
            saved = rt.rules.update(
                rule["rule_id"], updated.config(), by=user.username,
                base_updated_at=item.get("rule_updated_at"),
            )  # fmt: skip
        except Conflict:
            stale.append(
                {"key": key, "reason": t("someone changed the rule since the file was read")}
            )
            continue
        except ValueError as exc:
            stale.append({"key": key, "reason": str(exc)[:300]})
            continue
        action = "rule.changed" if change == "changed" else "rule.disabled"
        rt.audit(user, action, rule["rule_id"], {"name": updated.name, "alarm_list": import_id})
        _changed(rt, saved or rule, user.username)
        done["changed" if change == "changed" else "turned_off"] += 1
    result = {**done, "not_applied": stale}
    rt.alarm_lists.record_result(import_id, result)
    rt.audit(user, "alarm_list.applied", str(import_id), result)
    return _draft_or_404(rt, import_id)
