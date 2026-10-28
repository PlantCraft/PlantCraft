"""The eval set (eval/questions.toml): the search check without a model, the answer check with one."""

from __future__ import annotations

import json
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import chat
from .knowledge import Knowledge
from .llm import Model, ModelError

QUESTIONS = Path(__file__).resolve().parent.parent / "eval/questions.toml"


def load(path: Path = QUESTIONS) -> list[dict]:
    return tomllib.loads(path.read_text(encoding="utf-8"))["question"]


def found_sources(knowledge: Knowledge, question: dict) -> set[str]:
    """The pages the chat would put before the model for this question."""
    return {p.source for p in chat.context_of(knowledge, question["ask"], [])}


def retrieval_misses(knowledge: Knowledge, questions: list[dict]) -> list[str]:
    """Questions none of whose expected pages reach the model."""
    misses = []
    for q in questions:
        expected = set(q.get("sources", []))
        if expected and not expected & found_sources(knowledge, q):
            misses.append(q["id"])
    return misses


@dataclass
class Result:
    id: str
    kind: str
    ask: str
    answer: str
    contact: bool
    sources: list[str]
    problems: list[str] = field(default_factory=list)
    judge: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.problems


def check(question: dict, answer: chat.Answer) -> list[str]:
    text = answer.text.lower()
    problems = []
    for need in question.get("must", []):
        if not any(alt.strip().lower() in text for alt in need.split("|")):
            problems.append(f"missing {need!r}")
    for bad in question.get("must_not", []):
        if bad.lower() in text:
            problems.append(f"has {bad!r}")
    if "contact" in question and question["contact"] != answer.contact:
        problems.append(
            "should offer the contact form" if question["contact"] else "offered the contact form"
        )
    return problems


JUDGE = """You check a website chatbot's answer against the answer the team expects.
Reply with one line: PASS or FAIL, a colon, and at most 20 words of reason.
FAIL when the answer contradicts the expected one, states a fact the expected answer does not
support (a feature, number, price, customer or date), or misses its main point. Wording,
length and extra correct context are fine."""


def judge(model: Model, question: dict, answer: str) -> str:
    prompt = f"Question: {question['ask']}\n\nExpected: {question['expect']}\n\nAnswer: {answer}"
    try:
        return model.complete(JUDGE, [{"role": "user", "content": prompt}], 800).strip()
    except ModelError as exc:
        return f"ERROR: {exc}"


def run(
    model: Model,
    knowledge: Knowledge,
    questions: list[dict],
    docs_url: str,
    judge_model: Model | None = None,
) -> list[Result]:
    results = []
    failures = 0
    for q in questions:
        start = time.monotonic()
        a = chat.answer(model, knowledge, [{"role": "user", "content": q["ask"]}], docs_url)
        r = Result(
            q["id"],
            q["kind"],
            q["ask"],
            a.text,
            a.contact,
            [s.path for s in a.sources],
            check(q, a),
        )
        r.seconds = round(time.monotonic() - start, 1)
        failures = failures + 1 if a.failed else 0
        if failures >= 3:
            raise ModelError("the model stopped answering (3 questions in a row)")
        if judge_model is not None:
            r.judge = judge(judge_model, q, a.text)
            if r.judge.upper().startswith("FAIL"):
                r.problems.append(f"judge: {r.judge}")
        results.append(r)
        print(f"{'ok ' if r.ok else 'BAD'} {r.id:22} {r.seconds:5}s {'; '.join(r.problems)}")
    return results


def report(results: list[Result], questions: list[dict], model_name: str) -> str:
    by_id = {q["id"]: q for q in questions}
    passed = sum(r.ok for r in results)
    lines = [
        f"# Site chat eval: {passed}/{len(results)} passed",
        "",
        f"Model: `{model_name}`. Questions: `site/eval/questions.toml`.",
        "",
        "| Question | Kind | Result | Contact | Sources | Time |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        verdict = "ok" if r.ok else "**" + "; ".join(r.problems).replace("|", "/") + "**"
        lines.append(
            f"| {r.id} | {r.kind} | {verdict} | {'yes' if r.contact else ''} | "
            f"{', '.join(r.sources)} | {r.seconds}s |"
        )
    lines.append("")
    for r in results:
        lines += [
            f"## {r.id}",
            "",
            f"**Q:** {r.ask}",
            "",
            f"**Expected:** {by_id[r.id]['expect']}",
            "",
            "**Answer:**",
            "",
            *[f"> {line}" for line in r.answer.splitlines()],
            "",
        ]
    return "\n".join(lines)


def dump(results: list[Result], path: Path) -> None:
    path.write_text(json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=1))
