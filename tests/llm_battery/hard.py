"""Hard questions: the analyses a plant engineer asks, to find where a cheap model stops being enough.

The demo's battery asks short questions about a one-loop plant. These ask, as an administrator
outside the demo, what takes several reads and some reasoning: rank nine loops, recognise a
sticky valve from its data, estimate an oscillation's period, time a manual period or a level
excursion, read a unit's long operating notes, and use a fact given early in a long chat.

The plant is written here (``write_plant``): three units, nine loops, 48 hours at one-minute
steps ending at the current hour, each loop with a behaviour put in on purpose (a sticky valve,
an oscillation, a drift, a manual period, a cyclic disturbance, a level excursion, healthy ones).
Every golden answer is computed from the history PlantCraft serves (the same routes the
assistant's tools read), so a check never trusts the generator's intentions, and every check is
code: the loop's id, a number within a tolerance, a time within some minutes.

Asked to real models only (``model``); CI checks the plant and the checks themselves
(``tests/test_llm_battery.py``).
"""

from __future__ import annotations

import json
import math
import random
import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STEP = 60  # seconds
HOURS = 48
UNITS = {
    "U-100": "Feed unit",
    "U-200": "Reactor unit",
    "U-300": "Separation unit",
}
# loop -> (unit, name, setpoint, engineering unit, behaviour)
LOOPS: dict[str, tuple[str, str, float, str, str]] = {
    "FIC-101": ("U-100", "Feed flow", 50.0, "t/h", "healthy"),
    "FIC-102": ("U-100", "Recycle flow", 30.0, "t/h", "stiction"),
    "LIC-103": ("U-100", "Feed drum level", 50.0, "%", "level"),
    "PIC-201": ("U-200", "Reactor pressure", 12.0, "bar", "oscillation"),
    "TIC-202": ("U-200", "Reactor temperature", 180.0, "degC", "drift"),
    "FIC-203": ("U-200", "Coolant flow", 40.0, "t/h", "manual"),
    "TIC-301": ("U-300", "Column top temperature", 95.0, "degC", "cyclic"),
    "LIC-302": ("U-300", "Column bottom level", 60.0, "%", "excursion"),
    "FIC-303": ("U-300", "Product flow", 80.0, "t/h", "healthy"),
}
LEVEL_LOOPS = [loop for loop in LOOPS if loop.startswith("LIC")]
OSCILLATION_MINUTES = 5.0
MANUAL = (30 * 60, 33 * 60)  # minutes after the start: FIC-203 out of automatic
EXCURSION = 40 * 60  # minute after the start when LIC-302 starts to rise
CHAT_LIMIT = 75.0  # the temporary LIC-302 limit given early in the long chat
STARTUP_FEED = "37.5 t/h"
BYPASS_APPROVER = "process safety engineer"


def column(loop: str, role: str) -> str:
    return f"{loop}.{role.upper()}"


def signal(loop: str, role: str) -> str:
    return f"scenario:{column(loop, role)}"


def window_end(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _series(behaviour: str, sp: float, minutes: int, rng: random.Random) -> dict[str, list]:
    pv, op, mode = [], [], []
    level = 0.0
    for m in range(minutes):
        noise = rng.gauss(0, 0.004 * sp)
        out, state = 45.0 + rng.gauss(0, 0.3), "auto"
        value = sp + noise
        if behaviour == "stiction":
            # The output ramps like a sawtooth; the valve jumps, so the PV moves in steps.
            phase = (m % 20) / 20
            out = 40.0 + 6.0 * phase
            value = sp + (1.5 if m % 20 >= 10 else -1.5) + noise
        elif behaviour == "level":
            level = 0.97 * level + rng.gauss(0, 0.25)
            value = sp + level
        elif behaviour == "oscillation":
            value = sp + 0.7 * math.sin(2 * math.pi * m / OSCILLATION_MINUTES) + noise
            out = 50.0 + 4.0 * math.sin(2 * math.pi * m / OSCILLATION_MINUTES - 1.2)
        elif behaviour == "drift":
            if m >= minutes // 2:
                value += 6.0 * (m - minutes // 2) / (minutes // 2)
            out = 55.0 + (value - sp) * 2
        elif behaviour == "manual":
            if MANUAL[0] <= m < MANUAL[1]:
                state, out = "manual", 38.0
                value = sp + 2.0 + rng.gauss(0, 0.2)
        elif behaviour == "cyclic":
            value = sp + 4.0 * math.sin(2 * math.pi * m / 60) + noise
        elif behaviour == "excursion":
            value = sp + rng.gauss(0, 0.5)
            k = m - EXCURSION
            if 0 <= k < 60:
                # Up to 84 % in 30 minutes, back in 30.
                value = sp + 24.0 * (1 - abs(k - 30) / 30)
        pv.append(round(value, 4))
        op.append(round(out, 3))
        mode.append(state)
    return {"pv": pv, "sp": [sp] * minutes, "op": op, "mode": mode}


NOTES_FILLER = [
    "Shift handover follows the unit's checklist; the outgoing operator walks the panel with the "
    "incoming one and both sign the log.",
    "Sample points are flushed for two minutes before a lab sample is taken; the sample bottle is "
    "labelled with the time in the plant's zone.",
    "Rotating equipment rounds happen every four hours: listen for noise, check seal pots and "
    "note vibration readings on the round sheet.",
    "Instrument air pressure is watched on the utility screen; a drop below the low alarm is "
    "reported to the utilities desk.",
    "Housekeeping: drains closed, hoses coiled, no tools left on platforms after work permits "
    "are closed.",
    "Any change to a controller's tuning is recorded in the tuning log with the old and the new "
    "values and the reason.",
]


def operating_notes(rng: random.Random) -> str:
    """About 8,000 characters of a unit's operating notes, two facts buried past the middle."""

    paragraphs = []
    for index in range(40):
        paragraphs.append(f"{index + 1}. {rng.choice(NOTES_FILLER)}")
    paragraphs.insert(
        27,
        f"28a. Startup: the column feed is limited to {STARTUP_FEED} until the bottom level has "
        "been stable for one hour; then it may be raised in steps of 5 t/h.",
    )
    paragraphs.insert(
        33,
        "33a. The LIC-302 high-level alarm may only be bypassed with written approval from the "
        f"area's {BYPASS_APPROVER}, recorded in the bypass register.",
    )
    return "Separation unit operating notes.\n" + "\n".join(paragraphs)


def write_plant(folder: Path, now: datetime | None = None) -> Path:
    """The plant's CSV and scenario in ``folder``; returns the scenario's path."""

    folder.mkdir(parents=True, exist_ok=True)
    end = window_end(now)
    start = end - timedelta(hours=HOURS)
    minutes = HOURS * 60
    rng = random.Random(20261101)
    data = {loop: _series(spec[4], spec[2], minutes, rng) for loop, spec in LOOPS.items()}
    header = ["timestamp"] + [column(loop, role) for loop in LOOPS for role in data[loop]]
    lines = [",".join(header)]
    for m in range(minutes):
        stamp = (start + timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S")
        row = [stamp] + [str(data[loop][role][m]) for loop in LOOPS for role in data[loop]]
        lines.append(",".join(row))
    csv = folder / "hard-plant.csv"
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    scenario = {
        "name": "hard_questions_plant",
        "display_name": "Test plant — three units",
        "description": "A plant written by the battery for its hard questions.",
        "source": {"type": "csv", "path": str(csv), "timezone": "UTC"},
        "storage": {"sqlite_path": str(folder / "workspace.sqlite3")},
        "analysis": {"interval_minutes": 10, "resample_seconds": 60},
        "loops": [
            {
                "loop_id": loop,
                "name": name,
                "area": f"{UNITS[unit]} area",
                "service": name,
                "unit": unit,
                "signals": {role: column(loop, role) for role in ("pv", "sp", "op", "mode")},
                "metadata": {"engineering_unit": eng},
            }
            for loop, (unit, name, _sp, eng, _behaviour) in LOOPS.items()
        ],
    }
    path = folder / "hard-plant.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    return path


# Reading what PlantCraft serves -------------------------------------------------------------

Reader = Callable[[str, str, dict[str, Any]], tuple[int, Any]]


@dataclass
class Window:
    start: datetime
    end: datetime

    @property
    def mid(self) -> datetime:
        return self.start + (self.end - self.start) / 2

    def text(self, start: datetime | None = None, end: datetime | None = None) -> str:
        return f"between {_iso(start or self.start)} and {_iso(end or self.end)} (UTC)"


def raw(read: Reader, signal_id: str, start: datetime, end: datetime) -> list[tuple[datetime, Any]]:
    """Every recorded value of a signal in a window, as PlantCraft serves it."""

    status, payload = read(
        "GET", f"/api/v1/signals/{signal_id}/series", {"start": _iso(start), "end": _iso(end)}
    )
    if status >= 400 or not isinstance(payload, dict):
        raise RuntimeError(f"{signal_id}: HTTP {status}")
    out = []
    for t, v in zip(payload.get("t") or [], payload.get("v") or [], strict=False):
        moment = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        out.append((moment.astimezone(timezone.utc), v))
    if not out:
        raise RuntimeError(f"{signal_id}: no history served")
    return out


def numbers(read: Reader, signal_id: str, start: datetime, end: datetime) -> list[float]:
    return [
        float(v)
        for _, v in raw(read, signal_id, start, end)
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]


def errors(read: Reader, loop: str, start: datetime, end: datetime) -> list[float]:
    pv = numbers(read, signal(loop, "pv"), start, end)
    sp = numbers(read, signal(loop, "sp"), start, end)
    return [a - b for a, b in zip(pv, sp, strict=False)]


def relative_error(read: Reader, loop: str, start: datetime, end: datetime) -> float:
    """Mean |PV - SP| in percent of the mean setpoint."""

    sp = statistics.mean(numbers(read, signal(loop, "sp"), start, end))
    return 100 * statistics.mean(abs(e) for e in errors(read, loop, start, end)) / abs(sp)


def runs_where(
    points: list[tuple[datetime, Any]], test: Callable[[Any], bool]
) -> list[tuple[datetime, float]]:
    """Each run of consecutive points passing ``test``: its start and its length in minutes."""

    found, begun, last = [], None, None
    for moment, value in points:
        if test(value):
            begun = begun or moment
            last = moment
        elif begun is not None:
            found.append((begun, (last - begun).total_seconds() / 60 + STEP / 60))
            begun = None
    if begun is not None:
        found.append((begun, (last - begun).total_seconds() / 60 + STEP / 60))
    return found


# Checks on the answer's text ------------------------------------------------------------------

AnswerCheck = Callable[[str], tuple[bool, str]]
# A number as an answer writes it: "5.0", "5,0", "-1.2"; the 102 of "FIC-102" is not negative,
# and "FIC-102, 5.00 %" is two numbers (evals.numbers_in would join them).
NUMBER = re.compile(r"(?<![\w.,])(-?)(\d+(?:[.,]\d+)?)")


# Dates and clock times are not quantities: "04:26" must not pass for 4 minutes.
STAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?Z?)?|\b\d{1,2}[:h]\d{2}(?::\d{2})?\b"
)


def numbers_in(text: str) -> list[float]:
    text = STAMP.sub(" ", text)
    return [float(sign + digits.replace(",", ".")) for sign, digits in NUMBER.findall(text)]


LOOP_ID = re.compile(r"\b[FLPT]IC-\d{3}\b")
CLOCK = re.compile(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b")


def names(loop: str, others_at_most: int | None = None) -> AnswerCheck:
    def check(text: str) -> tuple[bool, str]:
        if loop not in text:
            return False, f"{loop} is not in the answer"
        others = sorted(set(LOOP_ID.findall(text)) - {loop})
        if others_at_most is not None and len(others) > others_at_most:
            return False, f"names {loop} but also {', '.join(others)}"
        return True, f"names {loop}"

    return check


def number_near(truth: float, tolerance: float, what: str = "") -> AnswerCheck:
    def check(text: str) -> tuple[bool, str]:
        values = numbers_in(text)
        close = [v for v in values if abs(v - truth) <= tolerance]
        if close:
            return True, f"{what}{close[0]:g} within {tolerance:g} of {truth:.4g}"
        return False, f"{what}no number within {tolerance:g} of {truth:.4g} (saw {values[:8]})"

    return check


def clock_near(moment: datetime, minutes: float) -> AnswerCheck:
    def check(text: str) -> tuple[bool, str]:
        target = moment.hour * 60 + moment.minute
        seen = [int(h) * 60 + int(m) for h, m in CLOCK.findall(text)]
        for value in seen:
            if min(abs(value - target), 1440 - abs(value - target)) <= minutes:
                return True, f"a time within {minutes:g} min of {moment:%H:%M} UTC"
        return False, f"no time within {minutes:g} min of {moment:%H:%M} UTC"

    return check


def contains(*words: str) -> AnswerCheck:
    def check(text: str) -> tuple[bool, str]:
        lowered = text.lower()
        missing = [w for w in words if w.lower() not in lowered]
        if missing:
            return False, f"missing {', '.join(missing)}"
        return True, f"says {', '.join(words)}"

    return check


def at_most_loops(count: int) -> AnswerCheck:
    """An answer that lists every loop has not chosen one (2026-11-01: luna listed all nine
    loops of each unit, saying it could not tell, and passed on names alone)."""

    def check(text: str) -> tuple[bool, str]:
        found = sorted(set(LOOP_ID.findall(text)))
        if len(found) > count:
            return False, f"lists {len(found)} loops instead of choosing"
        return True, f"names {len(found)} loops"

    return check


def in_order(loops: list[str]) -> AnswerCheck:
    def check(text: str) -> tuple[bool, str]:
        places = [text.find(loop) for loop in loops]
        if -1 in places:
            return False, f"missing {loops[places.index(-1)]}"
        if places != sorted(places):
            return False, f"not in the order {' > '.join(loops)}"
        return True, f"ranks {' > '.join(loops)}"

    return check


@dataclass
class HardCase:
    id: str
    title: str
    question: str
    golden: str
    checks: list[AnswerCheck]
    # A chat to ask in: earlier turns (role, text) written before the question.
    history: list[tuple[str, str]] = field(default_factory=list)

    def judge(self, text: str) -> tuple[bool, list[str]]:
        notes, passed = [], True
        for check in self.checks:
            ok, why = check(text)
            passed &= ok
            notes.append(("ok: " if ok else "FAIL: ") + why)
        return passed, notes


def long_chat(rng: random.Random) -> list[tuple[str, str]]:
    """Sixteen turns of shift talk (about 20,000 characters); the LIC-302 limit in the second."""

    turns: list[tuple[str, str]] = [
        ("user", "Good morning. I'm taking over the separation unit for this campaign."),
        (
            "assistant",
            "Good morning. Note for this campaign: the process engineer set a temporary "
            f"operating limit of {CHAT_LIMIT:g} % on LIC-302 (column bottom level); above it, "
            "the shift must reduce the feed.",
        ),
    ]
    topics = [
        "the feed pump's vibration readings",
        "the reboiler's steam valve",
        "the lab's last sample results",
        "the reflux drum's level trend",
        "the cooling water temperature",
        "a permit for the bottoms pump",
        "the flare's pilot",
    ]
    while len(turns) < 32:
        topic = rng.choice(topics)
        turns.append(("user", f"Can you summarise what we know about {topic}? " * 3))
        body = " ".join(rng.choice(NOTES_FILLER) for _ in range(7))
        turns.append(("assistant", f"About {topic}: {body}"))
    return turns


def build_cases(read: Reader, end: datetime | None = None) -> list[HardCase]:
    """The hard questions with golden answers read from the plant now."""

    end = end or window_end()
    w = Window(end - timedelta(hours=HOURS), end)
    whole, second = w.text(), w.text(w.mid)
    cases: list[HardCase] = []

    # The first 12 hours: short enough that one read of all nine loops' PV and setpoint keeps a
    # step under a minute (an oscillation of a few minutes averaged away would reorder them).
    first = w.start + timedelta(hours=12)
    early = w.text(w.start, first)
    ranked = sorted(
        LOOPS, key=lambda loop: relative_error(read, loop, w.start, first), reverse=True
    )
    top = relative_error(read, ranked[0], w.start, first)
    cases.append(
        HardCase(
            "hard-largest-error",
            "The loop with the largest error, and its value",
            f"Of all the plant's control loops, which had the largest mean absolute difference "
            f"between its PV and its setpoint, in percent of the setpoint, {early}? "
            "Give the loop and that value.",
            f"{ranked[0]}, {top:.2f} %",
            [names(ranked[0]), number_near(top, max(0.15 * top, 0.2), "value: ")],
        )
    )
    cases.append(
        HardCase(
            "hard-rank-three",
            "Rank the nine loops, top three",
            f"Rank the plant's control loops by mean absolute PV minus setpoint error in percent "
            f"of the setpoint, {early}. List the three worst, worst first.",
            " > ".join(ranked[:3]),
            [in_order(ranked[:3])],
        )
    )
    cases.append(
        HardCase(
            "hard-stiction",
            "Recognise a sticky valve from its data",
            f"One loop shows the classic sign of a sticky control valve {whole}: its controller "
            "output ramps like a sawtooth while its PV jumps between two levels. Which loop is "
            "it? Decide from the data, not from the names.",
            "FIC-102",
            [names("FIC-102", others_at_most=2)],
        )
    )
    start = w.end - timedelta(hours=2)
    cases.append(
        HardCase(
            "hard-oscillation-period",
            "Estimate an oscillation's period",
            f"PIC-201 oscillates. From its PV {w.text(start)}, estimate the period of the "
            "oscillation in minutes.",
            f"{OSCILLATION_MINUTES:g} minutes",
            [number_near(OSCILLATION_MINUTES, 1.0, "period: ")],
        )
    )
    manual = runs_where(
        raw(read, signal("FIC-203", "mode"), w.start, w.end),
        lambda v: str(v).lower() != "auto",
    )
    if manual:
        began, minutes = max(manual, key=lambda item: item[1])
        cases.append(
            HardCase(
                "hard-manual-period",
                "Time a period out of automatic",
                f"How many minutes was FIC-203 out of automatic {whole}, and at what time (UTC) "
                "did that start?",
                f"{minutes:.0f} min from {began:%H:%M} UTC",
                [number_near(minutes, 10, "minutes: "), clock_near(began, 10)],
            )
        )
    by_unit = {}
    for unit in UNITS:
        mine = [loop for loop in LOOPS if LOOPS[loop][0] == unit]
        by_unit[unit] = max(
            mine, key=lambda loop: statistics.pstdev(errors(read, loop, w.start, w.end))
        )
    cases.append(
        HardCase(
            "hard-per-unit",
            "The most variable loop of each unit",
            f"For each of the plant's three units, name the loop whose PV minus setpoint has the "
            f"largest standard deviation {whole}.",
            ", ".join(f"{u}: {loop}" for u, loop in by_unit.items()),
            [*(names(loop) for loop in by_unit.values()), at_most_loops(5)],
        )
    )
    level = raw(read, signal("LIC-302", "pv"), w.start, w.end)
    above = runs_where(level, lambda v: isinstance(v, (int, float)) and v > 80)
    if above:
        began, minutes = max(above, key=lambda item: item[1])
        cases.append(
            HardCase(
                "hard-level-excursion",
                "Find and time a level excursion",
                f"Did LIC-302 go above 80 % {whole}? If it did, when did it start (UTC) and for "
                "how many minutes did it stay above 80 %?",
                f"yes, from {began:%H:%M} UTC for {minutes:.0f} min",
                [clock_near(began, 10), number_near(minutes, 5, "minutes: ")],
            )
        )
    gap = errors(read, "TIC-202", w.end - timedelta(minutes=10), w.end)
    final_gap = statistics.mean(gap) if gap else 6.0
    cases.append(
        HardCase(
            "hard-drift",
            "Find the loop that drifted, and by how much",
            f"Which temperature loop moved steadily away from its setpoint {second}, and how far "
            "was its PV from the setpoint at the end of that period?",
            f"TIC-202, {final_gap:.1f}",
            [names("TIC-202", others_at_most=1), number_near(final_gap, 1.0, "gap: ")],
        )
    )
    mean_levels = statistics.mean(
        statistics.mean(numbers(read, signal(loop, "pv"), w.mid, w.end)) for loop in LEVEL_LOOPS
    )
    cases.append(
        HardCase(
            "hard-level-average",
            "One number from three loops",
            f"What was the average PV of the plant's level loops taken together {second}? Give "
            "one number: the mean of their means.",
            f"{mean_levels:.2f} %",
            [number_near(mean_levels, max(0.01 * mean_levels, 0.3), "mean: ")],
        )
    )
    cases.append(
        HardCase(
            "hard-long-notes",
            "Two facts buried in a unit's long notes",
            "Read the separation unit's (U-300) operating notes. What is the column feed limit "
            "during startup, and who must approve bypassing the LIC-302 high-level alarm?",
            f"{STARTUP_FEED}; the area's {BYPASS_APPROVER}",
            [number_near(37.5, 0.01, "limit: "), contains(BYPASS_APPROVER)],
        )
    )
    over = runs_where(level, lambda v: isinstance(v, (int, float)) and v > CHAT_LIMIT)
    total = sum(minutes for _, minutes in over)
    cases.append(
        HardCase(
            "hard-long-chat",
            "Use a fact from early in a long chat",
            f"Using the temporary LIC-302 limit we noted at the start of this chat, how many "
            f"minutes in total was LIC-302 above that limit {whole}?",
            f"{total:.0f} min above {CHAT_LIMIT:g} %",
            [number_near(total, 6, "minutes: ")],
            history=long_chat(random.Random(7)),
        )
    )
    return cases


def plant_notes(battery: Any) -> None:
    """The separation unit's operating notes, as a text an app published about U-300 (the
    platform's knowledge, which the assistant searches and reads; 600 characters is an asset
    description's limit, too short for notes)."""

    units = [
        item
        for item in battery.rt.workspace.assets.list()
        if item["kind"] == "unit" and "300" in (item.get("name") or item["asset_id"])
    ]
    if not units:
        raise RuntimeError("no U-300 unit in the plant")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    battery.rt.workspace.knowledge.put(
        [
            {
                "app": "linkcraft",
                "ref": "note:linkcraft/u-300-operating-notes",
                "kind": "note",
                "title": "Separation unit (U-300) operating notes",
                "text": operating_notes(random.Random(3)),
                "subjects": [f"asset:{units[0]['asset_id']}"],
            }
        ],
        now=now,
        cutoff="2000-01-01T00:00:00+00:00",
    )


def ask(battery: Any, case: HardCase, timeout: float = 900) -> Any:
    """Ask a hard case as the administrator, in a chat holding its history if it has one."""

    if not case.history:
        return battery.ask(case.question, person="admin", timeout=timeout)
    store = battery.rt.assistant.store
    chat = store.create("admin", case.title, kept=True)
    for role, text in case.history:
        store.add(chat["chat_id"], role, text)
    return battery.ask(case.question, person="admin", chat_id=chat["chat_id"], timeout=timeout)
