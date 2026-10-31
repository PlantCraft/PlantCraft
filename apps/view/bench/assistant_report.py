"""Assistant report bench (prototype E2): three editions of an assistant section over the
Riverbend demo plant (unit U-200, a week of loop results and alarms), with two feedbacks in
between, through View's real code (FakePlantCraft stands in for the suite).

    python bench/assistant_report.py OUT_DIR --openai      # a real model, OPENAI_API_KEY, 5 calls
    python bench/assistant_report.py OUT_DIR --answers DIR # answers written by hand, <use>-<n>.md

Run from apps/view with its dev install. Everything the model gets and says lands in OUT_DIR;
the key is read from the environment and never written.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

VIEW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIEW))
from plantcraft_sdk.testing import FakePlantCraft  # noqa: E402

from tests.conftest import client_for, make_runtime  # noqa: E402
from tests.plant import APP_KEY, APPS, LINK_KEY, USERS  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("bench-out")
OUT.mkdir(parents=True, exist_ok=True)
ANSWERS = Path(sys.argv[sys.argv.index("--answers") + 1]) if "--answers" in sys.argv else None
OPENAI = "--openai" in sys.argv
MODEL = os.environ.get("E2_MODEL", "gpt-5-mini")
FEEDBACK = [
    "Muito longo para a gerência. Quero no começo uma tabela com as 5 piores malhas (malha, "
    "problema, pontuação, alarmes na semana). Junte os analisadores numa linha só. Nas ações, diga "
    "quem deve agir: instrumentação, controle ou operação.",
    "Melhorou. Agora separe os problemas de válvula/atuador (mecânicos) dos de sintonia, e diga "
    "quantos alarmes cada grupo gerou. Tire a frase sobre a semana anterior: se não há dado, não "
    "comente.",
]
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)  # Monday 07:00 BRT
MAP = json.loads((VIEW.parents[1] / "deploy/demo/plantcraft-50-loops-map.json").read_text())

PROBLEM = [
    ("oscillation", "alarm", 41, "Oscillation, period {p} min, amplitude {a}% of range"),
    ("friction", "warning", 55, "Valve stiction: jumps of {a}% after holding still"),
    ("stepwise", "warning", 58, "Stepwise valve movement, {a}% steps"),
    ("actuator", "alarm", 38, "Output saturated at 100% for {p}% of the week"),
    ("saturation", "alarm", 44, "Output saturated for {p}% of the week"),
    ("limited", "warning", 60, "Output limited at high demand, {p}% of the week"),
    ("manual", "warning", 52, "In manual mode {p}% of the week"),
    ("noise", "warning", 63, "High-frequency noise, {a}% of range"),
    ("drift", "warning", 66, "Measurement drift, {a}% of range over the week"),
    ("interaction", "warning", 64, "Interaction with a neighbour loop (correlation 0.{p})"),
    ("disturbance", "ok", 74, "Recovers from load disturbances in {p} min"),
]


def assets() -> list[dict]:
    out = [
        {
            "id": a["asset_id"],
            "name": a["name"] if a["kind"] != "unit" else f"{a['asset_id']} {a['name']}",
            "kind": a["kind"],
            "parent_id": a.get("parent_id"),
            "attributes": a.get("attributes") or {},
        }
        for a in MAP["assets"]
    ]
    areas = {
        (a["name"], a.get("parent_id")): a["asset_id"] for a in MAP["assets"] if a["kind"] == "area"
    }
    for loop in MAP["loops"]:
        out.append(
            {
                "id": loop["loop_id"],
                "name": loop["loop_id"],
                "kind": "loop",
                "parent_id": areas.get((loop["area"], loop["unit"]), loop["unit"]),
                "attributes": {
                    "description": f"{loop['name']} ({loop['loop_type']}, criticality {loop['criticality']})"
                },
            }
        )
    return out


def health(loop: dict, n: int) -> dict:
    service = loop["service"].lower()
    for word, status, score, text in PROBLEM:
        if word in service:
            return {
                "status": status,
                "score": score - n % 5,
                "summary": text.format(p=4 + n % 9, a=round(1.5 + (n % 7) * 0.7, 1)),
            }
    return {"status": "ok", "score": 88 + n % 8, "summary": "Within limits"}


def build() -> FakePlantCraft:
    fake = FakePlantCraft(
        users=USERS,
        apps=APPS,
        app_keys={"dashcraft": APP_KEY, "linkcraft": LINK_KEY, "alarmcraft": "alarm-key"},
        assets=assets(),
        signals=[],
        now=NOW,
    )
    link = fake.client(None, app="linkcraft", key=LINK_KEY)
    rows = []
    events = []
    for n, loop in enumerate(MAP["loops"]):
        h = health(loop, n)
        rows.append(
            {
                "subject": f"asset:{loop['loop_id']}",
                "kind": "loop_health",
                **h,
                "details": {
                    "service_factor": round(h["score"] / 100, 2),
                    "criticality": loop["criticality"],
                },
                "expires_at": (NOW + timedelta(days=1)).isoformat(),
            }
        )
        if h["status"] != "ok":
            # Opened mid-week; the worst also last week (a repeat).
            events.append(
                (
                    NOW - timedelta(hours=20 + n * 7 % 140),
                    "linkcraft.finding.opened",
                    loop["loop_id"],
                    "warning" if h["status"] == "warning" else "error",
                    h["summary"],
                )
            )
        if "disturbance" in loop["service"].lower() or "recovery" in loop["service"].lower():
            events.append(
                (
                    NOW - timedelta(hours=30 + n),
                    "linkcraft.finding.closed",
                    loop["loop_id"],
                    "info",
                    "Finding closed: back within limits",
                )
            )
    assert not link.put_results(rows)["errors"]
    # Alarms on the U-200 problem loops.
    for k, (loop_id, count) in enumerate(
        [("PIC-1002", 14), ("PIC-1103", 9), ("LIC-1004", 6), ("PIC-1202", 4), ("TIC-1005", 2)]
    ):
        for i in range(count):
            events.append(
                (
                    NOW - timedelta(hours=3 + i * 11 + k),
                    "alarmcraft.alarm.raised",
                    loop_id,
                    "warning" if i % 3 else "critical",
                    f"{loop_id} PV {'high' if i % 2 else 'low'} alarm",
                )
            )
    events.append(
        (
            NOW - timedelta(days=3, hours=4),
            "alarmcraft.flood.started",
            "PIC-1103",
            "critical",
            "Alarm flood: 12 alarms in 10 min on Compression",
        )
    )
    for at, kind, subject, severity, summary in sorted(events):
        app = kind.split(".")[0]
        fake.links.events.append(
            {
                "id": len(fake.links.events) + 1,
                "at": at.isoformat(),
                "app": app,
                "kind": kind,
                "subject": f"asset:{subject}",
                "actor": f"app:{app}",
                "summary": summary,
                "refs": [],
                "payload": {},
                "severity": severity,
            }
        )
    return fake


def invented(text: str) -> list[str]:
    """Tags in the text that no asset of the plant has (the model made them up)."""

    from dashcraft.reports.assistant import TAG

    known = {a["id"] for a in assets()} | {a["name"] for a in assets()}
    return sorted({tag for tag in TAG.findall(text) if tag not in known})


def openai(call: dict) -> tuple[str, dict]:
    """One answer of OpenAI's Responses API, as PlantCraft's own client asks it."""

    body = {
        "model": MODEL,
        "instructions": call["system"],
        "input": [{"role": m["role"], "content": m["content"]} for m in call["messages"]],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        json.dumps(body).encode(),
        {
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    data = json.load(urllib.request.urlopen(request, timeout=300))
    texts = [
        part["text"]
        for item in data.get("output", [])
        for part in item.get("content") or []
        if part.get("type") == "output_text"
    ]
    return "\n".join(texts).strip(), data.get("usage") or {}


def answer_for(use: str, counter: dict) -> callable:
    def answer(call: dict) -> str:
        counter[use] = counter.get(use, 0) + 1
        n = counter[use]
        (OUT / f"{use}-{n}.prompt.txt").write_text(
            "SYSTEM:\n" + call["system"] + "\n\nUSER:\n" + call["messages"][-1]["content"]
        )
        if OPENAI:
            text, usage = openai(call)
            (OUT / f"{use}-{n}.usage.json").write_text(json.dumps(usage))
            (OUT / f"{use}-{n}.answer.md").write_text(text)
            return text
        path = ANSWERS / f"{use}-{n}.md"
        if not path.exists():
            raise SystemExit(f"write {path}")
        return path.read_text()

    return answer


def main(editions: int) -> None:
    import tempfile

    fake = build()
    counts: dict = {}

    def llm(call: dict) -> str:
        return answer_for(call["use"], counts)(call)

    fake.links.llm_answer = llm
    tmp = Path(tempfile.mkdtemp())
    runtime = make_runtime(tmp, fake)
    client = client_for(runtime, fake).__enter__()
    report = {
        "name": "U-200 weekly, by the assistant",
        "description": "Control loops and alarms of U-200 over the week, written by the assistant.",
        "period": "7d",
        "schedule": {"every": "week", "at": "07:00", "weekday": "mon"},
        "recipients": ["user:engineer"],
        "sections": [
            {
                "section_id": "ai",
                "kind": "assistant",
                "title": "U-200 this week",
                "assistant": {"asset_ids": ["U-200"], "analyses": ["loops", "alarms"]},
            }
        ],
    }
    created = client.post("/dash/api/reports", json=report)
    assert created.status_code == 201, created.text
    rid = created.json()["report_id"]
    log = []
    feedback = FEEDBACK
    for edition in range(1, editions + 1):
        made = client.post(f"/dash/api/reports/{rid}/pdf").json()
        sec = client.get(f"/dash/api/reports/{rid}/sections/ai").json()["data"]
        text = sec["written"]["text"] if sec.get("written") else ""
        pdf = client.get(f"/dash/api/reports/{rid}/runs/{made['run_id']}/pdf")
        (OUT / f"edition-{edition}.pdf").write_bytes(pdf.content)
        md = client.get(f"/dash/api/reports/{rid}/export/md")
        (OUT / f"edition-{edition}.md").write_text(md.text)
        log.append(
            {
                "edition": edition,
                "run": made["status"],
                "problems": made["problems"],
                "version": sec["written"]["version"] if sec.get("written") else None,
                "facts": {k: sec[k] for k in ("assets", "results", "events")},
                "chars": len(text),
                "tags_not_in_facts": invented(text),
            }
        )
        if edition < editions and edition <= len(feedback):
            tuned = client.post(
                f"/dash/api/reports/{rid}/assistant/ai/feedback",
                json={"feedback": feedback[edition - 1]},
            )
            assert tuned.status_code == 200, tuned.text
            proposal = tuned.json()
            log[-1]["feedback"] = feedback[edition - 1]
            log[-1]["next_requirements"] = proposal["requirements"]
            log[-1]["proposal_warnings"] = proposal["warnings"]
            # The bench applies every proposal as given (a person would read it first).
            applied = client.put(
                f"/dash/api/reports/{rid}/assistant/ai/requirements",
                json={"requirements": proposal["requirements"], "feedback": proposal["feedback"]},
            )
            assert applied.status_code == 200, applied.text
    history = client.get(f"/dash/api/reports/{rid}/assistant/ai").json()
    (OUT / "history.json").write_text(json.dumps(history, indent=1, ensure_ascii=False))
    (OUT / "log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False))
    print(json.dumps(log, indent=1, ensure_ascii=False))
    for edition in range(1, editions + 1):
        print(f"\n===== EDITION {edition} =====\n" + (OUT / f"edition-{edition}.md").read_text())


if __name__ == "__main__":
    main(3)
