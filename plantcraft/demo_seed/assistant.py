"""Desk's assistant chats and notebooks of loop data, with the sources they cite."""

from __future__ import annotations

import urllib.parse
from typing import Any

from .base import VISITOR, Http
from .links import Links

# Desk's Assistant and Notebooks -----------------------------------------------------------------

# Chats with the assistant as the team keeps them, written for the demo: what a language model
# answers from Analytics' results and the plant's documents. Each was asked on the page it is
# about (``place``, ``about``) and lists its sources under the answer (``sources``: names, see
# ``Links``); Ana's and Carlos's are shared with everyone, so the visitor reads them in "Shared
# with me"; the visitor has one too. ``{{name}}`` in an answer links that thing's page.
DEMO_ANSWER = "Example answer, written for the demo"
ASSISTANT_CHATS: list[dict[str, Any]] = [
    {
        "owner": "ana.lima",
        "title": "Why does FIC-1003 cycle?",
        "place": "Analytics › FIC-1003",
        "about": "asset:FIC-1003",
        "question": "Why does the recycle flow FIC-1003 cycle with a saw-tooth output?",
        "answer": "**A sticky valve: FV-1003 has stiction.**\n\n"
        "- Analytics' *Control loop performance* flags stiction on [FIC-1003](/assets/FIC-1003): the "
        "output ramps while the flow stays put, then the flow jumps (the PV against OP plot draws "
        "flat steps, not a line).\n"
        "- The maintenance history ({{DOC-MH-001}}, FV-1003) measured a dead band of **2.8 %** "
        "after the graphite packing was tightened for a stem leak (WO-25-1182, 2025-05-20).\n"
        "- The troubleshooting guide ({{DOC-TG-001}}, 4.1) lists FIC-1003, FIC-1102, FIC-1206 and "
        "FIC-1214 as the loops with known stiction.\n\n"
        "**Next:** the valve test of {{PRO-U200-012}} (steps of 0.5 % in manual, 30 s apart; stop "
        "if the flow falls below 40 m³/h), then the PTFE V-ring packing the history proposes. "
        "Retuning would only hide it. The action is already open for Carlos Menezes.",
        "sources": [
            "asset:FIC-1003",
            "DOC-MH-001",
            "DOC-TG-001",
            "PRO-U200-012",
            "Inspect the FIC-1003 recycle valve for stiction",
        ],
        "shared": True,
    },
    {
        "owner": "ana.lima",
        "title": "Is TIC-1209 drifting or is the furnace hotter?",
        "place": "Analytics › TIC-1209",
        "about": "asset:TIC-1209",
        "question": "The furnaces model says TIC-1209 reads higher than expected. Sensor or process?",
        "answer": "**Most likely the sensor, TT-1209.**\n\n"
        "- Analytics' Furnaces model sees the outlet temperature leave the model slowly while the "
        "fuel and the feed hold still: a process change would move them too.\n"
        "- The U-100 operating manual ({{DOC-U100-OM-001}}, 7.1) warns that a drifting TT-1209 "
        "keeps TIC-1209 at its setpoint while the column runs colder, and asks for a check with "
        "a portable thermometer.\n"
        "- The datasheets ({{DOC-DS-001}}) calibrate TT-1209 every 6 months; the maintenance "
        "history proposes a type N thermocouple, which drifts less.\n\n"
        "**Next:** compare with a portable reading at the next round; the calibration action is "
        "open for instrumentation.",
        "sources": [
            "asset:TIC-1209",
            "DOC-U100-OM-001",
            "DOC-DS-001",
            "Calibrate the TIC-1209 thermocouple",
        ],
        "shared": True,
    },
    {
        "owner": "ana.lima",
        "title": "Why does the PIC-1202 pressure alarm ring so often?",
        "place": "Alarms › PIC-1202 high pressure",
        "about": "asset:PIC-1202",
        "question": "The PIC-1202 high-pressure alarm rang dozens of times in two days. Why?",
        "answer": "**The loop oscillates; the alarm only follows it.**\n\n"
        "- The alarm rises at each peak of a cycle of about **12 minutes**: Analytics' oscillation "
        "watch finds the same period on [PIC-1202](/assets/PIC-1202) and rates it critical.\n"
        "- The output swings as much as the pressure, with no stiction signature: the tuning is "
        "too aggressive for the separator's time constant.\n"
        "- {{INC-2026-007}} tells the same story on PIC-1002: shelving the alarm hid it for a "
        "week, retuning fixed it. The {{DOC-TG-001}} (section 3) has the retuning steps.\n\n"
        "**Next:** retune rather than raise the limit or shelve (an alarm that rings at every "
        "cycle is a *chattering* alarm in ISA-18.2 terms). Ana's retune action is open.",
        "sources": [
            "asset:PIC-1202",
            "INC-2026-007",
            "DOC-TG-001",
            "Retune PIC-1202: aggressive tuning makes it oscillate",
        ],
        "shared": True,
    },
    {
        "owner": "carlos.menezes",
        "title": "How do I test FV-1003 without stopping the unit?",
        "place": "Documents › PRO-U200-012",
        "about": "",
        "question": "How do I test the FV-1003 valve stroke with the unit running?",
        "answer": "Follow {{PRO-U200-012}} (in Portuguese; the steps in short):\n\n"
        "1. Agree the test with the control room and put **FIC-1003 in manual**.\n"
        "2. Move the output in steps of **0.5 %**, 30 s apart, first up, then down.\n"
        "3. Write down the output at which the flow starts to move: the gap between up and down "
        "is the dead band. Above **1 %** the valve needs work.\n"
        "4. Stop if the flow falls below **40 m³/h** and go back to automatic.\n\n"
        "The last test on FV-1003 ({{DOC-MH-001}}) found 2.8 %, after the packing was tightened.",
        "sources": ["PRO-U200-012", "DOC-MH-001", "asset:FIC-1003"],
        "shared": True,
    },
    {
        "owner": VISITOR,
        "title": "Which loops need attention today?",
        "place": "Desk › Assistant",
        "about": "",
        "question": "Which loops of the plant need attention today, and why?",
        "answer": "Four loops stand out in Analytics' results this morning:\n\n"
        "| Loop | Level | Why |\n|---|---|---|\n"
        "| [FIC-1003](/assets/FIC-1003) | Critical | Sticky valve (stiction), the flow cycles |\n"
        "| [PIC-1202](/assets/PIC-1202) | Critical | Oscillates: tuned too hard; the pressure "
        "alarm rings at its peaks |\n"
        "| [TIC-1209](/assets/TIC-1209) | Warning | Drifts away from the Furnaces model: a "
        "sensor drift is likely |\n"
        "| [TIC-1104](/assets/TIC-1104) | Warning | A cyclic disturbance from the furnace draft |\n\n"
        "[FIC-1001](/assets/FIC-1001), the feed, is healthy: compare them on the {{Plant overview}} "
        "dashboard in View. Each problem has an open action in Desk.",
        "sources": [
            "asset:FIC-1003",
            "asset:PIC-1202",
            "asset:TIC-1209",
            "Plant overview",
        ],
        "shared": False,
    },
    # More of the team's chats (about twenty, from several apps).
    {
        "owner": "ana.lima",
        "title": "Which loops got worse this week?",
        "place": "Analytics › Results",
        "about": "",
        "question": "Which loops got worse this week compared with last week?",
        "answer": "**Three loops lost ground; one recovered.**\n\n- [FIC-1003](/assets/FIC-1003): from warning to critical, stiction growing since Monday.\n- [PIC-1202](/assets/PIC-1202): critical all week, the 12-minute oscillation did not change.\n- [TIC-1104](/assets/TIC-1104): a cyclic disturbance appears in the afternoons, with the furnace draft.\n- [FIC-1102](/assets/FIC-1102) recovered after its positioner was replaced.\n\nThe {{Control loops weekly performance}} report lists them all with their indices.",
        "sources": [
            "asset:FIC-1003",
            "asset:PIC-1202",
            "asset:TIC-1104",
            "asset:FIC-1102",
            "Control loops weekly performance",
        ],
        "shared": True,
    },
    {
        "owner": "carlos.menezes",
        "title": "What does the FV-1003 packing history say?",
        "place": "Documents › DOC-MH-001",
        "about": "asset:FIC-1003",
        "question": "What maintenance did FV-1003 get in the last two years?",
        "answer": "From {{DOC-MH-001}}:\n\n1. **2024-11**: positioner recalibrated after a feed change.\n2. **2025-05-20** (WO-25-1182): graphite packing tightened for a stem leak; the dead band went up to 2.8 %.\n3. **Proposed**: a PTFE V-ring packing, which holds the stem with less friction.\n\nThe stiction Analytics sees now matches the 2025 tightening.",
        "sources": ["DOC-MH-001", "asset:FIC-1003"],
        "shared": True,
    },
    {
        "owner": "marina.costa",
        "title": "What should the night shift watch on U-200?",
        "place": "Desk › Assistant",
        "about": "",
        "question": "What should the night shift watch on U-200 tonight?",
        "answer": "**Two things on U-200:**\n\n- [PIC-1202](/assets/PIC-1202) oscillates: its high-pressure alarm will ring at the peaks. Do not shelve it; the retune is planned this week.\n- [FIC-1003](/assets/FIC-1003) keeps cycling until its valve test tomorrow morning: keep it in automatic.\n\nEverything else on U-200 is healthy in Analytics' last round.",
        "sources": ["asset:PIC-1202", "asset:FIC-1003"],
        "shared": True,
    },
    {
        "owner": "ana.lima",
        "title": "Is LIC-1004 stable after the retune?",
        "place": "Analytics › LIC-1004",
        "about": "asset:LIC-1004",
        "question": "Did the LIC-1004 retune hold through the feed changes?",
        "answer": "**Yes.** Since the retune, Analytics rates [LIC-1004](/assets/LIC-1004) healthy in every round: the level settles in about 4 minutes after a feed change, with no overshoot above 5 %. The trend is on the {{Plant overview}} dashboard.",
        "sources": ["asset:LIC-1004", "Plant overview"],
        "shared": True,
    },
    {
        "owner": "juliana.rocha",
        "title": "How do I acknowledge a group of alarms?",
        "place": "Alarms › Alarms",
        "about": "",
        "question": "How do I acknowledge several alarms at once?",
        "answer": "In Alarms, open **Alarms**, tick the rows you have seen and press **Acknowledge**. Each alarm also reaches its people in Notifications, where the same button works. An acknowledged alarm stops its reminders but stays in the list until its rule clears it.",
        "sources": [],
        "shared": True,
    },
    {
        "owner": "lucas.ferreira",
        "title": "Which transmitters are due for calibration?",
        "place": "Documents › DOC-DS-001",
        "about": "",
        "question": "Which U-100 transmitters are due for calibration this month?",
        "answer": "From the datasheets ({{DOC-DS-001}}), with their last calibration in the maintenance history:\n\n| Transmitter | Every | Due |\n|---|---|---|\n| TT-1209 | 6 months | now (and drifting) |\n| FT-1001 | 12 months | in 3 weeks |\n| LT-1004 | new | next year |\n\nTT-1209 already has its calibration action.",
        "sources": ["DOC-DS-001", "DOC-MH-001", "Calibrate the TIC-1209 thermocouple"],
        "shared": True,
    },
    {
        "owner": "ana.lima",
        "title": "Draft the weekly loop review",
        "place": "Desk › Assistant",
        "about": "",
        "question": "Draft the summary for Monday's weekly loop review.",
        "answer": "**Weekly loop review: draft**\n\n- Fixed: FIC-1102 (positioner), LIC-1004 (retuned).\n- Open: FIC-1003 (valve test tomorrow), PIC-1202 (retune this week), TIC-1209 (calibration).\n- Watch: TIC-1104 (afternoon disturbance), FIC-1214 (in manual until its valve is checked).\n\nNumbers from the {{Control loops weekly performance}} report.",
        "sources": ["Control loops weekly performance", "asset:FIC-1003", "asset:PIC-1202"],
        "shared": True,
    },
    {
        "owner": "carlos.menezes",
        "title": "What spares do we need for the valve work?",
        "place": "Desk › Assistant",
        "about": "",
        "question": "What spare parts do the open valve actions need?",
        "answer": "From the open actions and {{DOC-MH-001}}:\n\n- FV-1003: a PTFE V-ring packing set (proposed) and stem gaskets.\n- FV-1214: a positioner, the same model as FIC-1102's.\n- FV-1206: a packing set, to fit together with FV-1214.\n\nCheck the store before the window: the positioner takes two weeks to arrive.",
        "sources": ["DOC-MH-001", "asset:FIC-1214", "asset:FIC-1206"],
        "shared": True,
    },
    {
        "owner": "marina.costa",
        "title": "Why did the plant lose data last night?",
        "place": "Alarms › Events",
        "about": "",
        "question": "We had a 'No data from the plant' alarm at 03:10. What happened?",
        "answer": "The Historian's OPC UA collector lost its connection for **12 minutes** (03:10 to 03:22) and reconnected by itself: every U-100 signal shows the same gap. Nothing changed in the process. If it happens again, check the network switch in the rack room, which IT replaced last month.",
        "sources": [],
        "shared": True,
    },
    {
        "owner": VISITOR,
        "title": "What does the stiction index mean?",
        "place": "Analytics › Blocks",
        "about": "",
        "question": "What does Analytics' stiction index measure, and when is it bad?",
        "answer": "It measures how much the valve **sticks, then jumps**: the output moves while the flow stays still, then the flow catches up at once. Analytics plots the PV against the OP: a healthy valve draws a line, a sticky one flat steps.\n\n- Below **0.3**: healthy.\n- **0.3 to 0.6**: watch it.\n- Above **0.6**: plan a valve test.\n\n[FIC-1003](/assets/FIC-1003) is at 0.74 this morning.",
        "sources": ["asset:FIC-1003"],
        "shared": False,
    },
    {
        "owner": VISITOR,
        "title": "Compare the two furnace outlets",
        "place": "View › Trends",
        "about": "",
        "question": "Compare TIC-1209 with TIC-1104 over the last day.",
        "answer": "Both outlets hold their setpoints, in different ways: [TIC-1209](/assets/TIC-1209) drifts slowly up against the Furnaces model (a sensor drift is likely), while [TIC-1104](/assets/TIC-1104) swings a few degrees every afternoon with the draft. The saved trend *Furnace outlets: TIC-1209 against TIC-1104* in View shows both.",
        "sources": ["asset:TIC-1209", "asset:TIC-1104"],
        "shared": False,
    },
    {
        "owner": "ana.lima",
        "title": "Can a model predict PIC-1202's new tuning?",
        "place": "Models › Studies",
        "about": "asset:PIC-1202",
        "question": "Can Models tell which tuning stops the PIC-1202 oscillation?",
        "answer": "Yes: a study on the separator model runs a grid of gains and integral times and ranks them by overshoot and settling time. The best runs halve the gain and double the integral time; the oscillation disappears, with a 4-minute settling. Try it on the plant in small steps, as {{DOC-TG-001}} section 3 says.",
        "sources": ["asset:PIC-1202", "DOC-TG-001"],
        "shared": True,
    },
]
NOTEBOOKS = [
    # (owner, name, loop, roles, period): a notebook of the loop's signals over the period.
    (VISITOR, "FIC-1003 sticky valve, last 12 h", "FIC-1003", ("pv", "sp", "op"), "-12h"),
    ("ana.lima", "PIC-1202 oscillation, last 24 h", "PIC-1202", ("pv", "sp", "op"), "-24h"),
]


def _signals_of(admin: Http, loop: str, roles: tuple[str, ...]) -> list[str]:
    asset = admin.get(f"/api/assets/{urllib.parse.quote(loop)}") or {}
    found = {
        item.get("role"): f"{item['source_id']}:{item['signal_id']}"
        for item in asset.get("signals") or []
        if item.get("source_id") and item.get("signal_id")
    }
    return [found[role] for role in roles if role in found]


def assistant_and_notebooks(
    workspace: Any, admin: Http, admin_name: str, links: Links | None = None
) -> dict[str, int]:
    """The team's assistant chats and two notebooks of loop data in people's folders; Notebooks
    is turned on (it ships off). Idempotent: a chat or notebook already there is kept. The chats
    are in ``links`` after, by title."""

    from plantcraft.assistant_chat import ChatStore
    from plantcraft.notebooks import file_name
    from plantcraft.notebooks.templates import series_notebook

    links = links or Links()
    written = {"chats": 0, "notebooks": 0}
    chats = ChatStore(workspace.db)
    for spec in ASSISTANT_CHATS:
        found = next(
            (item for item in chats.chats(spec["owner"]) if item["title"] == spec["title"]), None
        )
        if found is None:
            found = chats.create(
                spec["owner"], spec["title"], ref=spec["about"], place=spec["place"]
            )
            chats.add(found["chat_id"], "user", spec["question"])
            chats.add(
                found["chat_id"],
                "assistant",
                links.markdown(spec["answer"]),
                meta={"model": DEMO_ANSWER},
            )
            if spec["shared"]:
                chats.share(found["chat_id"], spec["owner"], ["everyone"])
            written["chats"] += 1
        else:
            # A chat seeded before the links: its answer as written now.
            answers = [m for m in chats.messages(found["chat_id"]) if m["role"] == "assistant"]
            text = links.markdown(spec["answer"])
            if answers and answers[-1]["meta"].get("model") == DEMO_ANSWER:
                if answers[-1]["text"] != text:
                    chats.update(answers[-1]["message_id"], text=text)
        links.add(spec["title"], f"chat:{found['chat_id']}")
    store = workspace.notebooks
    if store.settings()["allowed"] and not store.enabled():
        store.save_settings(actor=admin_name, enabled=True)
    for owner, name, loop, roles, period in NOTEBOOKS:
        if any(item.get("name") == file_name(name) for item in store.list(owner)):
            continue
        signals = _signals_of(admin, loop, roles)
        if not signals:
            continue
        _title, notebook = series_notebook(signals, period, "now", step=10, origin=f"{loop}'s page")
        store.create(owner, name, notebook)
        written["notebooks"] += 1
    return written


def chat_sources(workspace: Any, links: Links) -> None:
    """Each demo answer's sources, once the actions they name exist (run again: the same)."""

    from plantcraft.assistant_chat import ChatStore

    chats = ChatStore(workspace.db)
    for spec in ASSISTANT_CHATS:
        ref = links.refs.get(spec["title"], "")
        if not ref.startswith("chat:"):
            continue
        answers = [
            item
            for item in chats.messages(int(ref.removeprefix("chat:")))
            if item["role"] == "assistant"
        ]
        if answers:
            chats.update(answers[-1]["message_id"], refs=links.of(*spec["sources"]))
