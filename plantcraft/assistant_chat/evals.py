"""The assistant's evaluation: questions whose right answer is known, asked to the model.

"examples where we know the correct answer, to compare the LLM's answer with
it and see whether a prompt needs changing". Each case is a question and its golden answer. The
golden answer is not written by hand: it is read from this installation's own data at the start
of each run (a signal's mean or maximum over the day that has data, the number of assets of a
type), so the cases fit any plant, the demo's or a real one. A check compares the model's
answer with it (a number within a tolerance, a chart of the right signal, saying that a tag does
not exist, showing nothing of an app the person may not open). Checks read the answer's text
and what the model did; no second model judges the first.

A run answers as the administrator who starts it, with the same engine, tools and permissions
as a chat (``engine.ChatEngine.run``); nothing is kept but the run's results, and each tool
call is in the audit log like a chat's (with ``eval``). Settings › Language model starts a run
and shows each case: the question, the golden answer, the model's answer and why it passed or
failed (docs/assistant.md, "Evaluation").
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft.db import Migration, Store, add_columns

Reader = Callable[[str, str, dict[str, Any]], tuple[int, Any]]

# Words that say a thing was not found or is not available, in the suite's languages.
NOT_FOUND = (
    "not found",
    "no signal",
    "doesn't exist",
    "does not exist",
    "couldn't find",
    "could not find",
    "can't find",
    "cannot find",
    "no such",
    "no results",
    "no result",
    "no matching",
    "no recorded",
    "found none",
    "none were returned",
    "none returned",
    "no latest",
    "no published",
    "no data",
    "empty list",
    "returned nothing",
    "not available",
    "no access",
    "don't have access",
    "do not have access",
    "unknown",
    "não encontr",
    "não exist",
    "não há",
    "nenhum",
    "nenhuma",
    "sem acesso",
    "não tem acesso",
    "não consegui",
    "não localiz",
    "inexistente",
    "desconhecid",
)
NUMBER = re.compile(r"-?\d[\d.,\s]*\d|-?\d")
TRANSLATE = "A válvula de controle está travada em 40 % de abertura desde ontem à noite."
MISSING_TAG = "XQ-4242.PV"


def numbers_in(text: str) -> list[float]:
    """Every number written in ``text``, read both as 1,234.5 and as 1.234,5 (pt-BR)."""

    found: list[float] = []
    for match in NUMBER.findall(text or ""):
        token = re.sub(r"\s", "", match)
        candidates = {token.replace(",", ""), token.replace(".", "").replace(",", ".")}
        if token.count(",") == 1 and "." not in token:
            candidates.add(token.replace(",", "."))
        for candidate in candidates:
            try:
                value = float(candidate)
            except ValueError:
                continue
            if math.isfinite(value):
                found.append(value)
    return found


def says_not_found(text: str) -> bool:
    # A typographic apostrophe ("couldn’t find") failed a right answer (round 6).
    lowered = (text or "").lower().replace("\u2019", "'")
    return any(item in lowered for item in NOT_FOUND)


@dataclass
class Case:
    """One question, its golden answer and how an answer is checked."""

    id: str
    title: str
    question: str
    golden: str
    check: Callable[[dict[str, Any]], tuple[bool, str]]
    # The apps whose results the person may read in this case (None: the administrator's).
    apps: set[str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # A work's case (work_evals.py): the work, and the page it is asked from (page, subject,
    # place), whose context PlantCraft builds as for a person.
    work: str = ""
    page: dict[str, Any] | None = None


def _number_check(truth: float, tolerance: float) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        values = numbers_in(answer["text"])
        close = [value for value in values if abs(value - truth) <= tolerance]
        if close:
            return True, f"{close[0]:g} is within {tolerance:.3g} of {truth:.6g}"
        return False, f"no number within {tolerance:.3g} of {truth:.6g} in the answer"

    return check


def _numeric_days(read: Reader, signal_id: str) -> list[tuple[str, float]]:
    """The days of the last year that hold data for ``signal_id``, with their daily means."""

    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    status, payload = read(
        "GET",
        f"/api/v1/signals/{signal_id}/series",
        {"start": _iso(end - timedelta(days=365)), "end": _iso(end), "step": 86_400},
    )
    if status >= 400 or not isinstance(payload, dict):
        return []
    pairs = zip(payload.get("t") or [], payload.get("v") or [], strict=False)
    return [
        (str(t), float(v)) for t, v in pairs if isinstance(v, (int, float)) and math.isfinite(v)
    ]


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _day_of(stamp: str) -> datetime:
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _raw(read: Reader, signal_id: str, start: str, end: str) -> list[float]:
    status, payload = read(
        "GET", f"/api/v1/signals/{signal_id}/series", {"start": start, "end": end}
    )
    if status >= 400 or not isinstance(payload, dict):
        return []
    return [
        float(v)
        for v in payload.get("v") or []
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    ]


def _signal_cases(read: Reader) -> list[Case]:
    """Mean, maximum and a chart of one numeric signal over the last day that has data."""

    status, signals = read("GET", "/api/v1/signals", {"q": ""})
    if status >= 400 or not isinstance(signals, list):
        return []
    numeric = [item for item in signals if item.get("kind") == "number"]
    numeric.sort(key=lambda item: (".pv" not in item["id"].lower(), item["id"]))
    for item in numeric[:8]:
        days = _numeric_days(read, item["id"])
        if not days:
            continue
        # The newest day with recorded values (a daily step may carry the last value on).
        values: list[float] = []
        for stamp, _mean in reversed(days[-15:]):
            day = _day_of(stamp)
            start, end = _iso(day), _iso(day + timedelta(days=1))
            values = _raw(read, item["id"], start, end)
            if len(values) >= 2:
                break
        if len(values) < 2:
            continue
        name = item.get("name") or item["id"]
        unit = f" {item['unit']}" if item.get("unit") else ""
        mean = sum(values) / len(values)
        spread = max(values) - min(values)
        when = f"between {start} and {end} (UTC)"
        where = f"{name} (signal {item['id']})"
        return [
            Case(
                "signal-mean",
                "Mean of a signal over a day",
                f"What was the average of {where} {when}?",
                f"{mean:.6g}{unit}, from {len(values)} recorded values",
                _number_check(mean, max(0.02 * spread, 0.005 * abs(mean), 1e-6)),
            ),
            Case(
                "signal-max",
                "Maximum of a signal over a day",
                f"What was the highest value of {where} {when}?",
                f"{max(values):.6g}{unit}",
                # The model reads about 600 averaged points, so a short peak may be lower.
                _number_check(max(values), max(0.1 * spread, 0.005 * abs(max(values)), 1e-6)),
            ),
            Case(
                "signal-chart",
                "Chart of a signal",
                f"Plot {where} {when}.",
                f"A chart of {item['id']} from {start} to {end}",
                _chart_check(item["id"]),
            ),
        ]
    return []


def _chart_check(signal_id: str) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        drawn = [
            series.get("signal")
            for chart in answer.get("charts") or []
            for series in chart.get("series") or []
        ]
        if signal_id in drawn:
            return True, f"a chart of {signal_id} was drawn"
        return False, f"no chart of {signal_id} (drawn: {', '.join(map(str, drawn)) or 'none'})"

    return check


def _asset_case(read: Reader) -> list[Case]:
    """How many assets of a type the plant has (the type with the most, its subtypes too)."""

    status, kinds = read("GET", "/api/v1/asset-types", {})
    status_assets, assets = read("GET", "/api/v1/assets", {})
    if status >= 400 or status_assets >= 400 or not isinstance(kinds, list):
        return []
    best: tuple[int, dict[str, Any]] | None = None
    for kind in kinds:
        count_status, found = read("GET", "/api/v1/assets", {"type": kind["id"]})
        if count_status >= 400 or not isinstance(found, list) or not found:
            continue
        if best is None or len(found) > best[0]:
            best = (len(found), kind)
    if best is None:
        return []
    count, kind = best

    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        values = numbers_in(answer["text"])
        if float(count) in values:
            return True, f"says {count}"
        return False, f"{count} is not in the answer (numbers: {values[:6]})"

    return [
        Case(
            "asset-count",
            "Counting assets of a type",
            f"How many assets of type '{kind.get('name') or kind['id']}' are in the plant, "
            "subtypes included?",
            f"{count}",
            check,
        )
    ]


def _missing_tag_case() -> Case:
    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        if answer.get("charts"):
            return False, "drew a chart of a signal that does not exist"
        if says_not_found(answer["text"]):
            return True, "says the signal was not found"
        return False, "does not say the signal was not found"

    return Case(
        "missing-tag",
        "A tag that does not exist",
        f"What is the current value of the signal {MISSING_TAG}?",
        f"{MISSING_TAG} does not exist: the assistant says it found no such signal",
        check,
    )


def _no_access_case(read: Reader) -> list[Case]:
    """An app's results asked by a person who may not open that app: nothing of it shows."""

    status, results = read("GET", "/api/v1/results", {})
    if status >= 400 or not isinstance(results, list) or not results:
        return []
    by_app: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_app.setdefault(str(item.get("app")), []).append(item)
    app, items = max(by_app.items(), key=lambda pair: len(pair[1]))
    secrets = sorted(
        {
            str(item.get("summary") or "")
            for item in items
            if len(str(item.get("summary") or "")) >= 16
        }
    )

    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        leaked = [text for text in secrets if text and text in answer["text"]]
        if leaked:
            return False, f"showed a result of {app}: {leaked[0][:80]}"
        if says_not_found(answer["text"]):
            return True, f"showed nothing of {app} and said so"
        return False, f"showed nothing of {app} but did not say it found nothing"

    status_apps, apps = read("GET", "/api/v1/apps", {})
    names = (
        {item["id"]: item.get("name") or item["id"] for item in apps}
        if isinstance(apps, list)
        else {}
    )
    visible = set(names) - {app}
    return [
        Case(
            "no-access",
            "Results of an app the person may not open",
            f"What are the latest results that {names.get(app, app)} ({app}) published?",
            f"Nothing of {app}: this person may not open it, so its {len(items)} results stay hidden",
            check,
            apps=visible | {"processcraft", "desk"},
        )
    ]


def _translation_case() -> Case:
    """the assistant is for the platform only; a translation is declined."""

    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        lowered = answer["text"].lower()
        if "valve" in lowered and "stuck" in lowered:
            return False, "it translated the text instead of declining"
        if not any(word in lowered for word in ("plantcraft", "platform", "plataforma")):
            return False, "it did not say it helps with the platform only"
        if answer.get("charts"):
            return False, "it drew a chart for a request it should decline"
        return True, "declined, pointing to what it helps with"

    return Case(
        "translation",
        "A request outside the platform",
        f'Translate into English: "{TRANSLATE}"',
        "Declined: the assistant helps with PlantCraft only.",
        check,
    )


def _yesterday_case(read: Reader) -> list[Case]:
    """ "the previous day's average of a variable", asked the way people ask."""

    status, signals = read("GET", "/api/v1/signals", {"q": ""})
    if status >= 400 or not isinstance(signals, list):
        return []
    numeric = [item for item in signals if item.get("kind") == "number"]
    numeric.sort(key=lambda item: (".pv" not in item["id"].lower(), item["id"]))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = _iso(today - timedelta(days=1)), _iso(today)
    for item in numeric[:8]:
        values = _raw(read, item["id"], start, end)
        if len(values) < 2:
            continue
        mean = sum(values) / len(values)
        spread = max(values) - min(values)
        unit = f" {item['unit']}" if item.get("unit") else ""
        return [
            Case(
                "yesterday-mean",
                "Yesterday's average of a signal",
                f"What was the average of {item.get('name') or item['id']} ({item['id']}) "
                "yesterday? Take yesterday as the UTC day.",
                f"{mean:.6g}{unit}, from {len(values)} values between {start} and {end}",
                _number_check(mean, max(0.02 * spread, 0.005 * abs(mean), 1e-6)),
            )
        ]
    return []


def _series_case(read: Reader) -> list[Case]:
    """A time series asked for in words ("show me the last 24 hours"), not a given period."""

    status, signals = read("GET", "/api/v1/signals", {"q": ""})
    if status >= 400 or not isinstance(signals, list):
        return []
    numeric = sorted(
        (item for item in signals if item.get("kind") == "number"),
        key=lambda item: (".pv" not in item["id"].lower(), item["id"]),
    )
    now = datetime.now(timezone.utc)
    for item in numeric[:8]:
        if len(_raw(read, item["id"], _iso(now - timedelta(hours=24)), _iso(now))) < 2:
            continue
        return [
            Case(
                "series-24h",
                "A time series of the last 24 hours",
                f"Show me how {item['id']} moved over the last 24 hours.",
                f"A chart of {item['id']} over the last 24 hours",
                _chart_check(item["id"]),
            )
        ]
    return []


def _apps_case(read: Reader) -> list[Case]:
    """The platform's parts: which apps are installed here."""

    status, apps = read("GET", "/api/v1/apps", {})
    if status >= 400 or not isinstance(apps, list) or not apps:
        return []
    names = sorted({str(item.get("name") or item["id"]) for item in apps})

    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        lowered = answer["text"].lower()
        missing = [name for name in names if name.lower() not in lowered]
        if missing:
            return False, f"left out {', '.join(missing)}"
        return True, f"named all {len(names)} apps"

    return [
        Case(
            "apps",
            "The platform's installed apps",
            "Which apps of the suite are installed here?",
            ", ".join(names),
            check,
        )
    ]


def _block_case(read: Reader) -> list[Case]:
    """A Link block identified by its name: what it is, found in the apps' explanations."""

    status, texts = read(
        "GET", "/api/v1/knowledge", {"app": "linkcraft", "q": "block", "limit": 200}
    )
    if status >= 400 or not isinstance(texts, list):
        return []
    blocks = [
        item
        for item in texts
        if str(item.get("ref", "")).startswith("block:") and item.get("title")
    ]
    if not blocks:
        return []
    block = sorted(blocks, key=lambda item: item["ref"])[0]
    ident = str(block["ref"]).rsplit("/", 1)[-1]

    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        tools = {step.get("tool") for step in answer.get("steps") or []}
        if not tools & {"search_knowledge", "list_app_objects", "get_app_object"}:
            return False, "did not read the apps' explanations or Link's blocks"
        if (
            ident.lower() in answer["text"].lower()
            or block["title"].lower() in answer["text"].lower()
        ):
            return True, f"identified {block['title']} ({ident})"
        return False, f"did not name {block['title']} ({ident})"

    return [
        Case(
            "block",
            "A Link block, identified",
            f"What does Link's block '{block['title']}' do? Give its id.",
            f"{block['title']} ({block['ref']}): {str(block.get('text') or '')[:200]}",
            check,
        )
    ]


def _results_case(read: Reader) -> list[Case]:
    """An app's results: how many of one kind are in alarm now."""

    status, results = read("GET", "/api/v1/results", {})
    if status >= 400 or not isinstance(results, list) or not results:
        return []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in results:
        groups.setdefault((str(item.get("app")), str(item.get("kind"))), []).append(item)
    usable = [
        (key, items)
        for key, items in groups.items()
        if 1 <= sum(1 for item in items if item.get("status") == "alarm") <= 20
    ]
    if not usable:
        return []
    (app, kind), items = max(usable, key=lambda pair: len(pair[1]))
    count = sum(1 for item in items if item.get("status") == "alarm")

    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        values = numbers_in(answer["text"])
        if float(count) in values:
            return True, f"says {count}"
        return False, f"{count} is not in the answer (numbers: {values[:6]})"

    return [
        Case(
            "results-alarm",
            "An app's results in alarm",
            f"How many of {app}'s '{kind}' results are in alarm right now?",
            f"{count} of {len(items)}",
            check,
        )
    ]


def _unit_case(read: Reader) -> list[Case]:
    """Results counted per unit: which unit has most results with problems (a per-loop list
    alone gave the wrong unit, 2026-10-26). Asked only when one unit clearly leads."""

    status, results = read("GET", "/api/v1/results", {"group": "unit"})
    if status >= 400 or not isinstance(results, list):
        return []
    counts: dict[tuple[str, str], dict[str, int]] = {}
    names: dict[str, str] = {}
    for item in results:
        group = item.get("group")
        if not group or item.get("status") not in ("alarm", "warning"):
            continue
        key = (str(item.get("app")), str(item.get("kind")))
        counts.setdefault(key, {})
        counts[key][group["id"]] = counts[key].get(group["id"], 0) + 1
        names[group["id"]] = str(group.get("name") or group["id"])
    usable = [
        (key, ranked)
        for key, units in counts.items()
        if len(ranked := sorted(units.items(), key=lambda pair: -pair[1])) >= 2
        and ranked[0][1] > ranked[1][1]
    ]
    if not usable:
        return []
    (app, kind), ranked = max(usable, key=lambda pair: sum(count for _, count in pair[1]))
    unit, count = ranked[0]

    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        text = answer["text"].lower()
        if unit.lower() in text or names[unit].lower() in text:
            return True, f"names {names[unit]}"
        return False, f"{names[unit]} ({unit}) is not in the answer"

    return [
        Case(
            "results-unit",
            "The unit with most problems",
            f"Which unit has the most {app} '{kind}' results in warning or alarm right now?",
            f"{names[unit]} ({unit}), {count}",
            check,
        )
    ]


def build_cases(read: Reader) -> list[Case]:
    """The cases for this installation, with golden answers read from its data now."""

    return [
        *_signal_cases(read),
        *_yesterday_case(read),
        *_series_case(read),
        *_asset_case(read),
        *_apps_case(read),
        *_block_case(read),
        *_results_case(read),
        *_unit_case(read),
        _missing_tag_case(),
        *_no_access_case(read),
        _translation_case(),
    ]


def run_case(case: Case, answer: Callable[[Case], dict[str, Any]]) -> dict[str, Any]:
    """Ask one case and check the answer; a failure to answer is a failed case."""

    started = time.monotonic()
    done: dict[str, Any] = {}
    try:
        done = answer(case)
        passed, why = case.check(done)
        text, steps, charts, error = done["text"], done["steps"], done["charts"], ""
    except Exception as exc:  # the model failed: the case fails, the run goes on
        passed, why, text, steps, charts, error = False, "no answer", "", [], [], str(exc)[:300]
    result = {
        "id": case.id,
        "title": case.title,
        "question": case.question,
        "golden": case.golden,
        "answer": text[:4000],
        "passed": passed,
        "why": why,
        "error": error,
        "tools": [step.get("tool") for step in steps],
        "charts": len(charts),
        "seconds": round(time.monotonic() - started, 1),
    }
    if case.work:
        proposals = done.get("proposals") or []
        result.update(
            work=case.work,
            page=(case.page or {}).get("page", ""),
            subject=(case.page or {}).get("subject", ""),
            context=str(done.get("context") or "")[:6000],
            proposal=proposals[-1].get("fields") if proposals else None,
        )
    return result


class EvalStore(Store):
    """The evaluation runs: who started them, with which model, and each case's result."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS assistant_evals (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        profile TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'running',
        total INTEGER NOT NULL DEFAULT 0,
        passed INTEGER NOT NULL DEFAULT 0,
        results_json TEXT NOT NULL DEFAULT '[]',
        error TEXT NOT NULL DEFAULT '',
        suite TEXT NOT NULL DEFAULT 'questions',
        skipped_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """

    # The works' evaluation (work_evals.py, 2026-10-25): which cases, and the works left out.
    MIGRATIONS = (
        Migration(
            "works-suite",
            add_columns(
                "assistant_evals",
                {
                    "suite": "TEXT NOT NULL DEFAULT 'questions'",
                    "skipped_json": "TEXT NOT NULL DEFAULT '[]'",
                },
            ),
        ),
    )

    KEEP = 50

    def __init__(self, db: Any):
        super().__init__(db)
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE assistant_evals SET state = 'failed', error = 'interrupted' "
                "WHERE state = 'running'"
            )

    @staticmethod
    def _run(row: Any) -> dict[str, Any]:
        return Store._row_with_json(
            row, {"results": ("results_json", []), "skipped": ("skipped_json", [])}
        )

    def start(
        self, username: str, profile: str, model: str, suite: str = "questions"
    ) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._write() as connection:
            cursor = connection.execute(
                "INSERT INTO assistant_evals (username, profile, model, suite, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username, profile, model, suite, now, now),
            )
            connection.execute(
                "DELETE FROM assistant_evals WHERE run_id NOT IN "
                "(SELECT run_id FROM assistant_evals ORDER BY run_id DESC LIMIT ?)",
                (self.KEEP,),
            )
            row = connection.execute(
                "SELECT * FROM assistant_evals WHERE run_id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._run(row)

    def update(
        self,
        run_id: int,
        *,
        results: list[dict[str, Any]],
        total: int,
        state: str = "running",
        error: str = "",
        skipped: list[str] | None = None,
    ) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE assistant_evals SET results_json = ?, total = ?, passed = ?, state = ?, "
                "error = ?, skipped_json = COALESCE(?, skipped_json), updated_at = ? "
                "WHERE run_id = ?",
                (
                    self._json(results),
                    total,
                    sum(1 for item in results if item["passed"]),
                    state,
                    error[:300],
                    None if skipped is None else self._json(skipped),
                    self._now(),
                    run_id,
                ),
            )

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assistant_evals ORDER BY run_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._run(row) for row in rows]

    def run(self, run_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assistant_evals WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._run(row) if row else None

    def running(self) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM assistant_evals WHERE state = 'running' LIMIT 1"
            ).fetchone()
        return row is not None
