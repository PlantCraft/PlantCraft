"""Specialists answering in Messages, only when someone writes to them.

When a person writes in a conversation with a specialist, the specialist replies
in the background: alone with one person it answers every message; in a group it
answers only when mentioned (``@username``). The reply is grounded in what
PlantCraft holds now (assets, actions, and the results, events and runs of the
apps in the specialist's profile).

With a language model turned on in its profile (off by default), the model
answers from that context and may look up more through read-only tools. Without
one, or when the model fails, a script answers the simple questions (an object's
situation, what needs attention, the open actions). Nothing here writes anything
but the specialist's own reply.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime
from typing import Any

from plantcraft.i18n import current_language, reset_language, set_language, t
from plantcraft.messages import ConversationStore
from plantcraft.specialists.facts import SpecialistFacts
from plantcraft.specialists.model import ChatModel
from plantcraft.specialists.profiles import SpecialistStore, models_allowed

LOGGER = logging.getLogger(__name__)

HISTORY = 16
ANSWER_LANGUAGE = {"pt-BR": "Brazilian Portuguese", "en": "English"}

# Requests to change something; a specialist only reads. English or Portuguese.
WRITE_INTENT = re.compile(
    r"\b((change|modify|adjust|increase|decrease|reduce|lower|raise|retune|tune|delete|remove|"
    r"create|close) (the|its|it|a|an|this|that)\b|(put|switch|set) (it |the loop )?(in|to|into) "
    r"(manual|auto)|open the valve|close the valve|"
    r"alter(e|ar|em)|mud(e|ar|em)|ajust(ar|em)|ajuste (o|a|os|as)\b|aument(e|ar)|reduz(a|ir)|"
    r"diminu(a|ir)|sintoniz(e|ar)|ressintoniz(e|ar)|apag(ue|ar)|exclu(a|ir)|cri(e|ar) (uma|a|o)\b|"
    r"coloque em|pass(e|ar) para (manual|autom)|abr(a|ir) a valvula|fech(e|ar) a valvula)",
    re.IGNORECASE,
)
ASK_WORST = re.compile(
    r"\b(worst|priorit|critic|which|summary|overview|status|how are|attention|alert|problem|"
    r"pior|piores|priorid|quais|resumo|situac|como est|panorama|atencao|alerta|problema)",
    re.I,
)
ASK_ACTIONS = re.compile(r"\b(action|pending|task|to-?do|acao|acoes|pendenc|pendente|tarefa)", re.I)

TOOLS = [
    {
        "name": "search_assets",
        "description": "Find assets (units, equipment, control loops) by id, name or description.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_object",
        "description": "Anything by its kind:id reference (asset:FIC-101, action:12, "
        "signal:<source>:<tag>, run:<app>/<id>): its record, the latest results the apps "
        "published about it, open actions and recent events.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
            "additionalProperties": False,
        },
    },
    {
        "name": "result_history",
        "description": "How the apps' results about a subject (a kind:id reference) changed "
        "status over time, oldest first.",
        "input_schema": {
            "type": "object",
            "properties": {"subject": {"type": "string"}},
            "required": ["subject"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_attention",
        "description": "Results of your apps that are not ok, worst first.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 30}},
            "additionalProperties": False,
        },
    },
    {
        "name": "search_knowledge",
        "description": "Search what your apps wrote about their objects: what each protocol "
        "evaluates, its inputs, outputs and how to read them, and the reports of past runs. "
        "Returns refs, titles and openings; read one in full with get_object.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "recent_runs",
        "description": "The latest runs of your apps (newest first), optionally only failed "
        "ones or only those about one subject reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["failed", "done", "running"]},
                "subject": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_open_actions",
        "description": "Open follow-up actions, optionally only those about one reference.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "additionalProperties": False,
        },
    },
]

SYSTEM = """You are {name} (@{username}), a specialist robot of PlantCraft, a platform for process engineers in industrial plants. Your subject: {subject}.

How you work:
- Answer in {language}, direct and short (up to about 180 words); short lists when they help.
- Rely only on the context below and on what the tools return. Never make up numbers. If data is missing, say what is missing.
- You only read and explain. You never change controllers, settings or data, and never create, change or close actions. If asked to, decline politely and offer the evidence so engineering can decide.
- You read what these apps publish: {apps}. You do not see other apps' data.
- The apps explain their own objects in texts ("explained" in the context and in get_object): what a protocol evaluates, what its inputs and outputs mean, instructions for reading it, and run reports. Follow those instructions; use search_knowledge when the question names no object.
- Cite objects as #asset:ID, #action:ID, #signal:SOURCE:TAG or #run:APP/ID; they become links.
- The people talking to you: {people}. Address them by name.
{instructions}
Now: {now}.
Objects cited in the conversation:
{context}"""

ModelFactory = Callable[..., ChatModel]
# (people) -> (the apps they all open, whether they all see an action).
# What people may all read: the apps they open, whether they see an action, and whether a
# subject (``asset:``, ``signal:``) is in their asset scope (docs/asset-scope.md).
Scope = Callable[
    [list[str]],
    tuple[set[str], Callable[[dict[str, Any]], bool], Callable[[str], bool]],
]


def _plain(text: str) -> str:
    """Lowercase without accents, so "valvula" matches "válvula"."""

    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class SpecialistChat:
    def __init__(
        self,
        workspace: Any,
        store: SpecialistStore,
        conversations: ConversationStore,
        app_names: Callable[[], dict[str, str]],
        *,
        model_factory: ModelFactory = ChatModel,
        workers: int = 4,
        scope: Scope | None = None,
    ):
        self.workspace = workspace
        self.store = store
        self.conversations = conversations
        self.app_names = app_names
        self.model_factory = model_factory
        # What the people of a conversation may all read (their apps, the actions they see).
        self.scope = scope
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="specialist")
        self._futures: list[Future] = []
        self._lock = threading.Lock()

    # Who answers -------------------------------------------------------------

    @staticmethod
    def responders(conversation: dict[str, Any], message: dict[str, Any]) -> list[str]:
        members = conversation.get("members") or []
        bots = [item["username"] for item in members if item["kind"] == "specialist"]
        people = [item for item in members if item["kind"] != "specialist"]
        text = message.get("text", "").lower()
        mentioned = [
            name for name in bots if re.search(rf"(?<![\w.]){re.escape('@' + name)}\b", text)
        ]
        if mentioned:
            return mentioned
        return bots if len(people) <= 1 else []

    def handle(
        self, conversation: dict[str, Any], message: dict[str, Any], actor: str
    ) -> list[str]:
        """Start the replies to a person's message; specialists never answer each other."""

        if not self.workspace.users.is_person(actor):
            return []
        started = []
        for name in self.responders(conversation, message):
            self.conversations.set_busy(conversation["conversation_id"], name, True)
            with self._lock:
                self._futures = [future for future in self._futures if not future.done()]
                self._futures.append(
                    self._pool.submit(
                        self._safe_reply,
                        conversation["conversation_id"],
                        name,
                        message["message_id"],
                        current_language(),
                    )
                )
            started.append(name)
        return started

    def drain(self, timeout: float | None = None) -> None:
        with self._lock:
            futures = list(self._futures)
        wait(futures, timeout=timeout)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # The reply -----------------------------------------------------------------

    def _safe_reply(
        self, conversation_id: int, name: str, message_id: int, language: str | None
    ) -> None:
        token = set_language(language)
        try:
            self.reply(conversation_id, name, message_id)
        except Exception:  # never leave "writing…" on screen forever
            LOGGER.exception("The reply of %s in conversation %s failed", name, conversation_id)
            try:
                self.conversations.post(
                    conversation_id,
                    name,
                    t("I could not answer now because of an internal failure. Try again soon."),
                    meta={"writer": "error"},
                )
            except Exception:
                LOGGER.exception("Not even the failure message could be posted")
        finally:
            self.conversations.set_busy(conversation_id, name, False)
            reset_language(token)

    def model_for(self, profile: dict[str, Any]) -> ChatModel | None:
        """The model the profile answers with: the installation's default, a saved provider's
        model or its own."""

        settings = profile["model"]
        if not (models_allowed() and settings["ready"]):
            return None
        if settings["source"] == "provider":
            found = self.store.resolve(settings["provider_id"], settings["name"])
            if found is None:
                return None
            return self.model_factory(
                found["key"],
                provider=found["kind"],
                model=found["name"],
                endpoint=found["endpoint"],
                reasoning=found["reasoning"],
            )
        if settings["source"] == "installation":
            connection = self.store.connection()
            return self.model_factory(
                self.store.connection_key() or "",
                provider=connection["provider"],
                model=connection["name"],
                endpoint=connection["endpoint"],
                reasoning=connection["reasoning"],
            )
        key = self.store.api_key(profile["username"])
        if not key:
            return None
        return self.model_factory(
            key,
            provider=settings["provider"],
            model=settings["name"],
            endpoint=settings["endpoint"],
        )

    def facts(self, profile: dict[str, Any], people: list[str] | None = None) -> SpecialistFacts:
        """What the specialist reads to answer ``people``: its profile's apps that they all open
        and the actions they all see (without a ``scope``, all its profile reads)."""

        if self.scope is None or people is None:
            return SpecialistFacts(self.workspace, profile["apps"], self.app_names())
        apps, sees_action, sees_subject = self.scope(people)
        return SpecialistFacts(
            self.workspace,
            set(profile["apps"]) & apps,
            self.app_names(),
            sees_action,
            sees_subject,
        )

    def reply(self, conversation_id: int, name: str, message_id: int) -> dict[str, Any]:
        profile = self.store.get(name)
        if profile is None or not profile["active"]:
            return self.conversations.post(
                conversation_id,
                name,
                t("I am turned off. An admin can turn me back on in Users, Specialists."),
                meta={"writer": "script"},
            )
        conversation = self.conversations.get(conversation_id) or {}
        message = self.conversations.message(message_id) or {}
        history = self.conversations.messages(conversation_id, limit=HISTORY + 1)
        history = [item for item in history if item["message_id"] <= message_id][-HISTORY:]
        refs = self._conversation_refs(history)
        people = [
            item["username"]
            for item in conversation.get("members") or []
            if item.get("kind") != "specialist"
        ]
        facts = self.facts(profile, people)
        model = self.model_for(profile)
        if model is not None:
            try:
                text = self._model_reply(model, profile, facts, conversation, history, refs)
                posted = self.conversations.post(
                    conversation_id, name, text, meta={"writer": model.label}
                )
                self.store.count_answer(name)
                return posted
            except Exception as exc:
                LOGGER.warning("The language model of %s failed: %s", name, exc)
                text = self.scripted(profile, facts, message, refs)
                text += "\n\n" + t(
                    "(The language model did not answer now; this is the scripted answer.)"
                )
                posted = self.conversations.post(
                    conversation_id, name, text, meta={"writer": "script", "fallback": True}
                )
                self.store.count_answer(name)
                return posted
        posted = self.conversations.post(
            conversation_id,
            name,
            self.scripted(profile, facts, message, refs),
            meta={"writer": "script"},
        )
        self.store.count_answer(name)
        return posted

    @staticmethod
    def _conversation_refs(history: list[dict[str, Any]]) -> list[str]:
        """The objects cited, the latest message's first."""

        found: list[str] = []
        for item in reversed(history):
            for ref in item.get("refs") or []:
                if ref not in found:
                    found.append(ref)
        return found

    # With a language model -----------------------------------------------------

    def _model_reply(
        self,
        model: ChatModel,
        profile: dict[str, Any],
        facts: SpecialistFacts,
        conversation: dict[str, Any],
        history: list[dict[str, Any]],
        refs: list[str],
    ) -> str:
        names = {item["username"]: item["display_name"] for item in conversation.get("members", [])}
        people = [
            item["display_name"]
            for item in conversation.get("members", [])
            if item["kind"] != "specialist"
        ]
        context = []
        for ref in refs[:6]:
            try:
                found = facts.lookup(ref)
            except ValueError:
                found = None
            context.append(f"- {ref}: {found if found is not None else 'not found'}")
        instructions = profile["instructions"].strip()
        system = SYSTEM.format(
            name=profile["display_name"],
            username=profile["username"],
            subject=profile["subject"] or "general process engineering",
            language=ANSWER_LANGUAGE.get(current_language(), "English"),
            apps=", ".join(facts.app_name(app) for app in sorted(facts.apps)) or "none",
            people=", ".join(people) or "someone",
            instructions=f"\nYour own instructions:\n{instructions}\n" if instructions else "",
            now=datetime.now().astimezone().isoformat(timespec="minutes"),
            context="\n".join(context) or "(none)",
        )
        messages: list[dict[str, Any]] = []
        for item in history:
            if item["author"] == profile["username"]:
                role, content = "assistant", item["text"]
            else:
                author = names.get(item["author"]) or item.get("author_name") or item["author"]
                role, content = "user", f"{author}: {item['text']}"
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += "\n\n" + content
            else:
                messages.append({"role": role, "content": content})
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        if not messages or messages[-1]["role"] != "user":
            raise RuntimeError("Nothing to answer.")
        return model.answer(
            system, messages, lambda tool, data: self._tool(facts, tool, data), TOOLS
        )

    @staticmethod
    def _tool(facts: SpecialistFacts, name: str, data: dict[str, Any]) -> Any:
        if name == "search_assets":
            return facts.search_assets(str(data.get("text", "")))
        if name == "get_object":
            found = facts.lookup(str(data.get("ref", "")).strip())
            if found is None:
                raise ValueError("Nothing with that reference, or not in your apps' data.")
            return found
        if name == "result_history":
            return facts.result_history(str(data.get("subject", "")).strip())
        if name == "list_attention":
            return facts.worst(int(data.get("limit") or 10))
        if name == "search_knowledge":
            return facts.search_knowledge(str(data.get("text", "")))
        if name == "recent_runs":
            return facts.recent_runs(
                status=str(data.get("status") or "") or None,
                subject=str(data.get("subject") or "").strip() or None,
            )
        if name == "list_open_actions":
            ref = str(data.get("ref") or "").strip() or None
            return facts.actions(ref)
        raise ValueError(f"Unknown tool: {name}.")

    # Without a language model --------------------------------------------------

    def scripted(
        self,
        profile: dict[str, Any],
        facts: SpecialistFacts,
        message: dict[str, Any],
        refs: list[str],
    ) -> str:
        text = message.get("text", "")
        plain = _plain(text)
        if WRITE_INTENT.search(plain):
            return t(
                "I only read data and explain results: I do not change controllers, settings or "
                "data, nor create or close actions. I can bring the evidence for engineering to "
                "decide; cite the asset with #asset:ID and I will summarize what the apps found."
            )
        lines: list[str] = []
        own = list(message.get("refs") or [])
        for ref in own[:3]:
            lines.extend(self._describe(facts, ref))
        asked_actions = bool(ASK_ACTIONS.search(plain))
        if not own and asked_actions:
            lines.extend(self._actions_text(facts))
        elif not own and ASK_WORST.search(plain):
            lines.extend(self._worst_text(facts))
        if not lines and refs:
            # A follow-up question in a conversation about one object (an app's assistant).
            lines.extend(self._describe(facts, refs[0]))
        if not lines:
            lines.extend(self._help_text(profile, facts))
        return "\n".join(lines).strip()

    def _describe(self, facts: SpecialistFacts, ref: str) -> list[str]:
        try:
            found = facts.lookup(ref)
        except ValueError:
            found = None
        if found is None:
            return [t("I found nothing about #{ref} in the data I can read.", ref=ref)]
        if ref.startswith("action:"):
            owner = found.get("owner_name") or t("no owner")
            # The reference shows as a chip with the action's title.
            return [f"#{ref}: {found['status_label']}, {owner}."]
        if ref.startswith("run:"):
            return self._describe_run(found)
        explained = found.get("explained") or []
        title = found.get("name") or (explained[0]["title"] if explained else ref)
        lines = [f"**{title}** (#{ref})"]
        for item in explained[:1]:
            lines.append(self._opening(item["text"]))
        results = found.get("results") or []
        if results:
            lines.extend(f"- {facts.result_line(item)}" for item in results)
        elif not facts.apps:
            lines.append(t("- No app's data is open to me yet; an admin chooses them."))
        elif not explained:  # an object only explained (a protocol) has no results of its own
            lines.append(t("- None of my apps has published a result about it yet."))
        actions = found.get("open_actions") or []
        if actions:
            lines.append(t("Open actions:"))
            lines.extend(
                f"- #{item['ref']} ({item['owner'] or t('no owner')})" for item in actions[:5]
            )
        return lines

    @staticmethod
    def _opening(text: str, size: int = 700) -> str:
        text = text.strip()
        return text if len(text) <= size else text[:size].rsplit(" ", 1)[0] + " …"

    def _describe_run(self, found: dict[str, Any]) -> list[str]:
        run = found.get("run") or {}
        explained = found.get("explained") or []
        title = run.get("name") or (explained[0]["title"] if explained else found["ref"])
        lines = [f"**{title}** (#{found['ref']})"]
        if run:
            lines.append(
                t("- Status: {status}. {summary}", status=run["status"], summary=run["summary"])
            )
        for item in explained[:1]:
            lines.append(self._opening(item["text"]))
        return lines

    def _worst_text(self, facts: SpecialistFacts) -> list[str]:
        rows = facts.worst(8)
        if not rows:
            return [t("Nothing in my apps' results needs attention now.")]
        lines = [t("What needs attention now, worst first:")]
        for item in rows:
            summary = f": {item['summary']}" if item["summary"] else ""
            lines.append(f"- #{item['subject']} · {item['app']} {item['status']}{summary}")
        return lines

    def _actions_text(self, facts: SpecialistFacts) -> list[str]:
        rows = facts.actions()
        if not rows:
            return [t("There are no open actions.")]
        lines = [t("Open actions:")]
        for item in rows[:10]:
            due = t(", due {date}", date=item["due_at"]) if item["due_at"] else ""
            owner = item["owner"] or t("no owner")
            lines.append(f"- #{item['ref']} ({owner}{due})")
        return lines

    def _help_text(self, profile: dict[str, Any], facts: SpecialistFacts) -> list[str]:
        apps = ", ".join(facts.app_name(app) for app in sorted(facts.apps)) or t("none yet")
        lines = [
            t(
                "I am {name}, the specialist in {subject}. I read what these apps publish: {apps}.",
                name=profile["display_name"],
                subject=profile["subject"] or t("process engineering"),
                apps=apps,
            ),
            t(
                "Cite an asset (#asset:ID) and I summarize its results and open actions; ask "
                '"what needs attention?" or "which actions are open?".'
            ),
        ]
        if self.model_for(profile) is None:
            lines.append(
                t("My language model is off, so I answer with these scripted summaries only.")
            )
        return lines
