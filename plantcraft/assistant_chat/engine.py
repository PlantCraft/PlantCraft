"""The assistant answering in a person's chat: a language model with read-only tools.

The tools are the read-only MCP server's (``plantcraft/assistant_access/mcp.py``): each one is
a read of API v1, made with a token issued for the person who asked, at that moment. So the
model sees exactly what that person may see, a person who lost access stops at once, nothing
writes, and every tool call is in the audit log. ``show_chart`` is the chat's own tool: it reads
the series the same way and draws them for the person; the model only gets their statistics
back, so a chart never shows a value the model made up.

Answers are written in the background, by a fixed number of workers (``PLANTCRAFT_ASSISTANT_WORKERS``,
4 by default); a person has one answer being written at a time and a daily number of answers
(``PLANTCRAFT_ASSISTANT_DAILY``, 300 by default). The model is the installation's (Settings ›
Language model) or a specialist's, and models stay off unless an administrator turned them on.

This module puts ``ChatEngine`` together: its workers, who answers, and asking and answering.
The rest lives by subject: ``assistant_chat.engine_common`` (sizes, settings and errors),
``assistant_chat.toolbox`` (the tools the model is given and the reads they may make),
``assistant_chat.charts`` (the series a chart draws), ``assistant_chat.answer_text`` (the
answer's language, its citations and what the history gives the model), and the engine's
methods in the mixins ``engine_tools.ToolCalls``, ``engine_evals.Evaluation`` and
``engine_prompt.SystemPrompt``. The names other modules import from here stay importable from
here.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime
from typing import Any

from plantcraft.assistant_access.app_tools import AppTool, AppTools, refs_named
from plantcraft.assistant_chat import MAX_TEXT, ChatStore
from plantcraft.assistant_chat.answer_text import (
    CITE,
    CREATED_CLAIM,
    ENGLISH_WORDS,
    PORTUGUESE_WORDS,
    PREPARED,
    TOOL_TEXT_LINE,
    _last_question,
    cites_in,
    history_for_model,
    language_of,
    linked_citations,
    prefetched_turns,
    prepared_not_created,
    without_tool_text,
)
from plantcraft.assistant_chat.charts import (
    _iso,
    _iso_local,
    _stats,
    _when,
    signal_label,
    signal_of,
    unit_of,
)
from plantcraft.assistant_chat.demo import (
    PAUSING,
    DemoLimits,
    DemoQuestions,
    clean_answer,
    demo_assistant,
    failure_kind,
    is_visit,
    unavailable,
)
from plantcraft.assistant_chat.engine_common import (
    ANSWER_LANGUAGE,
    CHART,
    CHART_MODES,
    CHART_POINTS,
    CHART_SIGNALS,
    FUTURE_SLACK,
    HELP,
    HISTORY,
    LOGGER,
    MAX_REFS,
    PREFETCH_MIN,
    ROUNDS,
    STREAM_SECONDS,
    TOOL_TEXT,
    Reader,
    Refused,
    _env_int,
    _usage,
    chart_mode,
)
from plantcraft.assistant_chat.engine_evals import Evaluation
from plantcraft.assistant_chat.engine_prompt import SystemPrompt
from plantcraft.assistant_chat.engine_tools import ToolCalls
from plantcraft.assistant_chat.evals import EvalStore
from plantcraft.assistant_chat.toolbox import (
    HelpIndex,
    HelpRead,
    ReadBudget,
    _line,
    as_lists,
    chart_tool,
    fit,
    help_tool,
    read_help,
    reads_of,
    refs_of,
    summary,
    tool_title,
    tools,
)
from plantcraft.assistant_works import CREATE, PROPOSE, WorkRegistry, create_tools
from plantcraft.config import plant_timezone
from plantcraft.db import utc_text
from plantcraft.i18n import current_language, reset_language, set_language, t

# The names other modules import from here, from before the split.
__all__ = [
    "ANSWER_LANGUAGE",
    "CHART",
    "CHART_MODES",
    "CHART_POINTS",
    "CHART_SIGNALS",
    "CITE",
    "CREATED_CLAIM",
    "ENGLISH_WORDS",
    "FUTURE_SLACK",
    "HELP",
    "HISTORY",
    "HelpIndex",
    "HelpRead",
    "LOGGER",
    "MAX_REFS",
    "PORTUGUESE_WORDS",
    "PREFETCH_MIN",
    "PREPARED",
    "ROUNDS",
    "ReadBudget",
    "Reader",
    "Refused",
    "STREAM_SECONDS",
    "TOOL_TEXT",
    "TOOL_TEXT_LINE",
    "_env_int",
    "_iso",
    "_iso_local",
    "_last_question",
    "_line",
    "_stats",
    "_usage",
    "_when",
    "as_lists",
    "chart_mode",
    "chart_tool",
    "cites_in",
    "fit",
    "help_tool",
    "history_for_model",
    "language_of",
    "linked_citations",
    "prefetched_turns",
    "prepared_not_created",
    "read_help",
    "reads_of",
    "refs_of",
    "signal_label",
    "signal_of",
    "summary",
    "tool_title",
    "tools",
    "unit_of",
    "without_tool_text",
]


class ChatEngine(Evaluation, ToolCalls, SystemPrompt):
    def __init__(
        self,
        store: ChatStore,
        specialist_chat: Any,
        audit: Any,
        users: Any,
        evals: EvalStore | None = None,
        help_docs: tuple[HelpIndex, HelpRead] | None = None,
    ):
        self.store = store
        # A public demo's visits' questions and what each answer spent (assistant_chat.demo).
        self.demo_questions = DemoQuestions(store.db)
        self.demo_limits = DemoLimits()
        self.evals = evals
        self.help_docs = help_docs
        # The specialists' store and how a profile's model is made (``model_factory``, which
        # tests replace): one place decides which model answers.
        self.specialist_chat = specialist_chat
        self.audit = audit
        self.users = users
        self.workers = _env_int("PLANTCRAFT_ASSISTANT_WORKERS", 4, 1, 32)
        self.daily = _env_int("PLANTCRAFT_ASSISTANT_DAILY", 300, 1, 100_000)
        # What the assistant reads for one person: signals a day, and signals in one answer
        # past which the audit log flags a possible extraction (B13, 2026-10-31).
        self.reads = ReadBudget(
            audit, _env_int("PLANTCRAFT_ASSISTANT_DAILY_READS", 2_000, 1, 10_000_000)
        )
        self.bulk_signals = _env_int("PLANTCRAFT_ASSISTANT_BULK_SIGNALS", 60, 1, 100_000)
        self.executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="assistant")
        self._futures: set[Future] = set()
        self._lock = threading.Lock()
        # Held while a question is checked against the limits and its answer's row is added.
        self._asking = threading.Lock()
        # The works of every page (assistant_works): the runtime sets the suite's registry.
        self.works: WorkRegistry = WorkRegistry()
        # The tools the installed apps add (assistant_access.app_tools): the runtime sets them.
        self.app_tools: AppTools = AppTools()

    def drain(self, timeout: float | None = None) -> None:
        """Wait for the answers being written (tests, shutdown)."""

        with self._lock:
            futures = list(self._futures)
        wait(futures, timeout=timeout)

    def _forget(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    # Who answers

    def _allowed(self) -> bool:
        """Models are allowed in this installation (``PLANTCRAFT_LLM``, not a public demo)."""

        return bool(self.specialist_chat.store.settings()["allowed"])

    def _default(self) -> Any:
        """The assistant's model: its own choice in Settings › Language models, or the default."""

        found = self.specialist_chat.store.use_model("assistant")
        if found is None:
            return None
        return self.specialist_chat.model_factory(
            found["key"],
            provider=found["kind"],
            model=found["name"],
            endpoint=found["endpoint"],
            reasoning=found["reasoning"],
        )

    def profiles(self) -> list[dict[str, Any]]:
        """Who a chat can be with: the assistant (the installation's model) and each active
        specialist that has a model."""

        store = self.specialist_chat.store
        items = [
            {
                "id": "",
                "name": t("Assistant"),
                "subject": t("Writing, translating, explaining and the plant's data."),
                "ready": store.use_model("assistant") is not None,
            }
        ]
        for profile in store.list(include_inactive=False):
            ready = bool(self._allowed() and profile["model"]["ready"])
            if profile["model"]["source"] == "off":
                continue
            items.append(
                {
                    "id": profile["username"],
                    "name": profile["display_name"],
                    "subject": profile["subject"],
                    "ready": ready,
                }
            )
        return items

    def status(self) -> dict[str, Any]:
        profiles = self.profiles()
        if not self._allowed():
            reason = t("Language models are turned off in this installation.")
        elif not any(item["ready"] for item in profiles):
            reason = t(
                "No language model is set up yet. An administrator connects one in Settings, Language model."
            )
        else:
            reason = ""
        return {
            "available": not reason,
            # False: models are forbidden here, so pages do not offer the assistant at all.
            "allowed": self._allowed(),
            "reason": reason,
            "profiles": profiles,
            "daily_limit": self.daily,
            "charts": chart_mode(),
        }

    def _model(self, profile_id: str) -> tuple[Any, str]:
        """The model and the extra instructions of a chat's profile."""

        if not profile_id:
            return self._default(), ""
        profile = self.specialist_chat.store.get(profile_id)
        if profile is None or not profile["active"]:
            return None, ""
        instructions = profile.get("instructions") or ""
        heading = f"You answer as {profile['display_name']}, a specialist in: {profile['subject']}."
        return self.specialist_chat.model_for(profile), f"{heading}\n{instructions}".strip()

    # Asking

    def ask(
        self,
        chat: dict[str, Any],
        username: str,
        text: str,
        reader: Reader,
        apps: set[str] | None = None,
        level: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Keep the person's question and start writing the answer; both messages back.

        ``apps``: the apps whose results, events and runs the person may read (the others' are
        taken out of every tool answer, ``mcp.only_apps``)."""

        clean = text.strip()
        if not clean:
            raise Refused(t("Write a question."), 422)
        if len(clean) > MAX_TEXT:
            raise Refused(t("A question has {count} characters at most.", count=MAX_TEXT), 422)
        model, _ = self._model(chat["profile"])
        if model is None:
            raise Refused(
                self.status()["reason"] or t("This chat's specialist has no model now."), 409
            )
        # Whose answers these are: the person's, or a public demo visit's own (its chats belong to
        # ``<visitor>#visit:<id>``, assistant_chat.demo), so one visit never waits for another.
        owner = chat.get("username") or username
        # The checks and the answer's row in one step: twenty questions sent at once were three
        # answers written at once (test battery, 2026-11-01).
        with self._asking:
            if self.store.working(owner):
                raise Refused(t("Wait for the answer being written to finish."), 409)
            # The day is the plant's (PLANTCRAFT_TIMEZONE); stored times are UTC text.
            since = datetime.now(plant_timezone()).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if self.store.answers_since(owner, utc_text(since)) >= self.daily:
                raise Refused(
                    t("You reached today's {count} answers. Ask again tomorrow.", count=self.daily),
                    429,
                )
            question = self.store.add(chat["chat_id"], "user", clean)
            return question, self._start(chat, username, reader, apps, level)

    def retry(
        self,
        chat: dict[str, Any],
        username: str,
        reader: Reader,
        apps: set[str] | None = None,
        level: str | None = None,
    ) -> dict[str, Any]:
        """Answer the last question again, after an answer that failed (a lost connection, a
        model that timed out): the failed answer goes, the question stays."""

        messages = self.store.messages(chat["chat_id"])
        if not messages or messages[-1]["role"] != "assistant" or messages[-1]["state"] != "failed":
            raise Refused(t("Only an answer that failed is asked again."), 409)
        with self._asking:
            if self.store.working(chat.get("username") or username):
                raise Refused(t("Wait for the answer being written to finish."), 409)
            self.store.remove_message(messages[-1]["message_id"])
            return self._start(chat, username, reader, apps, level)

    def _start(
        self,
        chat: dict[str, Any],
        username: str,
        reader: Reader,
        apps: set[str] | None,
        level: str | None,
    ) -> dict[str, Any]:
        answer = self.store.add(
            chat["chat_id"], "assistant", "", state="working", meta={"queued": True}
        )
        language = current_language()
        future = self.executor.submit(
            self._answer, chat, username, answer["message_id"], reader, language, apps, level
        )
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget)
        return answer

    def run(
        self,
        chat: dict[str, Any],
        username: str,
        history: list[dict[str, Any]],
        reader: Reader,
        apps: set[str] | None = None,
        on_step: Callable[[list, list, list], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        level: str | None = None,
    ) -> dict[str, Any]:
        """One answer to ``history`` (its last turn is the person's): the text, the steps, the
        charts, the references read and the model's name. Nothing is kept here; ``on_step``
        sees the steps, charts and references as they grow (the chat keeps them; the
        evaluation, ``evals.py``, does not)."""

        steps: list[dict[str, Any]] = []
        charts: list[dict[str, Any]] = []
        refs: list[str] = []
        proposals: list[dict[str, Any]] = []
        # The passages the apps' tools numbered ("cite": 1, "url": ...): the answer's [1] opens it.
        cited: dict[int, str] = {}
        work = self.work_of(chat)
        # A public demo visit's chat only asks: no card that creates, fewer rounds of reads.
        demo = demo_assistant() if is_visit(chat.get("username")) else None
        if demo is not None:
            level = None
            if work is not None and work.spec.kind == "create":
                work = None
            # The chat's last turns only, starting with a question.
            history = history[-demo.history :]
            while history and history[0].get("role") != "user":
                history = history[1:]
        offered = tools(self.help_docs is not None)
        # The apps' own read-only tools (documents, ...), for the apps this person may open.
        added = {tool.name: tool for tool in self.app_tools.for_apps(apps)}
        offered.extend(
            {
                "name": name,
                "description": tool.tool().description,
                "input_schema": tool.tool().describe()["inputSchema"],
            }
            for name, tool in added.items()
        )
        if work is not None and work.spec.kind == "create":
            offered.append(work.tool())
        # A chat started from no work proposes whatever the person may create (``level``).
        creatable = (
            create_tools(self.works.creatable(level, apps)) if (work is None and level) else {}
        )
        offered.extend(tool for _work, tool in creatable.values())
        shown = on_step or (lambda *_: None)
        model, instructions = self._model(chat.get("profile") or "")
        if model is None:
            raise RuntimeError(t("This chat's specialist has no model now."))
        if hasattr(model, "rounds"):
            model.rounds = ROUNDS if demo is None else demo.rounds
        if demo is not None:
            # A visitor does not wait minutes: the answer has its seconds, each call fewer.
            if hasattr(model, "deadline"):
                model.deadline = demo.seconds
            if isinstance(getattr(model, "timeout", None), (int, float)):
                model.timeout = min(model.timeout, demo.call_seconds)
        if on_text is not None and hasattr(model, "on_text"):
            model.on_text = on_text

        def tool(name: str, arguments: dict[str, Any]) -> Any:
            if demo is not None and len(steps) >= demo.tool_calls:
                raise RuntimeError(
                    t("No more reads in this answer: answer with what was already read.")
                )
            # Every kind's create tool is one step for the person: "Prepare the card".
            shown_name = CREATE if name in creatable else name
            title = added[name].title if name in added else tool_title(shown_name)
            step = {"tool": shown_name, "title": title, "summary": ""}
            step["state"] = "running"
            steps.append(step)
            shown(steps, charts, refs)
            try:
                if name == PROPOSE and work is not None and work.spec.kind == "create":
                    value = self._propose(work, arguments, proposals, step, chat, username)
                elif name in creatable:
                    value = self._propose(
                        creatable[name][0], arguments, proposals, step, chat, username
                    )
                else:
                    value = self._tool(
                        name, arguments, reader, charts, refs, step, chat, username, apps
                    )
                    if name in added:
                        cited.update(cites_in(value))
                # A card the check refused is no card: the step says so, with why.
                refused = isinstance(value, dict) and value.get("ok") is False
                step["state"] = "error" if refused else "ok"
                if refused:
                    step["error"] = "; ".join(value.get("problems") or [])[:300]
                return value
            except Exception as exc:
                step["state"] = "error"
                step["error"] = str(exc)[:300]
                raise
            finally:
                shown(steps, charts, refs)

        asked = _last_question(history)
        # The apps' tools that ask for each question (``prefetch``): read before the model
        # answers, so it starts from what they hold instead of having to pick them.
        prefetched: list[tuple[AppTool, dict[str, Any], Any]] = []
        if not (work is not None and work.spec.kind == "create"):
            prefetched = self._prefetch(
                [item for item in added.values() if item.prefetch],
                asked,
                reader,
                steps,
                lambda: shown(steps, charts, refs),
                chat,
                username,
                apps,
            )
        for _item, _arguments, value in prefetched:
            cited.update(cites_in(value))
        try:
            text = model.answer(
                self.system(
                    chat,
                    username,
                    instructions,
                    work,
                    asked=asked,
                    app_tools=list(added.values()),
                    prefetched=[item for item, _, _ in prefetched],
                    creatable=creatable,
                ),
                history + prefetched_turns(prefetched),
                tool,
                offered,
            )
            text = linked_citations(without_tool_text(text), cited)
            if demo is not None:
                text = clean_answer(text, demo.max_answer)
            if proposals:
                text = prepared_not_created(text)
            # What was read before the model answered is a source when the answer used it.
            for _item, _arguments, value in prefetched:
                for ref in refs_named(value, text):
                    if ref not in refs:
                        refs.append(ref)
            if not text and not (charts or proposals):
                raise RuntimeError(t("The model did not finish this answer. Try again."))
        except Exception as exc:
            exc.steps, exc.charts, exc.refs = steps, charts, refs  # type: ignore[attr-defined]
            exc.usage = _usage(model)  # type: ignore[attr-defined]
            raise
        return {
            "text": text,
            "steps": steps,
            "charts": charts,
            "refs": refs[:MAX_REFS],
            "model": getattr(model, "label", ""),
            "proposals": proposals,
            "usage": _usage(model),
        }

    def _answer(
        self,
        chat: dict[str, Any],
        username: str,
        message_id: int,
        reader: Reader,
        language: str,
        apps: set[str] | None = None,
        level: str | None = None,
    ) -> None:
        token = set_language(language)
        began = time.monotonic()
        try:
            self.store.update(message_id, meta={"queued": False})
            history = history_for_model(
                [
                    item
                    for item in self.store.messages(chat["chat_id"])
                    if item["message_id"] < message_id
                ]
            )

            def shown(steps: list, charts: list, refs: list) -> None:
                self.store.update(message_id, steps=steps, charts=charts, refs=refs[:MAX_REFS])

            # The text as the model writes it ("streaming da mensagem"),
            # kept a few times a second for the page that polls; each call starts from "".
            written = {"at": 0.0}

            def writing(text: str) -> None:
                now = time.monotonic()
                if text and now - written["at"] < STREAM_SECONDS:
                    return
                written["at"] = now
                self.store.update(message_id, text=text)

            done = self.run(chat, username, history, reader, apps, shown, writing, level)
            visit = is_visit(chat.get("username"))
            self.store.update(
                message_id,
                text=done["text"],
                state="done",
                steps=done["steps"],
                charts=done["charts"],
                refs=done["refs"],
                meta={
                    # A demo visitor is not shown the model's name under every answer: it says
                    # nothing to them (2026-11-03); the demo's stats keep what answers spent.
                    "model": "" if visit else done["model"],
                    "queued": False,
                    "proposals": done["proposals"],
                    "usage": done["usage"],
                },
            )
            if visit:
                self.demo_questions.answered(
                    chat["username"], "done", done["usage"], seconds=time.monotonic() - began
                )
        except Exception as exc:
            LOGGER.warning("The assistant could not answer in chat %s: %s", chat["chat_id"], exc)
            visit = is_visit(chat.get("username"))
            why = failure_kind(exc)
            if visit and why in PAUSING:
                self.demo_limits.pause(PAUSING[why])
            self.store.update(
                message_id,
                # A visitor reads a plain sentence, never the service's error (it names keys
                # and settings only the installation's administrator can change).
                text=unavailable()
                if visit
                else t("The assistant could not answer: {error}", error=str(exc)[:300]),
                state="failed",
                steps=getattr(exc, "steps", None),
                charts=getattr(exc, "charts", None),
                refs=(getattr(exc, "refs", None) or [])[:MAX_REFS] or None,
                meta={"queued": False, "usage": getattr(exc, "usage", None) or {}},
            )
            if visit:
                self.demo_questions.answered(
                    chat["username"],
                    "failed",
                    getattr(exc, "usage", None) or {},
                    seconds=time.monotonic() - began,
                    failure=why,
                )
        finally:
            reset_language(token)
