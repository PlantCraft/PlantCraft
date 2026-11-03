"""The words of an answer: the language to answer in, tool calls a small model wrote as text,
"created" said of what was only prepared, citations made links, and the history the model
reads."""

from __future__ import annotations

import json
import re
from typing import Any

from plantcraft.assistant_chat.engine_common import HISTORY, TOOL_TEXT

# Words that mark a language in a short question; words both languages write ("a", "do", "no",
# "as", "e") are in neither list. "What dead band was measured on FV-1003?" was answered in
# Portuguese, the asker's settings, when two English words were needed (evaluation 2026-10-27).
ENGLISH_WORDS = frozenset(
    "the which what who whom whose is are was were be been of and how why when where does did "
    "this that these those with from most since show my all any there an in on at for to it "
    "its should can could would will must have has had i you we they your our their if then than "
    "before after about into over under between during until while without not or but also only "
    "just more much many often last first each every keep kept tell give list find explain".split()
)
PORTUGUESE_WORDS = frozenset(
    "o os que qual quais é são de da dos das como por quando onde com mais desde mostre meu "
    "minha meus minhas há em na esta este isso um uma uns umas para pela pelo pelos pelas não "
    "foi foram está estão estava tem têm ter fazer faz deve devem pode podem quem porque sobre "
    "ao aos à às nos nas seu sua seus suas essa esse essas esses aquele aquela já ainda também "
    "só muito muitos qual quanto quantos quantas ontem hoje semana depois antes entre sem mas "
    "ou se então mim eu você vocês nós ele ela eles elas lhe lista mostrar diga explique".split()
)


def language_of(text: str) -> str:
    """English or Portuguese when a message clearly is one of them, else empty."""

    lowered = text.lower()
    words = re.findall(r"[a-zà-ú]+", lowered)
    english = sum(word in ENGLISH_WORDS for word in words)
    portuguese = sum(word in PORTUGUESE_WORDS for word in words) + 2 * len(
        re.findall(r"[ãõçáéíóúâêô]", lowered)
    )
    if english >= 1 and english > 2 * portuguese:
        return "English"
    if portuguese >= 1 and portuguese > 2 * english:
        return "Portuguese"
    return ""


def _last_question(history: list[dict[str, Any]]) -> str:
    return (
        str(history[-1].get("content") or "")
        if history and history[-1].get("role") == "user"
        else ""
    )


# A small model sometimes writes its tool call as text ("to=functions.get_asset {...}").
TOOL_TEXT_LINE = re.compile(r"to=functions\.|<\|(?:start|end|call|channel|message)\|>")


def prefetched_turns(done: list[tuple[Any, dict[str, Any], Any]]) -> list[dict[str, Any]]:
    """What PlantCraft read before the model answered, as the model's own tool calls and their
    answers (the same blocks its loop adds), after the person's question."""

    if not done:
        return []
    calls = [
        {"type": "tool_use", "id": f"prefetch_{number}", "name": item.name, "input": arguments}
        for number, (item, arguments, _value) in enumerate(done, 1)
    ]
    answers = [
        {
            "type": "tool_result",
            "tool_use_id": f"prefetch_{number}",
            "content": json.dumps(value, ensure_ascii=False, default=str)[:TOOL_TEXT],
        }
        for number, (_item, _arguments, value) in enumerate(done, 1)
    ]
    return [{"role": "assistant", "content": calls}, {"role": "user", "content": answers}]


# "I created an action" after a proposal: the card only prepared it (D11, 2026-10-31). The
# person creates it with the card's button, so the answer says it was prepared.
CREATED_CLAIM = re.compile(
    r"\b(I|We)( have|'ve)? (created|added|registered)\b"
    r"|\b(criei|adicionei|registrei)\b",
    re.IGNORECASE,
)
PREPARED = {
    "created": "prepared",
    "added": "prepared",
    "registered": "prepared",
    "criei": "preparei",
    "adicionei": "preparei",
    "registrei": "preparei",
}


def prepared_not_created(text: str) -> str:
    """An answer that proposed objects never claims it made them: "I created" becomes "I
    prepared" (the person still has to press the card's button)."""

    def swap(match: re.Match[str]) -> str:
        word = match.group(0)
        last = word.rsplit(" ", 1)[-1]
        new = PREPARED[last.lower()]
        if last[:1].isupper():
            new = new.capitalize()
        return word[: len(word) - len(last)] + new

    return CREATED_CLAIM.sub(swap, text)


def without_tool_text(text: str) -> str:
    """The answer without lines that are a tool call written as text."""

    if not text or not TOOL_TEXT_LINE.search(text):
        return text
    kept = [line for line in text.splitlines() if not TOOL_TEXT_LINE.search(line)]
    return "\n".join(kept).strip()


CITE = re.compile(r"(?<![\[\]\w])\[(\d{1,2})\](?![(\[])")


def cites_in(payload: Any) -> dict[int, str]:
    """The numbered items of an app's answer (``{"cite": 1, "url": "/doc/documents/..."}``):
    the page each [n] of the answer opens, at the passage."""

    found: dict[int, str] = {}

    def take(value: Any) -> None:
        if isinstance(value, dict):
            cite, url = value.get("cite"), value.get("url")
            if (
                isinstance(cite, int)
                and isinstance(url, str)
                and url.startswith("/")
                and not url.startswith("//")
                and not any(char in url for char in " ()\\")
            ):
                found[cite] = url
            for inner in value.values():
                if isinstance(inner, (dict, list)):
                    take(inner)
        elif isinstance(value, list):
            for item in value:
                take(item)

    take(payload)
    return found


def linked_citations(text: str, cited: dict[int, str]) -> str:
    """Each [n] of the answer as a link to the passage it cites (a citation
    opens the document at that part); a number no tool gave stays as written."""

    if not cited or not text:
        return text

    def link(match: re.Match[str]) -> str:
        url = cited.get(int(match.group(1)))
        return f"[[{match.group(1)}]({url})]" if url else match.group(0)

    return CITE.sub(link, text)


def history_for_model(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The chat as the model reads it: alternating turns that start with the person's.

    An answer that failed is left out; two turns of the same side in a row are joined. A chart
    the assistant drew is named in its turn, so the model knows it was shown. A chat longer than
    ``HISTORY`` turns keeps its opening exchange and its newest turns: the opening often says
    what the chat is about (a limit, a campaign, a unit), and without it a long chat forgets it
    (2026-11-01: the battery's 32-turn chat lost the limit given in its first answer).
    """

    turns: list[dict[str, Any]] = []
    for item in messages:
        if item["role"] == "assistant" and item["state"] != "done":
            continue
        text = item["text"]
        if item["role"] == "assistant" and item.get("charts"):
            names = "; ".join(
                f"{chart.get('title') or ', '.join(s['signal'] for s in chart.get('series', []))} "
                f"({chart.get('start')} to {chart.get('end')})"
                for chart in item["charts"]
            )
            text = f"{text}\n\n[Charts shown to the person: {names}]"
        if turns and turns[-1]["role"] == item["role"]:
            turns[-1]["content"] += f"\n\n{text}"
        else:
            turns.append({"role": item["role"], "content": text})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if len(turns) <= HISTORY:
        return turns
    opening, newest = turns[:2], turns[-(HISTORY - 2) :]
    while newest and newest[0]["role"] != "user":
        newest.pop(0)
    return opening + newest
