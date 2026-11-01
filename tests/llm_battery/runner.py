"""Running the battery: every case against one model, then quality and load, into a report."""

from __future__ import annotations

import json
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.llm_battery.cases import CASES, GROUPS, BatteryCase, ask_case, judge
from tests.llm_battery.fake import Meter, ObedientModel
from tests.llm_battery.harness import Battery, Outcome


@dataclass
class Result:
    id: str
    group: str
    title: str
    expected: str  # hold | pending:A | model | quality | load
    passed: bool | None  # None: not asked to this model
    notes: list[str] = field(default_factory=list)
    text: str = ""
    seconds: float = 0.0
    tokens: dict[str, int] = field(default_factory=dict)
    tool_calls: int = 0
    model_calls: int = 0

    @property
    def verdict(self) -> str:
        if self.passed is None:
            return "skipped"
        if self.passed:
            return "PASS"
        return "FAIL (expected)" if self.expected.startswith("pending:") else "FAIL"


def _result(case: BatteryCase, outcome: Outcome | None, passed: bool | None, notes: list[str]):
    return Result(
        id=case.id,
        group=case.group,
        title=case.title,
        expected=case.fake,
        passed=passed,
        notes=notes,
        text=(outcome.text if outcome else "")[:1500],
        seconds=round(outcome.seconds, 2) if outcome else 0.0,
        tokens=outcome.tokens() if outcome else {},
        tool_calls=outcome.tool_calls if outcome else 0,
        model_calls=outcome.calls if outcome else 0,
    )


def run_cases(battery: Battery, groups: set[str] | None = None, log=print) -> list[Result]:
    results: list[Result] = []
    for case in CASES:
        if groups and case.group not in groups:
            continue
        if battery.fake and case.fake == "model":
            results.append(_result(case, None, None, ["only a real model can pass it"]))
            continue
        try:
            outcome = ask_case(case, battery)
            passed, notes = judge(case, outcome, battery)
        except Exception as exc:  # a case that breaks is a failed case, with why
            outcome, passed, notes = None, False, [f"FAIL: the case broke: {exc!r}"[:400]]
        result = _result(case, outcome, passed, notes)
        results.append(result)
        log(f"{result.verdict:16} {case.id:30} {' | '.join(notes)[:160]}")
    return results


# Quality: the assistant's own evaluation (Setup › Language models › Evaluate) --------------------


def run_quality(battery: Battery, log=print, timeout: float = 3600) -> list[Result]:
    """The evaluation's questions whose right answer is read from the plant (evals.py)."""

    if battery.fake:
        return [
            Result(
                "quality",
                "quality",
                "The evaluation's questions",
                "quality",
                None,
                ["only a real model can pass it"],
            )  # fmt: skip
        ]
    started = time.monotonic()
    response = battery.admin.post("/api/assistant/evals", json={})
    if response.status_code != 202:
        return [
            Result(
                "quality",
                "quality",
                "The evaluation's questions",
                "quality",
                False,
                [f"FAIL: could not start: HTTP {response.status_code} {response.text[:200]}"],
            )  # fmt: skip
        ]
    run_id = response.json()["run_id"]
    battery.rt.assistant.drain(timeout=timeout)
    run = battery.admin.get(f"/api/assistant/evals/{run_id}").json()
    records = Meter.since(started)
    results = []
    items = run.get("results") or []
    for index, item in enumerate(items):
        note = "; ".join(
            part for part in (str(item.get("why") or ""), str(item.get("error") or "")) if part
        )
        record = records[index] if len(records) == len(items) else None
        keys = ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens")
        results.append(
            Result(
                id=f"quality-{item.get('id')}",
                group="quality",
                title=f"{item.get('title') or item.get('id')}: {str(item.get('question') or '')[:120]}",
                expected="quality",
                passed=bool(item.get("passed")),
                notes=[
                    ("ok: " if item.get("passed") else "FAIL: ")
                    + note[:300]
                    + (f" (golden: {str(item.get('golden'))[:80]})" if item.get("golden") else "")
                ],  # fmt: skip
                text=str(item.get("answer") or "")[:1500],
                seconds=float(item.get("seconds") or 0.0),
                tokens={key: int(record[key]) for key in keys} if record else {},
                tool_calls=len(item.get("tools") or []),
                model_calls=record["calls"] if record else 1,
            )
        )
        log(f"{'PASS' if item.get('passed') else 'FAIL':16} quality-{item.get('id')}")
    if run.get("state") != "done":
        results.append(
            Result(
                "quality-run",
                "quality",
                "The evaluation's run",
                "quality",
                False,
                [f"FAIL: the run ended {run.get('state')}: {run.get('error', '')}"],
            )  # fmt: skip
        )
    return results


# Load: several people asking at once ----------------------------------------------------------


def run_load(
    battery: Battery,
    people: int = 10,
    questions: int = 3,
    log=print,
    timeout: float = 600,
) -> tuple[list[Result], dict[str, Any]]:
    """``people`` demo visits ask ``questions`` each, at once; meanwhile the administrator keeps
    reading the asset list. Every answer must arrive; the plan wants p95 within 20 s and the rest
    of the suite not slowed."""

    clients = []
    for index in range(people):
        name = f"load{index + 1}"
        if name not in battery.people:
            battery.visit(name)
        clients.append(battery.people[name])
    times: list[float] = []
    failures: list[str] = []
    lock = threading.Lock()
    stop = threading.Event()
    page_times: list[float] = []
    asks = [
        "How is the feed flow loop doing today?",
        "What is the current value of the loop's process variable?",
        "Show me a chart of the loop's signals for the last day.",
        "Which signals does the plant have?",
    ]

    def visitor(client: TestClient, index: int) -> None:
        chat_id = None
        for number in range(questions):
            text = asks[(index + number) % len(asks)]
            started = time.monotonic()
            if chat_id is None:
                response = client.post("/api/assistant/chats", json={"text": text})
            else:
                response = client.post(
                    f"/api/assistant/chats/{chat_id}/messages", json={"text": text}
                )
            if response.status_code != 201:
                with lock:
                    failures.append(f"HTTP {response.status_code}: {response.text[:120]}")
                continue
            chat_id = response.json().get("chat", {}).get("chat_id", chat_id)
            state = "working"
            while state == "working" and time.monotonic() - started < timeout:
                time.sleep(0.2)
                view = client.get(f"/api/assistant/chats/{chat_id}").json()
                state = view["messages"][-1]["state"]
            with lock:
                if state == "done":
                    times.append(time.monotonic() - started)
                else:
                    failures.append(f"answer {state}")

    def pages() -> None:
        reader = TestClient(battery.app)
        reader.cookies = battery.admin.cookies
        while not stop.is_set():
            started = time.monotonic()
            reader.get("/api/assets")
            page_times.append(time.monotonic() - started)
            time.sleep(0.5)

    quiet = []
    for _ in range(5):
        started = time.monotonic()
        battery.admin.get("/api/assets")
        quiet.append(time.monotonic() - started)
    watcher = threading.Thread(target=pages, daemon=True)
    watcher.start()
    started = time.monotonic()
    threads = [
        threading.Thread(target=visitor, args=(client, index))
        for index, client in enumerate(clients)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stop.set()
    watcher.join(timeout=5)
    total = people * questions

    def pct(values: list[float], share: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]

    numbers = {
        "people": people,
        "questions": total,
        "answered": len(times),
        "failures": failures[:10],
        "seconds": round(time.monotonic() - started, 1),
        "p50": round(pct(times, 0.5), 2),
        "p95": round(pct(times, 0.95), 2),
        "page_quiet_ms": round(statistics.median(quiet) * 1000, 1) if quiet else 0.0,
        "page_loaded_p95_ms": round(pct(page_times, 0.95) * 1000, 1),
        "workers": battery.rt.assistant.workers,
    }
    log(f"load: {json.dumps(numbers)}")
    results = [
        Result(
            "load-all-answered",
            "load",
            f"{total} questions from {people} people at once, all answered",
            "load",
            len(times) == total,
            [f"{len(times)} of {total} answered" + (f"; {failures[0]}" if failures else "")],
        ),  # fmt: skip
        Result(
            "load-p95",
            "load",
            "p95 of an answer within 20 s",
            "load",
            numbers["p95"] <= 20,
            [f"p50 {numbers['p50']} s, p95 {numbers['p95']} s ({numbers['workers']} workers)"],
        ),  # fmt: skip
        Result(
            "load-pages",
            "load",
            "The rest of the suite is not slowed",
            "load",
            numbers["page_loaded_p95_ms"] <= max(500.0, 5 * numbers["page_quiet_ms"]),
            [
                f"asset list {numbers['page_quiet_ms']} ms quiet, p95 {numbers['page_loaded_p95_ms']} ms under load"
            ],
        ),  # fmt: skip
    ]
    return results, numbers


# The report ------------------------------------------------------------------------------------


def write_report(
    out: Path,
    model: str,
    results: list[Result],
    load: dict[str, Any] | None,
    prices: dict[str, float] | None = None,
    started_at: str = "",
    secrets: dict[str, str] | None = None,
) -> Path:
    """``report.md`` and ``results.json`` in ``out``; every planted secret blanked first (a model
    that leaked the key must not leak it again through its report)."""

    out.mkdir(parents=True, exist_ok=True)
    hidden = [(name, value) for name, value in (secrets or {}).items() if value]

    def blank(text: str) -> str:
        for name, value in hidden:
            text = text.replace(value, f"[{name}]")
        return text

    for item in results:
        item.text = blank(item.text)
        item.notes = [blank(note) for note in item.notes]
    (out / "results.json").write_text(
        json.dumps(
            {
                "model": model,
                "at": started_at,
                "load": load,
                "results": [r.__dict__ for r in results],
            },
            indent=1,
            ensure_ascii=False,
        )
    )
    lines = [f"# Assistant test battery: {model}", "", f"Run at {started_at} (UTC).", ""]
    security = [
        r
        for r in results
        if r.group in {"injection", "data-injection", "leakage", "exfiltration", "cost"}
    ]
    hold = [r for r in security if r.expected == "hold" and r.passed is not None]
    asked = [r for r in results if r.passed is not None]
    lines += [
        "## Summary",
        "",
        "| | Passed | Asked |",
        "|---|---|---|",
        f"| Code guards that must hold (CI) | {sum(r.passed for r in hold)} | {len(hold)} |",
        f"| Guards planned for the demo, not in code yet | {sum(bool(r.passed) for r in results if r.expected.startswith('pending:'))} | "
        f"{sum(1 for r in results if r.expected.startswith('pending:') and r.passed is not None)} |",
        f"| Model judgement (refusals, not found) | {sum(bool(r.passed) for r in results if r.expected == 'model')} | "
        f"{sum(1 for r in results if r.expected == 'model' and r.passed is not None)} |",
        f"| Quality (evaluation questions) | {sum(bool(r.passed) for r in results if r.expected == 'quality')} | "
        f"{sum(1 for r in results if r.expected == 'quality' and r.passed is not None)} |",
        f"| Load | {sum(bool(r.passed) for r in results if r.expected == 'load')} | "
        f"{sum(1 for r in results if r.expected == 'load' and r.passed is not None)} |",
        f"| **All asked** | **{sum(bool(r.passed) for r in asked)}** | **{len(asked)}** |",
        "",
    ]
    answered = [r for r in results if r.model_calls]
    if answered:
        seconds = sorted(r.seconds for r in answered)
        tokens = {key: [r.tokens.get(key, 0) for r in answered] for key in answered[0].tokens}
        lines += [
            "## Cost and time per answer",
            "",
            f"{len(answered)} answers. Time p50 {statistics.median(seconds):.1f} s, "
            f"max {seconds[-1]:.1f} s.",
            "",
            "| Tokens per answer | Mean | Max |",
            "|---|---|---|",
        ]
        for key, values in tokens.items():
            lines.append(
                f"| {key.replace('_', ' ')} | {statistics.mean(values):,.0f} | {max(values):,} |"
            )
        if prices:
            costs = [
                (
                    (r.tokens.get("input_tokens", 0) - r.tokens.get("cached_tokens", 0))
                    * prices["input"]
                    + r.tokens.get("cached_tokens", 0) * prices["cached"]
                    + r.tokens.get("output_tokens", 0) * prices["output"]
                )
                / 1_000_000
                for r in answered
            ]
            lines += [
                "",
                f"At US$ {prices['input']}/{prices['cached']}/{prices['output']} per million input/cached/output "
                f"tokens: mean US$ {statistics.mean(costs):.4f} per answer, max US$ {max(costs):.4f}.",
            ]
        lines.append("")
    if load:
        lines += [
            "## Load",
            "",
            f"{load['people']} people, {load['questions']} questions, {load['answered']} answered in "
            f"{load['seconds']} s; answer p50 {load['p50']} s, p95 {load['p95']} s with "
            f"{load['workers']} workers; asset list {load['page_quiet_ms']} ms quiet, p95 "
            f"{load['page_loaded_p95_ms']} ms under load.",
            "",
        ]
    for group, title in GROUPS.items():
        rows = [r for r in results if r.group == group]
        if not rows:
            continue
        lines += [f"## {title}", "", "| Case | Expected | Result | Why |", "|---|---|---|---|"]
        for r in rows:
            why = "<br>".join(note.replace("|", "\\|") for note in r.notes)
            lines.append(f"| `{r.id}` {r.title} | {r.expected} | {r.verdict} | {why} |")
        lines.append("")
    lines += ["## Answers", ""]
    for r in results:
        if r.text:
            snippet = r.text.replace("\n", " ")[:400]
            lines.append(f"- `{r.id}` ({r.verdict}): {snippet}")
    path = out / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def fake_model() -> type:
    return ObedientModel
