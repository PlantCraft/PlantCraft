"""What Analytics shares with the suite, and what it reads from it (app standard, section 6).

- **Results**: after each round, each loop that is a PlantCraft asset gets one
  ``loop_health`` result on ``asset:<id>`` (status ok/warning/alarm/unknown, score = health,
  summary = the limiting finding, worded by the method's ``describe()``), expiring after about
  two round periods so a stopped Analytics never leaves a green light behind.
- **Derived series**: the same loops get one point per round in one signal of Analytics' own
  source, ``app-linkcraft:<loop id>.<algorithm>.health`` (number, unit ``/100``), with the
  loop's asset as subject and ``loop_health`` as result, so any app reads a loop's health over
  time through API v1 like any other signal (its status band is in the result). Each output an
  algorithm records is one more: ``app-linkcraft:<asset>.<algorithm>.<output>``, across its
  versions; ``app-linkcraft:algorithm.<id>.version`` marks where a version started.
- **Events**: a method that starts flagging a loop (warning or bad) opens a finding
  (``linkcraft.finding.opened``); when it stops, the finding closes (``linkcraft.finding.closed``).
  Open findings are kept in ``suite_findings`` and change only once PlantCraft took the event.
- **Runs and schedules**: each round is a run; the schedule list is replaced after changes.
- **Signal quality**: before a loop is judged, the latest verdicts of the Signal quality
  algorithm on its signals (in Analytics, ``signals/``) decide whether its data may be used
  (``quality_verdicts``); stale or missing verdicts leave the decision to the built-in gate.

Signal and asset ids are opaque, exactly as API v1 gives them: ``plantcraft_sdk.refs``
wraps them as references (``asset:<id>``, ``signal:<source id>:<tag>``); none is built from a tag.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any
from urllib.parse import quote

import pandas as pd
from plantcraft_sdk.derived import MAX_NAME, SCORE_UNIT, DerivedIn, source_of
from plantcraft_sdk.refs import RefError, asset_ref, run_ref
from pydantic import ValidationError

from linkcraft.blocks import compile_algorithm
from linkcraft.blocks.convert import diagram_of
from linkcraft.blocks.run import recorded_keys
from linkcraft.catalog.presets import PresetStore
from linkcraft.catalog.registry import describe_result, gate_method_ids, method_name
from linkcraft.config import LoopConfig
from linkcraft.data.frames import loop_signal_ids
from linkcraft.data.suite import SuiteClient, summary_text
from linkcraft.db import Database, Store
from linkcraft.engine.recurrence import Recurrence, describe
from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)

APP_ID = "linkcraft"
HEALTH_KIND = "loop_health"
FINDING_OPENED = f"{APP_ID}.finding.opened"
FINDING_CLOSED = f"{APP_ID}.finding.closed"
# Loop status (a band of health) -> the suite's one status vocabulary.
SUITE_STATUS = {"normal": "ok", "medium": "warning", "high": "alarm", "critical": "alarm"}
# Loop states in which the methods' verdicts say nothing new about findings.
NOT_JUDGED = {"no_data", "inactive", "incomplete", "pending"}
FLAGGED = {"warning", "bad"}
# Subjects one run lists (API v1 refuses a run with more than 500).
MAX_RUN_SUBJECTS = 500
# Every series Link writes on an asset is ``app-linkcraft:<asset>.<algorithm>.<output>``: a
# loop's health (``<loop>.<algorithm>.health``) and each output an algorithm records. Each
# algorithm adds one ``app-linkcraft:algorithm.<id>.version`` (text, a point when it changes).
HEALTH_SERIES = "health"
VERSION_PREFIX = "algorithm"
VERSION_SERIES = "version"
# A loop judged without an algorithm of its own (its methods alone).
DEFAULT_ALGORITHM = "cpm"
# An algorithm's outputs (``blocks.outputs``): result kind ``out_<key>``, and the message
# events, tracked in ``suite_findings`` under ``message:<block id>``. Recorded ports are series
# ``app-linkcraft:<asset>.<algorithm>.<output>`` (``blocks.run.recorded_keys``).
OUTPUT_PREFIX = "out_"
# The suite's alert shape (PlantCraft can turn it into a message later): subject the asset,
# summary the text, payload severity info|warning|critical.
MESSAGE_OPENED = f"{APP_ID}.protocol.alert"
MESSAGE_CLOSED = f"{APP_ID}.protocol.cleared"
ALERT_SEVERITY = {"bad": "critical", "warning": "warning"}
MESSAGE_PREFIX = "message:"
# A block result status -> the suite's status vocabulary.
OUTPUT_STATUS = {"ok": "ok", "warning": "warning", "bad": "alarm"}


def condition_key(asset_id: str, name: str) -> str:
    """The key of a finding or message on an asset: its opened and closed events share it."""

    return f"{asset_id}/{name}"[:200]


# Set once Link retired the series it wrote before 0.4 (a loop's ``.status`` text, a verdict's
# ``_status`` code, recorded ports named by block id): ``retire_old_series``.
OLD_SERIES_MARK = "series.retired-0.4"
# Set once Link retired what its algorithms on assets wrote before round 8: ``old_asset_series``.
ASSET_SERIES_MARK = "series.retired-round-8"


def old_series(
    ids: set[str], diagrams: dict[str, dict[str, Any]], loops: set[str] = frozenset()
) -> list[str]:
    """Which of Link's own series (``ids``) it no longer writes.

    ``diagrams``: each algorithm's diagram by id, to find the ports it once recorded under
    ``<asset>.<algorithm>.<block id>.<port>`` that now have a key of their own. ``loops``: the
    loop ids, whose health and status were ``<loop>.health`` and ``<loop>.status``.
    """

    old = {series_id(loop_id, suffix) for loop_id in loops for suffix in ("health", "status")}
    # A verdict's status code (new keys never hold "_": ``blocks.run.output_key``).
    old |= {item for item in ids if item.endswith("_status") and item[: -len("_status")] in ids}
    for algorithm_id, diagram in diagrams.items():
        plan = compile_algorithm(diagram)
        if not plan.valid:
            continue
        for (node_id, port), key in recorded_keys(plan).items():
            if key == f"{node_id}.{port}":
                continue
            suffix = f".{algorithm_id}.{node_id}.{port}"
            old |= {item for item in ids if item.endswith(suffix)}
    return sorted(old & ids)


def old_asset_series(signals: list[dict[str, Any]], algorithms: set[str]) -> list[str]:
    """The series algorithms on assets wrote before their schedules chose what is recorded
    (round 8, D6): ``app-linkcraft:<asset>.<algorithm>.<output>``, set by no schedule
    (``managed_by`` empty); the schedules now write ``<asset>.<schedule key>.<output>``."""

    prefix = f"{source_of(APP_ID)}:"
    found = []
    for item in signals:
        signal = str(item.get("id") or "")
        name = signal.removeprefix(prefix)
        if item.get("managed_by") or name == signal or name.startswith(f"{VERSION_PREFIX}."):
            continue
        if any(f".{algorithm}." in name for algorithm in algorithms):
            found.append(signal)
    return sorted(found)


def retire_old_series(
    suite: SuiteClient, presets: PresetStore, loops: set[str] = frozenset()
) -> int:
    """Once each: retire the series Link stopped writing in 0.4 and those its algorithms on
    assets wrote before round 8 (fewer signals in its source)."""

    marks = [mark for mark in (OLD_SERIES_MARK, ASSET_SERIES_MARK) if presets.marked(mark) is None]
    if not marks:
        return 0
    listed = suite.own_signals(APP_ID)
    if listed is None:
        return 0  # PlantCraft unread: try again at the next start
    ids = {str(item.get("id")) for item in listed}
    diagrams, on_assets = {}, set()
    for profile in presets.list_profiles():
        config = profile.get("method_config") or {}
        if config.get("subject_kind") == "asset":
            on_assets.add(str(profile["profile_id"]))
        try:
            diagrams[str(profile["profile_id"])] = diagram_of(config)
        except Exception:  # an algorithm Link cannot read records nothing to retire
            continue
    old: set[str] = set()
    if OLD_SERIES_MARK in marks:
        old |= set(old_series(ids, diagrams, loops))
    if ASSET_SERIES_MARK in marks:
        old |= set(old_asset_series(listed, on_assets))
    wanted = sorted(old)
    retired: list[str] = []
    for start in range(0, len(wanted), 500):
        done = suite.retire_series(wanted[start : start + 500])
        if done is None:
            return len(retired)  # retried at the next start
        retired.extend(done)
    for mark in marks:
        presets.mark(mark, str(len(retired)))
    if retired:
        LOGGER.info("Retired %d series Link no longer writes", len(retired))
    return len(retired)


def series_id(loop_id: str, suffix: str) -> str:
    """``app-linkcraft:<asset>.<suffix>``, the id of one of an asset's derived series."""

    return f"{source_of(APP_ID)}:{loop_id}.{suffix}"


def suite_status(summary: dict[str, Any] | None) -> str:
    """ok, warning, alarm or unknown (no health: no data, inactive, incomplete, pending)."""

    if not summary or summary.get("health") is None:
        return "unknown"
    return SUITE_STATUS.get(str(summary.get("status")), "unknown")


def health_summary(summary: dict[str, Any] | None) -> str:
    """One line people read: the limiting finding, else why there is no health."""

    summary = summary or {}
    limiting = summary.get("limiting") or {}
    if limiting.get("finding"):
        return str(limiting["finding"])
    if summary.get("health") is None:
        return str(summary.get("operating_state_reason") or t("No health in this run."))
    return t("Health {health}; no method limits it.", health=round(float(summary["health"])))


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


class SeriesVersionStore(Store):
    """The version of each algorithm Link last wrote to its ``algorithm.<id>.version`` series."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS series_versions (
        algorithm_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL
    );
    """

    def written(self) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM series_versions").fetchall()
        return {row["algorithm_id"]: int(row["version"]) for row in rows}

    def save(self, versions: dict[str, int]) -> None:
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO series_versions VALUES (?, ?)", list(versions.items())
            )


class FindingStore(Store):
    """Findings Analytics told PlantCraft are open, per loop and method."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS suite_findings (
        loop_id TEXT NOT NULL,
        method_id TEXT NOT NULL,
        severity TEXT NOT NULL,
        finding TEXT NOT NULL,
        opened_at TEXT NOT NULL,
        PRIMARY KEY (loop_id, method_id)
    );
    """

    def open_findings(self) -> dict[str, dict[str, dict[str, Any]]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM suite_findings").fetchall()
        found: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            found.setdefault(row["loop_id"], {})[row["method_id"]] = dict(row)
        return found

    def opened(self, loop_id: str, method_id: str, severity: str, finding: str, at: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO suite_findings VALUES (?, ?, ?, ?, ?)",
                (loop_id, method_id, severity, finding, at),
            )

    def closed(self, loop_id: str, method_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM suite_findings WHERE loop_id = ? AND method_id = ?",
                (loop_id, method_id),
            )


def _moment(value: Any) -> str:
    """A one-off monitor's moment as people read it: on its own clock (saved with its offset)."""

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value or "—")


def cadence_words(schedule: dict[str, Any]) -> str:
    """How often a schedule runs, in people's words."""

    cadence = schedule.get("cadence")
    at = schedule.get("time_local") or "08:00"
    if cadence == "interval":
        minutes = float(schedule.get("interval_minutes") or 0)
        return t("every {minutes} minutes", minutes=f"{minutes:g}")
    if cadence == "hourly":
        return t("every hour at minute {minute}", minute=at.partition(":")[2] or "00")
    if cadence == "daily":
        return t("every day at {time}", time=at)
    if cadence == "weekly":
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        weekday = schedule.get("weekday")
        day = days[weekday] if isinstance(weekday, int) and 0 <= weekday < 7 else days[0]
        return t("every {day} at {time}", day=t(day), time=at)
    if cadence == "once":
        return t("once, at {moment}", moment=_moment(schedule.get("scheduled_for")))
    if cadence == "calendar" and schedule.get("recurrence"):
        text = describe(Recurrence.model_validate(schedule["recurrence"]))
        return text[:1].lower() + text[1:]
    return str(cadence or "")


def schedule_when(schedule: dict[str, Any]) -> str:
    """When a schedule runs, as its page says it: "Every 15 minutes, Mon to Fri"."""

    text = cadence_words(schedule)
    return text[:1].upper() + text[1:]


class SuitePublisher:
    """Writes Analytics' results, events, runs and schedules to PlantCraft."""

    def __init__(self, db: Database, suite: SuiteClient, *, root_path: str = "/link"):
        self.suite = suite
        self.findings = FindingStore(db)
        self.presets = PresetStore(db)
        self.versions = SeriesVersionStore(db)
        # Names and versions of the algorithms one publish uses (read once per publish).
        self._names: dict[str, tuple[str, int | None]] = {}
        self.root = root_path.rstrip("/")

    def asset_url(self, asset_id: str) -> str:
        return f"{self.root}/assets/{quote(asset_id, safe='')}"

    # Results and events ------------------------------------------------------

    def publish_round(
        self,
        payloads: dict[str, Any],
        origins: dict[str, str],
        *,
        completed_at: datetime,
        interval_minutes: float,
        run_id: str | None = None,
    ) -> dict[str, int]:
        """Health results for every asset loop of the round, then its finding events."""

        self._names = {}
        expires = completed_at + timedelta(minutes=2 * max(1.0, float(interval_minutes)))
        rows = []
        assets = [loop_id for loop_id in payloads if origins.get(loop_id, "user") == "processcraft"]
        for loop_id in assets:
            summary = payloads[loop_id].get("summary") or {}
            limiting = summary.get("limiting") or {}
            rows.append(
                {
                    "subject": asset_ref(loop_id),
                    "kind": HEALTH_KIND,
                    "status": suite_status(summary),
                    "score": summary.get("health"),
                    "usable": None,
                    "value": summary.get("health"),
                    "summary": summary_text(health_summary(summary)),
                    "detail": {
                        "loop_status": summary.get("status"),
                        "limiting_method": limiting.get("method_id"),
                        "operating_state": summary.get("operating_state"),
                        "url": self.asset_url(loop_id),
                    },
                    "at": _iso(completed_at),
                    "expires_at": _iso(expires),
                }
            )
        published = len(rows) if rows and self.suite.put_results(rows) else 0
        opened, closed = self._findings(payloads, assets, completed_at, run_id)
        series = self._series(payloads, assets, completed_at)
        counts = {"results": published, "opened": opened, "closed": closed, "series": series}
        outputs = self.publish_outputs(
            payloads,
            origins,
            completed_at=completed_at,
            interval_minutes=interval_minutes,
            run_id=run_id,
            versions=False,  # written with the health, in the round's one request
        )
        return {**counts, **{f"output_{key}": value for key, value in outputs.items()}}

    def publish_outputs(
        self,
        payloads: dict[str, Any],
        origins: dict[str, str],
        *,
        completed_at: datetime,
        interval_minutes: float,
        run_id: str | None = None,
        versions: bool = True,
    ) -> dict[str, int]:
        """The algorithms' outputs of asset loops: results, series and messages.

        A round publishes them with the loops' health; a scheduled algorithm run (a job)
        publishes them alone. Loops defined only in Link have no asset: their outputs stay
        in Link (the loop page and Runs).
        """

        self._names = {}
        assets = [loop_id for loop_id in payloads if origins.get(loop_id, "user") == "processcraft"]
        if not assets:
            return {"results": 0, "series": 0, "messages": 0}
        expires = completed_at + timedelta(minutes=2 * max(1.0, float(interval_minutes)))
        at = _iso(completed_at)
        rows: list[dict[str, Any]] = []
        series: list[dict[str, Any]] = []
        runs: list[dict[str, Any]] = []
        for loop_id in assets:
            payload = payloads[loop_id]
            outputs = (payload.get("summary") or {}).get("outputs") or []
            tag = str((payload.get("config") or {}).get("name") or loop_id)
            try:
                subject = asset_ref(loop_id)
            except RefError as exc:
                LOGGER.warning("Not publishing the outputs of loop %r: %s", loop_id, exc)
                continue
            for output in outputs:
                if not isinstance(output, dict):
                    continue
                kind = f"{OUTPUT_PREFIX}{output.get('key')}"
                value = output.get("value")
                if output.get("kind") == "result":
                    rows.append(
                        {
                            "subject": subject,
                            "kind": kind,
                            "status": OUTPUT_STATUS.get(str(output.get("status")), "unknown"),
                            "score": value,
                            "usable": None,
                            "value": value,
                            "summary": summary_text(
                                f"{output.get('name')}: {output.get('message') or ''}".rstrip(": ")
                            ),
                            "detail": {
                                "output": output.get("name"),
                                "status": output.get("status"),
                                "url": self.asset_url(loop_id),
                            },
                            "at": at,
                            "expires_at": _iso(expires),
                        }
                    )
            if payload.get("schedule"):
                # What its schedule records (``assets.outputs.recorded_points``).
                points = payload.get("recorded_points") or {}
                series.extend(points.get("values") or [])
                runs.extend(points.get("runs") or [])
            else:
                series.extend(self._recorded(loop_id, tag, subject, payload, at))
        changed: dict[str, int] = {}
        if versions:
            marks, changed = self._versions(payloads, assets, at)
            series.extend(marks)
        saved = len(rows) if rows and self.suite.put_results(rows) else 0
        written = self.suite.put_series(series) if series and self.suite.available("series") else 0
        if written and changed:
            self.versions.save(changed)
        if runs and self.suite.available("series_runs"):
            written += self.suite.put_series_runs(runs)
        messages = self._messages(payloads, assets, completed_at, run_id)
        return {"results": saved, "series": written, "messages": messages}

    def publish_asset_run(
        self, payload: dict[str, Any], completed_at: datetime, interval_minutes: float
    ) -> dict[str, int]:
        """One run of an algorithm on an asset: its results, new series points and messages."""

        asset_id = str(payload["asset"]["id"])
        return self.publish_outputs(
            {asset_id: payload},
            {asset_id: "processcraft"},
            completed_at=completed_at,
            interval_minutes=interval_minutes,
        )

    def _algorithm(self, algorithm_id: str) -> tuple[str, int | None]:
        """An algorithm's name and version, for its series' names and points."""

        if algorithm_id not in self._names:
            profile = self.presets.get_profile(algorithm_id) if algorithm_id else None
            version = (profile or {}).get("version")
            self._names[algorithm_id] = (
                str(
                    (profile or {}).get("name")
                    or (t("Loop methods") if algorithm_id == DEFAULT_ALGORITHM else algorithm_id)
                    or t("Algorithm")
                ),
                int(version) if version else None,
            )
        return self._names[algorithm_id]

    def _versions(
        self, payloads: dict[str, Any], assets: list[str], at: str
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """``algorithm.<id>.version``, one text series per algorithm (not per asset): a point
        ("v3") when the version that ran changed, so charts mark where a new version started
        writing the same series."""

        known = self.versions.written()
        items: list[dict[str, Any]] = []
        changed: dict[str, int] = {}
        for loop_id in assets:
            algorithm = str((payloads[loop_id].get("summary") or {}).get("algorithm") or "")
            name, version = self._algorithm(algorithm)
            if not algorithm or version is None or algorithm in changed:
                continue
            if known.get(algorithm) == version:
                continue
            item = {
                "signal": f"{source_of(APP_ID)}:{VERSION_PREFIX}.{algorithm}.{VERSION_SERIES}",
                "t": [at],
                "v": [f"v{version}"],
                "name": f"{name} · {t('Version')}"[:MAX_NAME],
                "unit": "",
                "description": t("The version of the algorithm from this point on."),
                "kind": "text",
            }
            try:
                DerivedIn.model_validate(item)
            except ValidationError:
                continue
            items.append(item)
            changed[algorithm] = version
        return items, changed

    def _recorded(
        self, loop_id: str, tag: str, subject: str, payload: dict[str, Any], at: str
    ) -> list[dict[str, Any]]:
        """The ports the algorithm records: one series each per asset and algorithm.

        ``app-linkcraft:<asset>.<algorithm>.<output>``, named ``<tag> · <algorithm> · <output>``.
        A new version of the algorithm keeps adding points to the same series; a verdict is its
        score (``/100``), its status stays in the run (Link's Executions) and in the result.
        """

        summary = payload.get("summary") or {}
        algorithm = str(summary.get("algorithm") or "algorithm")
        algorithm_name, _version = self._algorithm(algorithm)
        found: list[dict[str, Any]] = []
        for entry in summary.get("recorded") or []:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key") or f"{entry.get('node_id')}.{entry.get('port')}"
            output = str(entry.get("label") or key)
            if "." in str(key):  # a block that records several ports names the port too
                output = f"{output} {t(str(entry.get('port_label') or ''))}".strip()
            name = f"{tag} · {algorithm_name} · {output}"
            value = entry.get("value")
            # A series an algorithm on assets records carries its new points; else one point.
            points = entry.get("points") or {}
            item = {
                "signal": f"{source_of(APP_ID)}:{loop_id}.{algorithm}.{key}",
                "t": list(points.get("t") or []) or [at],
                "v": list(points.get("v") or []) or [None if value is None else float(value)],
                "name": name[:MAX_NAME],
                "unit": SCORE_UNIT if entry.get("type") == "result" else entry.get("unit") or "",
                "description": t(str(entry.get("description") or "")),
                "kind": "number",
                "subject": subject,
            }
            try:
                DerivedIn.model_validate(item)
            except ValidationError as exc:
                LOGGER.warning("Not publishing %s: %s", item["signal"], exc.errors()[0]["msg"])
                continue
            found.append(item)
        return found

    def _messages(
        self,
        payloads: dict[str, Any],
        assets: list[str],
        completed_at: datetime,
        run_id: str | None,
    ) -> int:
        """Raise an alert event when a message output triggers; clear it when it recovers."""

        if not self.suite.available("events"):
            return 0
        known = self.findings.open_findings()
        at = _iso(completed_at)
        refs_extra = [run_ref(APP_ID, run_id)] if run_id else []
        pending: list[tuple[dict[str, Any], Callable[[], None]]] = []
        for loop_id in assets:
            payload = payloads[loop_id]
            tag = str((payload.get("config") or {}).get("name") or loop_id)
            # An algorithm on assets tracks its messages under its own id: several algorithms
            # may run on one asset, and one never closes another's.
            scope = f"{MESSAGE_PREFIX}{(payload.get('summary') or {}).get('message_scope') or ''}"
            outputs = {
                f"{scope}{item.get('node_id')}": item
                for item in (payload.get("summary") or {}).get("outputs") or []
                if isinstance(item, dict) and item.get("kind") == "message"
            }
            before = {
                key: row
                for key, row in known.get(loop_id, {}).items()
                if key.startswith(scope)
                and (scope != MESSAGE_PREFIX or "." not in key[len(scope) :])
            }
            subject = asset_ref(loop_id)
            for key, item in outputs.items():
                if not item.get("triggered") or key in before:
                    continue
                text = f"{tag}: {item.get('text') or item.get('message') or ''}".strip()
                severity = ALERT_SEVERITY.get(str(item.get("status")), "info")
                event = {
                    "kind": MESSAGE_OPENED,
                    "subject": subject,
                    "summary": text,
                    "refs": [subject, *refs_extra],
                    "severity": severity,
                    "phase": "start",
                    "key": condition_key(loop_id, key),
                    "payload": {
                        "output": item.get("name"),
                        "severity": severity,
                        "status": item.get("status"),
                        "score": item.get("value"),
                        "url": self.asset_url(loop_id),
                    },
                }
                record = partial(
                    self.findings.opened, loop_id, key, str(item.get("status")), text, at
                )
                pending.append((event, record))
            for key, row in before.items():
                if outputs.get(key, {}).get("triggered"):
                    continue
                event = {
                    "kind": MESSAGE_CLOSED,
                    "subject": subject,
                    "summary": t("Closed: {finding}", finding=row["finding"]),
                    "refs": [subject, *refs_extra],
                    "severity": "ok",
                    "phase": "end",
                    "key": condition_key(loop_id, key),
                    "payload": {"severity": "info", "opened_at": row["opened_at"]},
                }
                pending.append((event, partial(self.findings.closed, loop_id, key)))
        return len(self._send_events(pending))

    def _series(self, payloads: dict[str, Any], assets: list[str], completed_at: datetime) -> int:
        """Each asset loop's health at the round time, in one list (the SDK splits it).

        A loop without health this round writes an empty point (null), so a reader sees the gap.
        An item PlantCraft would refuse (an id it cannot hold) is left out, not the whole list.
        """

        if not assets or not self.suite.available("series"):
            return 0
        at = [_iso(completed_at)]
        items = []
        for loop_id in assets:
            payload = payloads[loop_id]
            summary = payload.get("summary") or {}
            tag = str((payload.get("config") or {}).get("name") or loop_id)
            try:
                subject = asset_ref(loop_id)
            except RefError as exc:
                LOGGER.warning("Not publishing the series of loop %r: %s", loop_id, exc)
                continue
            health = summary.get("health")
            algorithm = str(summary.get("algorithm") or DEFAULT_ALGORITHM)
            item = {
                "signal": series_id(loop_id, f"{algorithm}.{HEALTH_SERIES}"),
                "t": at,
                "v": [None if health is None else float(health)],
                "name": f"{tag} · {self._algorithm(algorithm)[0]} · {t('Health')}"[:MAX_NAME],
                "unit": SCORE_UNIT,
                "kind": "number",
                "subject": subject,
                "result": HEALTH_KIND,
            }
            try:
                DerivedIn.model_validate(item)
            except ValidationError as exc:
                LOGGER.warning("Not publishing %s: %s", item["signal"], exc.errors()[0]["msg"])
                continue
            items.append(item)
        marks, changed = self._versions(payloads, assets, at[0])
        written = self.suite.put_series(items + marks)
        if written and changed:
            self.versions.save(changed)
        return min(written, len(items))

    def _findings(
        self,
        payloads: dict[str, Any],
        assets: list[str],
        completed_at: datetime,
        run_id: str | None,
    ) -> tuple[int, int]:
        if not self.suite.available("events"):
            return 0, 0
        known = self.findings.open_findings()
        gate = set(gate_method_ids())
        at = _iso(completed_at)
        refs_extra = [run_ref(APP_ID, run_id)] if run_id else []
        # (event, what to record once PlantCraft took it)
        pending: list[tuple[dict[str, Any], Callable[[], None]]] = []
        for loop_id in assets:
            payload = payloads[loop_id]
            if (payload.get("summary") or {}).get("status") in NOT_JUDGED:
                continue  # no verdict this round: open findings stay open
            current = {
                item["method_id"]: item
                for item in payload.get("results") or []
                if isinstance(item, dict)
                and item.get("status") in FLAGGED
                and item.get("method_id") not in gate
            }
            # Message outputs share the table; they open and close in ``_messages``.
            before = {
                key: row
                for key, row in known.get(loop_id, {}).items()
                if not key.startswith(MESSAGE_PREFIX)
            }
            subject = asset_ref(loop_id)
            for method_id, item in current.items():
                if method_id in before:
                    continue
                finding = describe_result(item)
                severity = ALERT_SEVERITY.get(str(item.get("status")), "info")
                event = {
                    "kind": FINDING_OPENED,
                    "subject": subject,
                    "summary": finding,
                    "refs": [subject, *refs_extra],
                    "severity": severity,
                    "phase": "start",
                    "key": condition_key(loop_id, method_id),
                    "payload": {
                        "method_id": method_id,
                        # Its name, so a report counting findings by method reads it.
                        "method_name": method_name(method_id),
                        "severity": severity,
                        "status": item.get("status"),
                        "score": item.get("score"),
                        "url": self.asset_url(loop_id),
                    },
                }
                record = partial(
                    self.findings.opened, loop_id, method_id, str(item.get("status")), finding, at
                )
                pending.append((event, record))
            for method_id, row in before.items():
                if method_id in current:
                    continue
                event = {
                    "kind": FINDING_CLOSED,
                    "subject": subject,
                    "summary": t("Closed: {finding}", finding=row["finding"]),
                    "refs": [subject, *refs_extra],
                    "severity": "ok",
                    "phase": "end",
                    "key": condition_key(loop_id, method_id),
                    "payload": {
                        "method_id": method_id,
                        "method_name": method_name(method_id),
                        "opened_at": row["opened_at"],
                    },
                }
                pending.append((event, partial(self.findings.closed, loop_id, method_id)))
        sent = self._send_events(pending)
        opened = sum(1 for event in sent if event["kind"] == FINDING_OPENED)
        return opened, len(sent) - opened

    def _send_events(
        self, pending: list[tuple[dict[str, Any], Callable[[], None]]]
    ) -> list[dict[str, Any]]:
        """Post the round's events as lists (``SuiteClient.post_events``).

        A finding is recorded only once PlantCraft took its event; the others (a failed
        request, an event refused on its own) go again next round.
        """

        if not pending:
            return []
        taken = self.suite.post_events([event for event, _ in pending])
        sent = []
        for (event, record), ok in zip(pending, taken):
            if ok:
                record()
                sent.append(event)
        return sent

    # Runs and schedules ------------------------------------------------------

    def publish_run(self, run: dict[str, Any]) -> bool:
        """One run; a round over more loops than a run may list names the first 500."""

        run = {"url": f"{self.root}/runs", **run}
        if len(run.get("subjects") or []) > MAX_RUN_SUBJECTS:
            run["subjects"] = list(run["subjects"])[:MAX_RUN_SUBJECTS]
        return self.suite.put_runs([run])

    def publish_knowledge(self, items: list[dict[str, Any]]) -> bool:
        """Texts the suite's assistants read (``linkcraft.knowledge``)."""

        return self.suite.put_knowledge(items)

    def publish_schedules(
        self, schedules: list[dict[str, Any]], results: list[dict[str, Any]] | None = None
    ) -> bool:
        rows = [
            {
                "id": item["schedule_id"],
                "name": item.get("name") or item["schedule_id"],
                "cadence": cadence_words(item),
                "next_run": item.get("next_run_at") if item.get("enabled", 1) else None,
                "enabled": bool(item.get("enabled", 1)),
                "url": f"{self.root}/runs",
                "subjects": list(item.get("subjects") or []),
            }
            for item in schedules
        ]
        saved = self.suite.put_schedules(rows)
        if results is not None:  # the result assets the schedules record into
            self.suite.sync_result_assets(results)
        return saved


def quality_verdicts(
    latest: dict[str, dict[str, Any]],
    loops: list[LoopConfig],
    *,
    max_age_minutes: float,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """The Signal quality algorithm's word on each loop's data, from its latest verdicts.

    ``latest`` maps a signal id to its latest verdict (``signals.store``: ``status`` good,
    suspect, bad or unknown, ``apt``, ``message``, ``checked_at``). ``{"blocked": [reasons],
    "covered": bool, "roles": {role: verdict}}`` per loop with at least one fresh verdict:
    ``blocked`` lists the signals the algorithm calls unusable (``bad``); ``covered`` means every
    signal of the loop has a fresh verdict; ``roles`` gives each role's verdict (``status``,
    ``quality``, ``message``) to the diagram's Signal quality blocks. Verdicts older than ``max_age_minutes``, ``unknown`` or missing ones say
    nothing; with none, the built-in gate decides.
    """

    if not latest or not loops:
        return {}
    now = now or datetime.now(timezone.utc)
    oldest = now - timedelta(minutes=max(1.0, float(max_age_minutes)))
    fresh: dict[str, dict[str, Any]] = {}
    for signal_id, verdict in latest.items():
        if not isinstance(verdict, dict):
            continue
        status, checked = verdict.get("status"), verdict.get("checked_at")
        if not isinstance(status, str) or status not in {"good", "suspect", "bad"}:
            continue
        if not isinstance(checked, str):
            continue
        try:
            stamp = pd.Timestamp(checked)
        except (TypeError, ValueError):
            continue
        if stamp is pd.NaT:
            continue
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        if stamp.to_pydatetime() < oldest:
            continue
        fresh[signal_id] = verdict
    verdicts: dict[str, dict[str, Any]] = {}
    for loop in loops:
        signals = loop_signal_ids(loop)
        known = [(signal, fresh[signal]) for signal in signals if signal in fresh]
        if not known:
            continue
        blocked = [
            t(
                "Signal quality, {signal}: {summary}",
                signal=signal,
                summary=str(verdict.get("message") or t("data not usable")),
            )
            for signal, verdict in known
            if verdict.get("status") == "bad" or verdict.get("apt") is False
        ]
        # Each role's verdict, for the diagram blocks that read Signal quality.
        roles = {
            role: {
                "status": fresh[signal].get("status"),
                "quality": fresh[signal].get("quality"),
                "message": fresh[signal].get("message"),
            }
            for role, signal in loop.signals.model_dump().items()
            if isinstance(signal, str) and signal in fresh
        }
        verdicts[loop.loop_id] = {
            "blocked": blocked,
            "covered": len(known) == len(signals),
            "roles": roles,
        }
    return verdicts
