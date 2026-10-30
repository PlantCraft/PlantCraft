"""The evaluation of the assistant's works: each work asked the way its page asks it.

Owner, 2026-10-25: "run an LLM with the prompt the application adds from the person's choice,
and see whether the model can read that context and whether it is enough". One case per work
(``assistant_works``): the chat starts as the button beside the page's title starts it, with
the work, the page's id and a subject read from this installation (an asset, a loop, a signal,
an alarm's signal, a run, an action), and the same context PlantCraft builds for a person
(``api/routers/assistant_chat.page_context``). The question is the work's own title, as the
menu sends it; a create work's question also gives the fields, so one answer can propose.

The checks are deliberately simple (a weak model should pass most): an ask work answers in
some sentences, reads the plant with at least one tool, names its subject and does not say it
could not find it; a create work calls ``propose`` with fields PlantCraft accepts and carries
what the person asked for. Each result keeps the context sent and the proposal, so a person
can judge whether the context was enough. A work whose page needs an object this installation
does not have (a block, a dashboard) is left out; the run says how many.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plantcraft.assistant_chat.evals import Case, Reader
from plantcraft.assistant_works import Work, WorkRegistry

# Words that say the model could not read its subject (narrower than evals.NOT_FOUND: an
# answer may well say "no alarms" about a healthy loop).
COULD_NOT = (
    "could not find",
    "couldn't find",
    "not found",
    "does not exist",
    "doesn't exist",
    "no access",
    "cannot access",
    "can't access",
    "não encontr",
    "não consegui",
    "não existe",
    "sem acesso",
)
MIN_ANSWER = 40

# What the person says when a work first asks something ("What process should the model
# represent?"), by work id; any other work with a question gets the generic answer.
ASK_ANSWERS = {
    "new-model": "A water tank whose level is controlled by an inlet valve (a PI controller).",
    "dashboards-find": "The levels and flows of the first unit you find.",
    "dashboard-plan": "The levels and flows of the first unit you find.",
    "report-plan": "The shift supervisors: how the first unit you find ran over the shift.",
}
GENERIC_ASK = "The first one you can find."
NO_QUESTIONS = "Propose it now with these values; do not ask me anything else."

# The fields a create work's question gives, by the object it creates, and the words the
# proposal must carry back (field, word). An object not listed gets sensible values.
CREATE_DETAILS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "action": (
        "Title: Check the valve stiction of {subject}. Priority: high. Due 2026-12-01. "
        "It is about {ref}.",
        [("title", "stiction"), ("priority", "high")],
    ),
    "event": (
        "Title: Turnaround review. Starts 2026-12-01 at 09:00, ends at 10:00 the same day.",
        [("title", "turnaround")],
    ),
    "asset": (
        "Tag: EVAL-PUMP-01. Name: Evaluation pump. Type: equipment. A pump used only to check "
        "the assistant.",
        [("name", "pump")],
    ),
    "block": (
        "Name: Rate of change. It computes the rate of change of its input per minute. Input "
        "x: the signal. Output rate: the change per minute. No parameters. Code: def run("
        "inputs, params, ctx): x = inputs['x']; return {{'rate': x.diff() * 60}}.",
        [("name", "rate")],
    ),
    "rule": (
        "Name: High level alarm. Kind: high. Signal: a level signal of this plant (find one "
        "with search_signals). Limit: a little above the highest value it reached last week. "
        "Priority: high. Cause: the level ran above its usual range.",
        [("name", "high"), ("kind", "high")],
    ),
    "algorithm": (
        "Name: Oscillation check. It works on control loops and flags the loops whose PV "
        "oscillates. Start from scratch.",
        [("name", "oscillation")],
    ),
}
GENERIC_CREATE = "Use sensible values for every required field."

# The pages whose subject an evaluation can read from the platform's API, by page id.
SubjectFinder = Callable[[Reader], tuple[str, str] | None]


def _list(read: Reader, path: str, values: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    status, payload = read("GET", path, values or {})
    if status >= 400 or not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _asset(read: Reader) -> tuple[str, str] | None:
    """An asset that has signals (equipment first), as (ref, name)."""

    items = _list(read, "/api/v1/assets")
    items.sort(key=lambda item: (not item.get("signals"), item.get("kind") != "equipment"))
    for item in items:
        asset_id = item.get("id") or item.get("asset_id")
        if asset_id and item.get("kind") != "site":
            return f"asset:{asset_id}", str(item.get("name") or asset_id)
    return None


def _loop(read: Reader) -> tuple[str, str] | None:
    for item in _list(read, "/api/v1/assets", {"kind": "loop"}):
        asset_id = item.get("id") or item.get("asset_id")
        if asset_id:
            return f"asset:{asset_id}", str(item.get("name") or asset_id)
    return None


def _signal(read: Reader) -> tuple[str, str] | None:
    items = [item for item in _list(read, "/api/v1/signals", {"q": ""}) if item.get("id")]
    items.sort(key=lambda item: (item.get("kind") != "number", ".pv" not in item["id"].lower()))
    if not items:
        return None
    return f"signal:{items[0]['id']}", str(items[0].get("name") or items[0]["id"])


def _alarm(read: Reader) -> tuple[str, str] | None:
    """The subject of an alarm Alarms published (its signal or asset)."""

    for item in _list(read, "/api/v1/results", {"app": "alarmcraft"}):
        subject = str(item.get("subject") or "")
        if subject.startswith(("asset:", "signal:")):
            return subject, subject.split(":", 1)[1]
    return _signal(read)


def _run(read: Reader) -> tuple[str, str] | None:
    for item in _list(read, "/api/v1/runs"):
        app, run_id = item.get("app"), item.get("run_id") or item.get("id")
        if app and run_id:
            return f"run:{app}/{run_id}", str(run_id)
    return None


def _app_object(app: str, kind: str) -> SubjectFinder:
    """The first of an app's objects of ``kind`` (View's dashboards and reports), as (ref, name)."""

    def find(read: Reader) -> tuple[str, str] | None:
        status, payload = read("GET", f"/api/v1/apps/{app}/objects/{kind}", {})
        items = payload.get("items") if status < 400 and isinstance(payload, dict) else None
        for item in items or []:
            if isinstance(item, dict) and item.get("id"):
                return f"{kind}:{item['id']}", str(item.get("name") or item["id"])
        return None

    return find


def _action(read: Reader) -> tuple[str, str] | None:
    for item in _list(read, "/api/v1/actions"):
        action_id = item.get("action_id") or item.get("id")
        if action_id:
            return f"action:{action_id}", str(item.get("title") or action_id)
    return None


SUBJECTS: dict[str, SubjectFinder] = {
    "processcraft:asset": _asset,
    "processcraft:action": _action,
    "linkcraft:loop": _loop,
    "linkcraft:subject-history": _loop,
    "linkcraft:run": _run,
    "histcraft:point": _signal,
    "alarmcraft:alarm": _alarm,
    "dashcraft:dashboard": _app_object("dashcraft", "dashboard"),
    "dashcraft:report": _app_object("dashcraft", "report"),
}
# Pages about one object the platform's API does not list (an app's own): left out.
OBJECT_PAGES = {
    "linkcraft:block",
    "linkcraft:algorithm",
    "linkcraft:schedule",
    "linkcraft:execution-group",
    "modelcraft:model",
}


def _words(text: str) -> str:
    return (text or "").lower()


def ask_check(subject: tuple[str, str] | None) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        text = _words(answer["text"])
        if len(text.strip()) < MIN_ANSWER:
            return False, "the answer is too short to be one"
        if any(words in text for words in COULD_NOT):
            return False, "it says it could not read what the page is about"
        reads = [step for step in answer.get("steps") or [] if step.get("state") == "ok"]
        if not reads:
            return False, "it answered without reading anything with its tools"
        if subject is not None:
            ref, name = subject
            short = ref.split(":", 1)[1].split("/")[-1].split(":")[-1]
            if not any(_words(term) in text for term in (name, short) if term):
                return False, f"it does not name the page's subject ({name})"
        return True, f"read with {len(reads)} tool call(s) and answered about the page"

    return check


def create_check(expected: list[tuple[str, str]]) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    def check(answer: dict[str, Any]) -> tuple[bool, str]:
        proposals = answer.get("proposals") or []
        if not proposals:
            return False, "it did not propose the object (no card)"
        fields = proposals[-1].get("fields") or {}
        missing = [
            f"{key} with '{word}'"
            for key, word in expected
            if word not in _words(" ".join(map(str, _as_list(fields.get(key)))))
        ]
        if missing:
            return False, f"the card lacks {', '.join(missing)}"
        return True, f"proposed a card with {len(fields)} field(s) PlantCraft accepts"

    return check


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _question(work: Work, subject: tuple[str, str] | None) -> tuple[str, list[tuple[str, str]]]:
    spec = work.spec
    text = spec.title
    if spec.ask:
        text += "\n" + ASK_ANSWERS.get(spec.id, GENERIC_ASK)
    if spec.kind != "create":
        return text, []
    template, expected = CREATE_DETAILS.get(spec.object, (GENERIC_CREATE, []))
    ref, name = subject or ("", "the page's subject")
    details = template.format(subject=name, ref=ref or "nothing in particular")
    return f"{text}\n{details}\n{NO_QUESTIONS}", expected


def build_work_cases(read: Reader, works: WorkRegistry) -> tuple[list[Case], list[str]]:
    """One case per work offered to an administrator, and the works left out (no object)."""

    cases: list[Case] = []
    skipped: list[str] = []
    found: dict[str, tuple[str, str] | None] = {}
    for work in works.all():
        if not work.offered_to("admin"):
            continue
        page = work.pages()[0]
        subject: tuple[str, str] | None = None
        if page in OBJECT_PAGES:
            skipped.append(work.key)
            continue
        if page in SUBJECTS:
            if page not in found:
                found[page] = SUBJECTS[page](read)
            subject = found[page]
            if subject is None:
                skipped.append(work.key)
                continue
        question, expected = _question(work, subject)
        app, page_id = page.split(":", 1)
        cases.append(
            Case(
                f"work:{work.key}",
                work.spec.title,
                question,
                (
                    "A card with the object's fields"
                    if work.spec.kind == "create"
                    else "An answer that reads the plant and keeps to the page"
                ),
                create_check(expected) if work.spec.kind == "create" else ask_check(subject),
                work=work.key,
                page={
                    "page": page,
                    "subject": subject[0] if subject else "",
                    "place": f"{app} › {page_id}",
                },
            )
        )
    return cases, skipped
