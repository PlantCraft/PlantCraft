"""Prompts for an AI assistant: the "Copy as prompt" buttons of the suite.

``docs/design/copy-prompt.md`` says why. A module's API builds a prompt for one of its objects (a
Link method, a Modelica class, the plant map's import format) and the interface puts its text on
the clipboard with ``CopyPrompt`` (``@plantcraft/ui``). Nothing leaves the plant: the person
decides where to paste it.

A prompt is data, answered by ``GET /api/prompts/<kind>/<id>``::

    prompt = Prompt(
        module="Analytics",
        title="Method: Oscillation index",
        subject="an Analytics method: Python code that reads a control loop's signals by role",
        question=QUESTIONS["explain"],
        parts=[code_part("Source (oscillation.py)", source, "python"), json_part("Parameters", schema)],
    )
    return prompt.render()

``render`` gives ``{title, text, parts, omitted, chars}``. ``text`` is what goes on the
clipboard: a header saying what PlantCraft is and which module, the house rules an assistant
follows, the question, then each part as a fenced block. It stays under ``MAX_CHARS``; a part
that does not fit is cut with a note, and the parts after it are named in ``omitted``.

Secrets never enter a prompt: ``json_part`` drops every key that names a password, token, key,
endpoint, URL, host or user name (``scrub``), and the text of every part that is not code goes
through the log redaction (``plantcraft_sdk.server.logs.redact``). Code parts are the shipped
source of the object, kept as is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from plantcraft_sdk.i18n import t
from plantcraft_sdk.server.logs import redact

MAX_CHARS = 30_000
# A part shorter than this after cutting is left out instead (a stub helps nobody).
MIN_PART = 400
# Kept free at the end for the line naming the parts left out.
TAIL = 300
CODE_LANGUAGES = frozenset({"python", "modelica", "sql", "javascript", "typescript"})

# Keys a prompt never carries, wherever they sit in a JSON part.
_SECRET_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|app[_-]?key|private[_-]?key|authorization|"
    r"cookie|credential)",
    re.IGNORECASE,
)
_ENDPOINT_KEY = re.compile(
    r"^(url|uri|endpoint|endpoint_url|server_url|base_url|host|hostname|address|ip|port|"
    r"username|user_name|login|email|dsn|connection|connection_string)$",
    re.IGNORECASE,
)


def _house_rules() -> list[str]:
    return [
        t("PlantCraft only reads the plant: never suggest writing to the control system."),
        t("Methods choose their inputs by signal role (PV, SP, OP...), never by tag."),
        t(
            "Answer in the same format as the parts below (the same language, the same JSON keys), "
            "so the answer can be pasted back into PlantCraft as it is."
        ),
        t("Every change to code comes with a test that shows it works."),
        t(
            "Use only public, citable methods, and say when you are not sure: an inconclusive "
            "answer is better than a confident wrong one, because people act on it in a running plant."
        ),
    ]


@dataclass(frozen=True)
class Part:
    """One piece of context: a label, its text and the language its fence carries."""

    label: str
    content: str
    language: str = "text"

    @property
    def is_code(self) -> bool:
        return self.language in CODE_LANGUAGES


def code_part(label: str, source: str, language: str) -> Part:
    return Part(label, source.strip("\n"), language)


def text_part(label: str, text: str, language: str = "markdown") -> Part:
    return Part(label, redact(text.strip("\n")), language)


def json_part(label: str, value: Any) -> Part:
    """``value`` as indented JSON, with every secret or endpoint key taken out."""

    clean, _removed = scrub(value)
    return Part(label, redact(json.dumps(clean, indent=2, ensure_ascii=False, default=str)), "json")


def scrub(value: Any) -> tuple[Any, list[str]]:
    """``value`` without the keys a prompt never carries, and the paths of the keys removed."""

    removed: list[str] = []

    def walk(item: Any, path: str) -> Any:
        if isinstance(item, dict):
            kept = {}
            for key, inner in item.items():
                name = str(key)
                where = f"{path}.{name}" if path else name
                if _SECRET_KEY.search(name) or _ENDPOINT_KEY.match(name):
                    removed.append(where)
                    continue
                kept[key] = walk(inner, where)
            return kept
        if isinstance(item, (list, tuple)):
            return [walk(inner, f"{path}[{index}]") for index, inner in enumerate(item)]
        return item

    return walk(value, ""), removed


def _fence(content: str) -> str:
    """A fence longer than any run of backticks inside ``content``."""

    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def _cut_note(count: int) -> str:
    return "\n" + t("[cut here: {count} more characters left out]", count=count)


def _block(part: Part, content: str) -> str:
    fence = _fence(content)
    language = "" if part.language == "text" else part.language
    return f"## {part.label}\n\n{fence}{language}\n{content}\n{fence}\n"


@dataclass
class Prompt:
    """A prompt about one object of a module (see the module docstring)."""

    module: str
    title: str
    subject: str
    question: str
    parts: list[Part] = field(default_factory=list)
    # Lines the assistant should know about this object in particular.
    notes: list[str] = field(default_factory=list)

    @property
    def product(self) -> str:
        """``PlantCraft Analytics`` for a module; the platform's own objects say just ``PlantCraft``."""

        return "PlantCraft" if self.module in {"", "PlantCraft"} else f"PlantCraft {self.module}"

    def header(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            t(
                "I work with PlantCraft, an open suite of industrial software for process plants "
                "that runs offline inside the plant. This is about PlantCraft {module}: below is "
                "{subject}.",
                module=self.module,
                subject=self.subject,
            ),
            "",
            t("Rules for your answer:"),
            *(f"- {rule}" for rule in [*_house_rules(), *self.notes]),
            "",
            f"## {t('Question')}",
            "",
            self.question.strip(),
            "",
        ]
        return "\n".join(lines)

    def render(self, max_chars: int = MAX_CHARS) -> dict[str, Any]:
        text = self.header()
        parts: list[dict[str, str]] = []
        omitted: list[str] = []
        for index, part in enumerate(self.parts):
            if omitted:
                omitted.append(part.label)
                continue
            block = _block(part, part.content)
            # Room for the "left out" line when parts follow this one.
            tail = TAIL if index < len(self.parts) - 1 else 0
            room = max_chars - len(text) - 1 - tail
            if len(block) <= room:
                text += "\n" + block
                parts.append({"label": part.label, "kind": part.language, "content": part.content})
                continue
            # The note's length with the largest count it can carry, so the cut part fits.
            longest_note = len(_cut_note(len(part.content)))
            keep = room - len(_block(part, "")) - longest_note - 8
            if keep < MIN_PART:
                omitted.append(part.label)
                continue
            content = part.content[:keep] + _cut_note(len(part.content) - keep)
            text += "\n" + _block(part, content)
            parts.append({"label": part.label, "kind": part.language, "content": content})
            break
        omitted += [part.label for part in self.parts[len(parts) + len(omitted) :]]
        if omitted:
            text += "\n" + t("Left out for length: {parts}.", parts=", ".join(omitted)) + "\n"
        return {
            "title": self.title,
            "text": text,
            "parts": parts,
            "omitted": omitted,
            "chars": len(text),
        }


def question_of(presets: dict[str, str], chosen: str | None, default: str) -> str:
    """The preset ``chosen`` names, or ``default``'s: a free question never comes from the URL."""

    return presets.get(chosen or "", presets[default])
