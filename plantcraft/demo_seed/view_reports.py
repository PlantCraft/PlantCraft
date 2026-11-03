"""View's reports: notebooks of Markdown cells over one period, sent as PDF on a schedule."""

from __future__ import annotations

from typing import Any

from .base import STICTION_LOOPS, Http, log
from .view import INSTRUMENTATION, _folders, _kpi, _scatter, _trend

# View's reports (2026-10-25): a document over one period, sent as PDF on a schedule; since
# 2026-10-26 a notebook of Markdown cells whose headings make its sections ---------------------


def _text(section_id: str, title: str, text: str = "", level: int = 1) -> dict[str, Any]:
    """A Markdown cell: its heading (``#`` level), then its text."""

    heading = f"{'#' * level} {title}" if title else ""
    return {"section_id": section_id, "kind": "text", "text": f"{heading}\n\n{text}".strip()}


def _card(section_id: str, card: dict[str, Any], width: str = "full") -> dict[str, Any]:
    return {"section_id": section_id, "kind": "card", "card": card, "width": width}


def _events(
    section_id: str, title: str, kinds: list[str], limit: int = 20, width: str = "full"
) -> dict[str, Any]:
    events = {"kinds": kinds, "limit": limit}
    return {
        "section_id": section_id,
        "kind": "events",
        "title": title,
        "events": events,
        "width": width,
    }


def _pvs(card_id: str, title: str, loops: list[str], kind: str = "stat") -> dict[str, Any]:
    """Each loop's PV over the period: one tile (or one table row) per loop."""

    return {
        "card_id": card_id,
        "title": title,
        "kind": kind,
        "items": [{"asset_id": loop, "role": "pv", "label": loop} for loop in loops],
        "agg": "mean",
        "window": "24h",
        "width": 12,
        "height": 1 if kind == "stat" else 3,
        "options": {"columns": ["mean", "min", "max", "unit", "state"]} if kind == "table" else {},
    }


def _health(card_id: str, title: str, loops: list[str], kind: str) -> dict[str, Any]:
    """Analytics' loop health of each loop: now (gauges, a table) or over the period (a trend)."""

    return {
        **_kpi(card_id, title, loops[0]),
        "kind": kind,
        "items": [
            {"asset_id": loop, "result": "linkcraft.loop_health", "label": loop} for loop in loops
        ],
        "agg": "last" if kind != "trend" else "mean",
        "width": 12,
        "height": 2 if kind == "gauge" else 3,
        **({"options": {"columns": ["last", "state"]}} if kind == "table" else {}),
    }


def _ranked(
    section_id: str, title: str, kinds: list[str], group_by: str, limit: int = 10
) -> dict[str, Any]:
    """An events section that counts the period's events by ``group_by`` and ranks the groups."""

    return {
        **_events(section_id, title, kinds, limit),
        "events": {"kinds": kinds, "limit": limit, "group_by": group_by},
    }


def _ranking(card_id: str, title: str, loops: list[str]) -> dict[str, Any]:
    """Analytics' health of ``loops`` as bars, the worst first, coloured by its band."""

    card = _health(card_id, title, loops, "bar")
    return {**card, "height": max(3, len(loops) // 2), "options": {"sort": "asc"}}


# Unit 100, the crude distillation unit, as the map has it: feed, heat exchange, furnaces and
# the column (12 of its 15 loops: a panel shows up to 12 signals).
U100_LOOPS = [
    "FIC-1001",
    "FIC-1007",
    "FIC-1112",
    "TIC-1009",
    "TIC-1111",
    "TIC-1104",
    "TIC-1209",
    "FIC-1210",
    "FIC-1101",
    "FIC-1102",
    "TIC-1213",
    "FIC-1214",
]
U100_LEVELS = ["LIC-1106", "LIC-1113", "LIC-1211"]
# The loops the weekly report follows: every loop with a known problem of the plant's two
# process units, the critical loops, and FIC-1001, the healthy reference.
WATCHED_LOOPS = [
    "FIC-1003",
    "FIC-1102",
    "FIC-1206",
    "FIC-1214",
    "PIC-1002",
    "PIC-1103",
    "PIC-1202",
    "TIC-1209",
    "LIC-1004",
    "TIC-1005",
    "AIC-1006",
    "FIC-1001",
]
VALVE_LOOPS = [
    "FIC-1003",
    "FIC-1102",
    "FIC-1206",
    "FIC-1214",
    "LIC-1004",
    "FIC-1109",
    "PIC-1207",
    "FIC-1219",
    "LIC-1113",
    "FIC-1001",
]
SENSOR_LOOPS = [
    "AIC-1006",
    "AIC-1108",
    "AIC-1205",
    "AIC-1215",
    "PIC-1008",
    "TIC-1111",
    "TIC-1209",
    "AIC-1224",
    "TIC-1114",
]
FINDINGS = ["linkcraft.finding.opened"]
ALARM_EVENTS = ["alarmcraft.alarm.raised", "alarmcraft.alarm.cleared", "alarmcraft.flood.started"]
RAISED = ["alarmcraft.alarm.raised"]

HEALTH_SCALE = (
    "Analytics rates every loop from **0 to 100** after each round of its methods: "
    "**75 and above** is healthy (green), **50 to 75** needs attention (amber) and "
    "**under 50** is a problem (red). The score is limited by the worst finding of the "
    "loop's methods, and the *Summary* column names that finding in words."
)

REPORTS: list[dict[str, Any]] = [
    {
        "name": "Control loops weekly performance",
        "description": "Which control loops had problems this week, which problems were the "
        "most frequent, the worst loops, and the valves with stiction, explained.",
        "folder": INSTRUMENTATION["name"],
        "period": "7d",
        "schedule": {"every": "week", "weekday": "mon", "at": "07:00"},
        "recipients": ["group:instrumentation", "group:process-engineering"],
        "sections": [
            _text(
                "summary",
                "Control loop performance, last 7 days",
                "This report reviews the control loops of **Riverbend Refinery** over the last "
                "seven days, as PlantCraft Analytics judged them. It answers four questions: "
                "*which loops had problems*, *which problems were the most frequent*, *which "
                "loop is the worst*, and *what should be done next*. Every table and chart is "
                "computed when the report is made; the text explains how to read them.\n\n"
                "### How loops are judged\n\n"
                + HEALTH_SCALE
                + "\n\nA **finding** opens when one method starts flagging a loop (for example "
                "*Possible valve stiction screening* or *Oscillation screening by "
                "autocorrelation*) and closes when the method stops flagging it. Counting the "
                "findings opened in the week shows where the problems come from; a loop whose "
                "finding opens and closes again and again has an intermittent problem, often "
                "worse than a steady one.",
            ),
            _text(
                "where",
                "Which loops had problems",
                "The table counts the findings opened this week **by loop**, the most first. "
                "*Share* is the loop's part of all the week's findings, *Latest* when its "
                "last finding opened and *Latest event* what Analytics said then. A colour bar "
                "marks the worst severity among its findings (red: bad, amber: warning).",
                2,
            ),
            _ranked("by-loop", "Findings opened this week, by loop", FINDINGS, "subject", 10),
            _text(
                "what",
                "The most frequent problems",
                "The same findings counted **by method**, that is by the kind of problem. "
                "A problem that appears on several loops usually has a common cause: a "
                "tuning practice (oscillation), a valve type or its maintenance (stiction), "
                "or an operating habit (manual mode).\n\n"
                "| Method | What it means | Usual fix |\n"
                "|---|---|---|\n"
                "| Oscillation screening by autocorrelation | The PV swings around its setpoint with a regular "
                "period | Lower the controller gain, check for a sticky valve or an interaction |\n"
                "| Possible valve stiction screening | The valve sticks, then jumps: the PV moves in steps "
                "| Valve maintenance; meanwhile a deadband or a stiction compensator |\n"
                "| Controller output saturation fraction | The controller output sits at a limit: the valve is too "
                "small or the setpoint unreachable | Resize the valve, review the setpoint |\n"
                "| Manual mode fraction | The loop spends long periods in manual | Ask "
                "operations why; retune or repair what makes them take it |\n"
                "| Sensor noise ratio | The measurement carries high-frequency noise | Filter "
                "the measurement, check the transmitter and its wiring |",
                2,
            ),
            _ranked(
                "by-problem",
                "Findings opened this week, by method",
                FINDINGS,
                "payload.method_id",
                10,
            ),
            _text(
                "worst",
                "The worst loops now",
                "The loops under watch ranked by their health **now**, the worst first: every "
                "loop with a known problem in units 100 and 200, the critical loops, and "
                "FIC-1001, a healthy loop kept for comparison. The table under it gives each "
                "loop's state and the finding that limits its score.",
                2,
            ),
            _card("ranking", _ranking("ranking", "Loop health now, worst first", WATCHED_LOOPS)),
            _card(
                "health-table",
                _health("health-table", "What limits each loop", WATCHED_LOOPS, "table"),
            ),
            _card(
                "week",
                {
                    **_health(
                        "week",
                        "Health of the problem loops over the week",
                        ["FIC-1003", "PIC-1202", "TIC-1209", "FIC-1001"],
                        "trend",
                    ),
                    "height": 3,
                },
            ),
            _text(
                "week-read",
                "",
                "**How to read the trend.** A line that stays under 50 is a steady problem "
                "(a sticky valve does not heal by itself). A line that dips and recovers is "
                "an intermittent one, often tied to the operation (a load change, a campaign). "
                "FIC-1001 should stay near the top: if it drops too, suspect the data before "
                "the loops.",
            ),
            {"section_id": "stiction-break", "kind": "break"},
            _text(
                "stiction",
                "Valve stiction",
                "**Stiction** (static friction) makes a control valve stick: the controller "
                "output (OP) keeps moving while the valve stays put, until the force is enough "
                "and the valve jumps. The process value (PV) then moves in steps instead of "
                "following the output smoothly, and the loop cycles around its setpoint "
                "even when it is well tuned. Stiction wears the valve and the process, and no "
                "retuning cures it: the valve needs maintenance.\n\n"
                "### How to see it\n\n"
                "- **OP against PV** (the scatter below): a healthy valve draws a cloud along "
                "a line; a sticky valve draws a parallelogram of flat steps, the OP moving "
                "while the PV does not.\n"
                "- **The trend**: a saw-tooth OP with a square-wave PV, at a steady period.\n\n"
                "### The valves Analytics suspects\n\n"
                "| Loop | Service | Criticality | What is seen |\n"
                "|---|---|---|---|\n"
                "| FIC-1003 | Recycle flow, U-200 | high | static friction, jumpy movement |\n"
                "| FIC-1102 | Reflux flow, U-100 | medium | stepwise valve movement |\n"
                "| FIC-1206 | Quench flow, U-200 | medium | friction and stepwise movement |\n"
                "| FIC-1214 | Side draw flow, U-100 | medium | static friction in the product "
                "valve |\n\n"
                "The chart under the scatters ranks the four by their health now; the "
                "*by method* table above says how often stiction was flagged this week.\n\n"
                "FIC-1003 is the clearest case: its scatter is shown next to the healthy "
                "FIC-1001 so the difference is visible.",
                2,
            ),
            _card(
                "stick",
                {
                    **_scatter("stick", "FIC-1003: OP against PV (flat steps)", "FIC-1003"),
                    "height": 3,
                },
                "half",
            ),
            _card(
                "healthy",
                {
                    **_scatter("healthy", "FIC-1001: OP against PV (healthy)", "FIC-1001"),
                    "height": 3,
                },
                "half",
            ),
            _card(
                "stick-trend",
                {
                    **_trend(
                        "stick-trend",
                        "FIC-1003 over the week: OP saw-tooth, PV steps",
                        "FIC-1003",
                        12,
                    ),
                    "height": 3,
                },
            ),
            _card(
                "stick-health",
                _ranking("stick-health", "Health of the suspected valves", STICTION_LOOPS),
            ),
            _text(
                "oscillation",
                "Oscillation",
                "An oscillating loop swings around its setpoint with a regular period. The "
                "usual cause is a controller tuned too hard (gain too high, integral time too "
                "short); a sticky valve or an interaction with another loop can cause it too. "
                "**PIC-1202** (reactor inlet pressure, U-200) and **PIC-1002** (vessel "
                "pressure) oscillate from aggressive tuning; the alarms on PIC-1202 come from "
                "these swings. Lowering the gain by a third and lengthening the integral time "
                "is the usual first step, watched for one shift.",
                2,
            ),
            _card("osc", {**_trend("osc", "PIC-1202 over the week", "PIC-1202", 12), "height": 3}),
            _text(
                "next",
                "Recommended actions",
                "1. **Valves with stiction** (FIC-1003 first, then FIC-1102, FIC-1206 and "
                "FIC-1214): plan the maintenance with instrumentation at the next opportunity; "
                "until then, keep the loops in automatic and accept the cycling.\n"
                "2. **PIC-1202 and PIC-1002**: retune (lower gain) and confirm the oscillation "
                "is gone in next week's report.\n"
                "3. **TIC-1209**: the temperature element drifts; check it against a hand-held "
                "reading and recalibrate.\n"
                "4. Any loop new to the first table: open it in Analytics and read its "
                "finding before the weekly meeting.\n\n"
                "*This report is made every Monday at 07:00 for instrumentation and process "
                "engineering. The counts cover the seven days up to the time it is made.*",
                2,
            ),
        ],
    },
    {
        "name": "Alarm summary, weekly",
        "description": "How the alarm system did this week against ISA-18.2 and EEMUA 191: the "
        "alarm load, the bad actors, the priorities and the floods, explained.",
        "folder": "Operation",
        "period": "7d",
        "schedule": {"every": "week", "weekday": "mon", "at": "08:00"},
        "recipients": ["group:u-100-operations", "group:u-200-operations", "user:marina.costa"],
        "sections": [
            _text(
                "summary",
                "Alarm system performance, last 7 days",
                "An alarm asks an operator to act. When there are too many, the important "
                "ones are lost among the rest, so plants measure their alarm system the way "
                "ISA-18.2 and EEMUA 191 describe. This report gives the week's alarm load, the "
                "**bad actors** (the few alarms that ring most), the mix of priorities and the "
                "floods, and says what to fix first.\n\n"
                "### The targets\n\n"
                "| Measure | Target | What it means |\n"
                "|---|---|---|\n"
                "| Average alarm rate | about 1 per 10 minutes per console (6 an hour, about "
                "1,000 a week) or less | above it the operator cannot respond to every alarm |\n"
                "| Floods | under 1% of the time | a flood is more than 10 alarms in 10 minutes |\n"
                "| Top 10 bad actors | a small share of all alarms | in a poor system they "
                "make half or more |\n"
                "| Priorities | about 80% low, 15% high, 5% critical | when everything is "
                "urgent, nothing is |",
            ),
            _text(
                "load",
                "The alarm load",
                "How many alarms were raised and cleared, and how many floods began. Compare "
                "the number raised with the target of about 1,000 a week per console; the "
                "raised and cleared counts should be close (an alarm raised and never "
                "cleared is a standing alarm).",
                2,
            ),
            _ranked("by-kind", "Alarm events this week", ALARM_EVENTS, "kind", 5),
            _text(
                "bad-actors",
                "Bad actors",
                "The alarms raised this week counted **by what they are about**, the most "
                "first. Fixing the top few (a wrong limit, a missing deadband, an oscillating "
                "loop behind them) usually removes a large part of the load. *Share* is the "
                "part of all alarms raised this week.",
                2,
            ),
            _ranked("by-subject", "Top 10 bad actors", RAISED, "subject", 10),
            _text(
                "priorities",
                "Priorities",
                "The same alarms by **priority**. Compare with the target mix: about 80% low, "
                "15% high and 5% critical. Too many high or critical alarms mean the "
                "priorities were not set by the consequence and the time to respond.",
                2,
            ),
            _ranked(
                "by-priority", "Alarms raised this week, by priority", RAISED, "payload.priority", 4
            ),
            _text(
                "behind",
                "Behind the top bad actor",
                "In this plant the pressure alarms of **PIC-1202** (reactor inlet, U-200) come "
                "from the loop itself: it oscillates from aggressive tuning, so its pressure "
                "crosses the alarm limit on every swing. Adding a deadband would hide the "
                "symptom; retuning the loop removes the cause. The trend shows the swings.",
                2,
            ),
            _card("pic", {**_trend("pic", "PIC-1202 over the week", "PIC-1202", 12), "height": 3}),
            _text("floods-head", "Floods and the latest alarms", "", 2),
            _events("floods", "Floods this week", ["alarmcraft.flood.started"], 10),
            _events("latest", "The latest alarms", RAISED, 15),
            _text(
                "next",
                "Recommended actions",
                "1. Review the **top three bad actors** with operations: is the limit right, "
                "does it need a deadband or an on-delay, is a loop behind it?\n"
                "2. Retune **PIC-1202** (see the *Control loops weekly performance* report).\n"
                "3. Review the priority of any alarm marked critical that rang more than once "
                "a day.\n\n"
                "*Made every Monday at 08:00 for the operations of units 100 and 200.*",
                2,
            ),
        ],
    },
    {
        "name": "U-100 daily report",
        "description": "The crude distillation unit's last 24 hours for the morning handover: "
        "throughput, furnaces, column, the loops and alarms of the day, explained.",
        "folder": "Operation",
        "period": "24h",
        "schedule": {"every": "day", "at": "06:00"},
        "recipients": ["group:u-100-operations", "user:marina.costa"],
        "sections": [
            _text(
                "summary",
                "Unit 100, the last 24 hours",
                "The daily report of **Unit 100**, the crude distillation unit, for the "
                "06:00 handover. It covers the 24 hours up to 06:00: the feed and the "
                "products, the furnaces, the column, the state of the unit's control loops "
                "and the alarms of the day. Values are the period's means unless a table says "
                "otherwise; a section that could not be read says so, and the rest of the "
                "report is still made.\n\n"
                "The unit has four areas: **Feed** (crude charge from TK-1001 by P-1001), "
                "**Heat exchange** (the feed/product exchanger E-1009), **Furnaces** (the "
                "atmospheric furnace F-1104) and **Distillation** (the column C-1101 with "
                "its overhead accumulator D-1106).",
            ),
            _text(
                "throughput",
                "Feed and throughput",
                "**FIC-1001** is the crude feed to the unit, **FIC-1007** the charge flow set "
                "by the campaign and **FIC-1112** the production flow. The feed should follow "
                "its setpoint closely; a gap between PV and SP that lasts means the pump or "
                "the valve cannot deliver.",
                2,
            ),
            _card("feed", {**_trend("feed", "Crude feed FIC-1001", "FIC-1001", 12), "height": 3}),
            _card(
                "flows",
                _pvs(
                    "flows",
                    "Feed and product flows (means of the day)",
                    ["FIC-1001", "FIC-1007", "FIC-1112", "FIC-1101"],
                ),
            ),
            _text(
                "furnace",
                "Furnaces",
                "The furnace heats the crude before the column. **TIC-1104** controls the "
                "furnace temperature by the fuel gas flow **FIC-1210**; **TIC-1209** measures "
                "the furnace outlet. TIC-1209's temperature element drifts slowly: if its "
                "value creeps away from TIC-1104 with the same firing, trust TIC-1104 and "
                "ask instrumentation to check the element.",
                2,
            ),
            _card(
                "furnace-trend",
                {
                    **_trend("furnace-trend", "Furnace temperature TIC-1104", "TIC-1104", 6),
                    "height": 3,
                },
                "half",
            ),
            _card(
                "outlet-trend",
                {**_trend("outlet-trend", "Furnace outlet TIC-1209", "TIC-1209", 6), "height": 3},
                "half",
            ),
            _text(
                "column",
                "Column",
                "The column separates the products. **FIC-1102** is the reflux, **TIC-1213** "
                "the top temperature that sets the product specification, and **FIC-1214** the "
                "side draw. FIC-1102 and FIC-1214 have valves that move in steps (stiction): "
                "a small, steady cycling on them is known and is in the weekly loop report.",
                2,
            ),
            _card(
                "column-table",
                _pvs(
                    "column-table",
                    "Column and levels, the day's range",
                    ["FIC-1102", "TIC-1213", "FIC-1214", *U100_LEVELS],
                    "table",
                ),
            ),
            _text(
                "loops",
                "The unit's control loops",
                HEALTH_SCALE + " Loops in amber or red are worth a word at the handover.",
                2,
            ),
            _card("ranking", _ranking("ranking", "Unit 100 loops, worst first", U100_LOOPS)),
            _card(
                "loops-table", _health("loops-table", "What limits each loop", U100_LOOPS, "table")
            ),
            _text(
                "alarms",
                "Alarms of the day",
                "The alarms raised in the 24 hours, counted by what they are about, then the "
                "latest of them. A unit in steady operation raises a few an hour at most.",
                2,
            ),
            _ranked("alarm-count", "Alarms raised, by what they are about", RAISED, "subject", 8),
            _events("alarm-list", "The latest alarms", ALARM_EVENTS[:2], 12),
            _text(
                "handover",
                "For the handover",
                "- Check any loop in red in the table above and say whether it was in manual.\n"
                "- Note any alarm that rang more than three times: it belongs in the weekly "
                "alarm review.\n"
                "- Write what the next shift must know in a Desk note.",
                2,
            ),
        ],
    },
    {
        "name": "Valve and instrument health, monthly",
        "description": "The month's view for maintenance planning: sticky and saturated "
        "valves, noisy and drifting measurements, ranked, with what each problem means.",
        "folder": INSTRUMENTATION["name"],
        "period": "30d",
        "schedule": {"every": "month", "day": 1, "at": "07:00"},
        "recipients": ["group:instrumentation"],
        "sections": [
            _text(
                "summary",
                "Valves and instruments, last 30 days",
                "Many loop problems are not tuning problems: a valve that sticks or cannot "
                "open enough, a transmitter that is noisy or drifts. Retuning does not fix "
                "them; maintenance does. This monthly report lists what Analytics found on "
                "the **final elements** (valves and actuators) and the **measurements** "
                "(transmitters and analyzers) over the last 30 days, so instrumentation can "
                "plan the work for the next maintenance window.\n\n" + HEALTH_SCALE,
            ),
            _text(
                "month",
                "Findings of the month",
                "Every finding Analytics opened in the 30 days, by method and then by loop. "
                "Over a month, a loop high in the second table with a valve or sensor problem "
                "is the first candidate for the maintenance list.",
                2,
            ),
            _ranked(
                "by-method",
                "Findings opened this month, by method",
                FINDINGS,
                "payload.method_id",
                10,
            ),
            _ranked("by-loop", "Findings opened this month, by loop", FINDINGS, "subject", 10),
            _text(
                "valves-about",
                "Valves and actuators",
                "Two valve problems matter most:\n\n"
                "- **Stiction**: the valve sticks, then jumps. The PV moves in steps and the "
                "loop cycles. Fix: repack or overhaul the valve; a positioner check first.\n"
                "- **Saturation**: the controller output sits at 0% or 100%. The valve is "
                "too small for the flow asked, or the actuator cannot reach its travel. Fix: "
                "check the actuator's supply and stroke; resize the valve if it is always "
                "fully open. **LIC-1004** (separator level) and **FIC-1109** (steam) show it.\n\n"
                "The chart ranks the valves under watch by their loop's health now.",
                2,
            ),
            _card("valves", _ranking("valves", "Valves under watch, worst first", VALVE_LOOPS)),
            _card(
                "valve-table",
                _health("valve-table", "What Analytics says of each valve", VALVE_LOOPS, "table"),
            ),
            _card(
                "saturation",
                {
                    **_trend(
                        "saturation",
                        "LIC-1004: the output pinned at its upper limit",
                        "LIC-1004",
                        12,
                    ),
                    "height": 3,
                },
            ),
            _text(
                "sensors-about",
                "Measurements and analyzers",
                "- **Noise**: high-frequency noise on a measurement makes the controller move "
                "the valve for nothing. Analyzers (the AIC loops) are the usual cases. Fix: "
                "check the sample system and the wiring; add a light filter.\n"
                "- **Drift**: a sensor that slowly moves away from the true value. The loop "
                "holds the wrong process value perfectly, so nothing looks wrong on the "
                "trend. Compare with a second measurement or a hand-held reading. "
                "**TIC-1209** (furnace outlet), **PIC-1008** (header pressure) and "
                "**AIC-1224** (effluent pH) are known to drift.",
                2,
            ),
            _card(
                "sensors",
                _ranking("sensors", "Measurements under watch, worst first", SENSOR_LOOPS),
            ),
            _card(
                "noise",
                {**_trend("noise", "AIC-1006: a noisy analyzer", "AIC-1006", 6), "height": 3},
                "half",
            ),
            _card(
                "drift",
                {**_trend("drift", "TIC-1209: a slow drift", "TIC-1209", 6), "height": 3},
                "half",
            ),
            _text(
                "plan",
                "For the maintenance plan",
                "1. Valves with stiction confirmed in this report and last month's: overhaul "
                "at the next window (FIC-1003 is the priority: high criticality).\n"
                "2. Saturated valves: check the actuator first; raise a resizing request only "
                "if the valve is fully open at normal throughput.\n"
                "3. Drifting sensors: recalibrate; noisy analyzers: inspect the sample "
                "system.\n\n"
                "*Made on the first day of each month at 07:00 for instrumentation.*",
                2,
            ),
        ],
    },
]

# Example reports of earlier demos, replaced by the four above (2026-10-27): the seed removes
# them where it made them, by name.
RETIRED_REPORTS = (
    "Plant overview, daily",
    "Loop detail, weekly",
    "Control room shift report",
    "Suite health weekly",
)


def view_reports(dash: Http) -> None:
    """The example reports, each made and sent once when it is created or rewritten, so
    Messages and the report's Sent tab show a PDF at once (after Alarms' replay: the alarm
    sections are full). A report of an earlier demo with the same name is rewritten (its
    description tells the editions apart); the retired examples are removed."""

    status, listed = dash.call("GET", "/api/reports", ok=(404,))
    if status == 404:
        return
    folders = _folders(dash)
    found = {item.get("name"): item for item in listed or []}
    for name in RETIRED_REPORTS:
        if name in found:
            dash.call("DELETE", f"/api/reports/{found[name]['report_id']}", ok=(403, 404))
            log(f"View: retired example report '{name}'")
    for spec in REPORTS:
        body = {key: value for key, value in spec.items() if key != "folder"}
        body["folder_id"] = folders.get(spec["folder"], "")
        old = found.get(spec["name"])
        if old is not None and old.get("description") == spec["description"]:
            continue
        if old is None:
            report = dash.post("/api/reports", body)["report_id"]
        else:
            report = old["report_id"]
            dash.put(f"/api/reports/{report}", body)
        status, run = dash.call("POST", f"/api/reports/{report}/send", ok=(422, 502, 503))
        sent = f", sent to {run.get('delivered', 0)} people" if status < 300 else ""
        log(f"View: report '{spec['name']}'{'' if old is None else ' (rewritten)'}{sent}")
