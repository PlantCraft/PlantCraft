"""What each specialist is: a robot account with a profile, and its model key kept apart.

A specialist is a workspace user of kind ``specialist`` (it signs in nowhere and
has no password) plus a profile: the subject it covers, its instructions (the
prompt), the apps whose published data it may read and its language model: the
installation's (the one connection an administrator sets up in Settings, usually the
company's own or a local model), one of the providers saved in Settings with a model from its
list, its own (older profiles), or none. API keys never go to the database: they live in ``specialist-keys.json`` beside it, readable by the service
account only, and the API shows only their last four characters.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

from plantcraft.auth.public_demo import public_demo
from plantcraft.auth.users import UserStore
from plantcraft.db import Store
from plantcraft.egress import is_public_host, provider_host, write_allowlist
from plantcraft.files import write_atomic
from plantcraft.i18n import t

LOGGER = logging.getLogger(__name__)

PROVIDERS = {
    "anthropic": "Claude (Anthropic Messages API)",
    "openai": "OpenAI-compatible (chat completions: vLLM, Ollama, LM Studio, Azure, gateways)",
}
# How hard a reasoning model thinks before it answers, set per OpenAI provider; empty leaves
# it to the service (a model that does not reason refuses the parameter).
REASONING = ("none", "minimal", "low", "medium", "high")
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-5-5"
# Which model a specialist answers with: the installation's default, a saved provider's model,
# its own (older profiles), or none.
SOURCES = ("installation", "provider", "own", "off")
# The installation's key in the key file: no username starts with "@".
INSTALLATION_KEY = "@installation"
# A saved provider's key: "@provider:<id>".
PROVIDER_KEY = "@provider:{id}"
MAX_PROVIDERS = 20
# The parts of the platform that write with a language model, each set in Setup › Language
# models to the default, a provider's model or off. Apps add their own (``[[llm]]`` in app.toml).
PLATFORM_USES = {
    "assistant": (
        "Assistant",
        "The panel on every page and the chats in Desk: reads the plant's data the person may see.",
    ),
    "plant-draft": (
        "Plant draft",
        "Assets › Import, Draft a plant: places the loops the rules and the documents leave "
        "unsure. Reads tag names, descriptions and passages Documents gives the assistant.",
    ),
}
MAX_MODELS = 30
USERNAME = re.compile(r"^[a-z][a-z0-9_.\-]{1,39}$")
MAX_INSTRUCTIONS = 8000


def models_allowed() -> bool:
    """``PLANTCRAFT_LLM=off`` forbids language models in the whole installation.
    Its name before the rename still counts (``settings_compat``). A public demo keeps them for the people
    an administrator created (``models_allowed_for``); its visitors never reach them."""

    value = os.environ.get("PLANTCRAFT_LLM") or ""
    return value.strip().lower() not in {
        "off",
        "0",
        "false",
        "no",
    }


def models_allowed_for(level: str | None) -> bool:
    """Whether a person with this access level may use a model here: in a public demo only
    editors and administrators (the visitor account is a read-only viewer), and never the apps'
    uses (``models_allowed_for(None)``), which a visitor's clicks could set off."""

    if not models_allowed():
        return False
    if public_demo() is None:
        return True
    return level in {"editor", "admin"}


def key_hint(key: str | None) -> str | None:
    return f"…{key[-4:]}" if key and len(key) >= 8 else ("…" if key else None)


class KeyFile:
    """API keys by specialist, in one JSON file with mode 600."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return (
            {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}
        )

    def get(self, username: str) -> str | None:
        with self._lock:
            return self._read().get(username) or None

    def set(self, username: str, key: str | None) -> None:
        with self._lock:
            data = self._read()
            if key:
                data[username] = key
            else:
                data.pop(username, None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, json.dumps(data, indent=2))


class SpecialistStore(Store):
    """Profiles of the specialists and how many answers each wrote."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS specialists (
        username TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        answers INTEGER NOT NULL DEFAULT 0,
        last_answer_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS language_model (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS app_llm_calls (
        app TEXT NOT NULL,
        day TEXT NOT NULL,
        calls INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (app, day)
    );
    CREATE TABLE IF NOT EXISTS language_providers (
        provider_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
    """

    def __init__(self, db: Any, users: UserStore, keys: KeyFile):
        super().__init__(db)
        self.users = users
        self.keys = keys
        self._adopt_single_connection()
        self._drop_the_switch()
        self.sync_egress()

    def egress_hosts(self) -> list[str]:
        """The hosts on the internet the models set up here call (llm-egress lets only these
        out); none while language models are forbidden in this installation."""

        if not models_allowed():
            return []
        hosts = {provider_host(item["kind"], item["endpoint"]) for item in self.providers()}
        for profile in self.list(include_inactive=False):
            model = profile["model"]
            if model["source"] == "own":
                hosts.add(provider_host(model["provider"], model["endpoint"]))
        return sorted(host for host in hosts if is_public_host(host))

    def sync_egress(self) -> None:
        """Tell llm-egress which hosts it may open (a file it reads); a failure never stops
        PlantCraft (the gate then keeps its last list, or refuses everything)."""

        try:
            write_allowlist(self.egress_hosts())
        except OSError:
            LOGGER.warning("could not write the list of hosts of llm-egress", exc_info=True)

    # Reading ----------------------------------------------------------------

    def list(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM specialists ORDER BY created_at").fetchall()
        items = [self._profile(row) for row in rows]
        return [item for item in items if include_inactive or item["active"]]

    def get(self, username: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM specialists WHERE username = ?", (username,)
            ).fetchone()
        return self._profile(row) if row else None

    def api_key(self, username: str) -> str | None:
        return self.keys.get(username)

    def _profile(self, row: Any) -> dict[str, Any]:
        data = self._loads(row["payload_json"], {})
        user = self.users.get_user(row["username"]) or {}
        model = data.get("model") or {}
        key = self.keys.get(row["username"])
        source = model.get("source")
        if source not in SOURCES:
            # Profiles from before the installation's connection: a key of its own keeps it.
            source = "own" if model.get("enabled") and key else "installation"
        return {
            "username": row["username"],
            "display_name": user.get("display_name") or row["username"],
            "subject": data.get("subject", ""),
            "instructions": data.get("instructions", ""),
            "apps": list(data.get("apps") or []),
            "active": bool(user.get("active")),
            "model": {
                "source": source,
                "enabled": source != "off",
                "provider": model.get("provider") or DEFAULT_PROVIDER,
                "provider_id": model.get("provider_id") or "",
                "name": model.get("name") or "",
                "endpoint": model.get("endpoint") or "",
                "api_key_set": bool(key),
                "api_key_hint": key_hint(key),
                "ready": self.model_ready(source, bool(key), model.get("provider_id") or ""),
            },
            "answers": int(row["answers"]),
            "last_answer_at": row["last_answer_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    def model_ready(self, source: str, own_key: bool, provider_id: str = "") -> bool:
        """Whether a specialist with this source has a model to answer with now."""

        if not models_allowed() or source == "off":
            return False
        if source == "own":
            return own_key
        if source == "provider":
            found = self.provider(provider_id)
            return bool(found and found["ready"])
        connection = self.connection()
        return connection["enabled"] and connection["ready"]

    # Language model providers (Setup › Language models) ---------------------------
    #
    # Each provider is a server the installation may send prompts to: a name, its format
    # (Anthropic's Messages API or OpenAI's chat completions), its address, its key (in the key
    # file) and the models it serves. The settings say whether models are used at all and
    # which provider and model is the installation's default.

    def _settings(self) -> tuple[dict[str, Any], Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM language_model WHERE id = 1").fetchone()
        return (self._loads(row["payload_json"], {}) if row else {}), row

    def _write_settings(self, payload: dict[str, Any], actor: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO language_model (id, payload_json, updated_at, updated_by)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at, updated_by = excluded.updated_by
                """,
                (self._json(payload), self._now(), actor),
            )

    def _adopt_single_connection(self) -> None:
        """The one connection of before (2026-10-22) becomes the provider "default"."""

        data, row = self._settings()
        if not row or data.get("version") in (2, 3):
            return
        if data.get("name"):
            self._write_provider(
                "default",
                {
                    "name": t("Installation model"),
                    "kind": data.get("provider") or "openai",
                    "endpoint": data.get("endpoint") or "",
                    "models": [data["name"]],
                },
                actor=row["updated_by"],
            )
            key = self.keys.get(INSTALLATION_KEY)
            if key:
                self.keys.set(PROVIDER_KEY.format(id="default"), key)
        self._write_settings(
            {
                "version": 2,
                "enabled": bool(data.get("enabled")),
                "provider_id": "default" if data.get("name") else "",
                "model": data.get("name") or "",
            },
            row["updated_by"],
        )

    def _drop_the_switch(self) -> None:
        """Models were turned on by a switch beside the default (until 2026-10-25). Now choosing
        the default turns them on, so an installation whose switch was off keeps no default."""

        data, row = self._settings()
        if not row or data.get("version") != 2:
            return
        on = bool(data.get("enabled"))
        self._write_settings(
            {
                "version": 3,
                "provider_id": data.get("provider_id", "") if on else "",
                "model": data.get("model", "") if on else "",
                "uses": {},
            },
            row["updated_by"],
        )

    def providers(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM language_providers ORDER BY position, created_at"
            ).fetchall()
        return [self._provider(row) for row in rows]

    def provider(self, provider_id: str) -> dict[str, Any] | None:
        if not provider_id:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM language_providers WHERE provider_id = ?", (provider_id,)
            ).fetchone()
        return self._provider(row) if row else None

    def provider_key(self, provider_id: str) -> str | None:
        return self.keys.get(PROVIDER_KEY.format(id=provider_id))

    def _provider(self, row: Any) -> dict[str, Any]:
        data = self._loads(row["payload_json"], {})
        key = self.provider_key(row["provider_id"])
        kind = data.get("kind") or "openai"
        endpoint = vendor_endpoint(kind, data.get("endpoint") or "")
        models = [str(item) for item in data.get("models") or []]
        # A local model (Ollama, vLLM) may need no key; the hosted APIs always do.
        needs_key = kind == "anthropic" or not endpoint
        return {
            "provider_id": row["provider_id"],
            "name": data.get("name") or row["provider_id"],
            "kind": kind,
            "kind_label": t(PROVIDERS.get(kind, kind)),
            "endpoint": endpoint,
            "models": models,
            "reasoning": data.get("reasoning") or "",
            "api_key_set": bool(key),
            "api_key_hint": key_hint(key),
            "ready": bool(models) and (bool(key) or not needs_key),
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    def _write_provider(self, provider_id: str, payload: dict[str, Any], *, actor: str) -> None:
        now = self._now()
        with self._lock, self._write() as connection:
            position = connection.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM language_providers"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO language_providers
                (provider_id, payload_json, position, created_at, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at, updated_by = excluded.updated_by
                """,
                (provider_id, self._json(payload), position, now, now, actor),
            )
        self.sync_egress()

    def save_provider(
        self,
        provider_id: str | None,
        *,
        actor: str,
        name: str,
        kind: str,
        endpoint: str = "",
        models: list[str] | None = None,
        api_key: str | None = None,
        reasoning: str = "",
    ) -> dict[str, Any]:
        """Create (``provider_id`` None) or replace a provider; ``api_key`` None keeps the key."""

        if kind not in PROVIDERS:
            raise ValueError(t("Unknown model provider: {provider}.", provider=kind))
        if reasoning and reasoning not in REASONING:
            raise ValueError(t("Unknown reasoning effort: {effort}.", effort=reasoning))
        cleaned_name = (name or "").strip()[:80]
        if not cleaned_name:
            raise ValueError(t("Give the provider a name."))
        names = []
        for item in models or []:
            model = str(item).strip()[:100]
            if model and model not in names:
                names.append(model)
        if not names:
            raise ValueError(t("List at least one model, for example llama3.1:70b or gpt-4o."))
        if len(names) > MAX_MODELS:
            raise ValueError(t("A provider lists {count} models at most.", count=MAX_MODELS))
        if provider_id is None:
            existing = {item["provider_id"] for item in self.providers()}
            if len(existing) >= MAX_PROVIDERS:
                raise ValueError(t("At most {count} providers.", count=MAX_PROVIDERS))
            base = re.sub(r"[^a-z0-9]+", "-", cleaned_name.lower()).strip("-")[:30] or "provider"
            provider_id, number = base, 2
            while provider_id in existing:
                provider_id, number = f"{base}-{number}", number + 1
        elif self.provider(provider_id) is None:
            raise KeyError(provider_id)
        payload = {
            "name": cleaned_name,
            "kind": kind,
            "endpoint": vendor_endpoint(kind, _endpoint(endpoint)),
            "models": names,
            "reasoning": reasoning if kind == "openai" else "",
        }
        self._write_provider(provider_id, payload, actor=actor)
        if api_key is not None:
            self.keys.set(PROVIDER_KEY.format(id=provider_id), api_key.strip() or None)
        # A model's name may have changed: the default and the uses keep only models still listed.
        settings = self.settings()
        if settings["provider_id"] == provider_id and settings["model"] not in names:
            self.save_settings(actor=actor, provider_id=provider_id, model=names[0])
        return self.provider(provider_id) or {}

    def remove_provider(self, provider_id: str, *, actor: str) -> list[str]:
        """Remove a provider and its key; returns the specialists that used it (now on the default)."""

        if self.provider(provider_id) is None:
            raise KeyError(provider_id)
        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM language_providers WHERE provider_id = ?", (provider_id,)
            )
        self.keys.set(PROVIDER_KEY.format(id=provider_id), None)
        self.sync_egress()
        settings = self.settings()
        # The uses on this provider go back to the default; the default goes to the next
        # provider, or to none (models off) when it was the last.
        uses = {
            use: choice
            for use, choice in settings["uses"].items()
            if choice.get("provider_id") != provider_id
        }
        if settings["provider_id"] == provider_id:
            rest = [item for item in self.providers() if item["ready"]]
            self.save_settings(
                actor=actor,
                provider_id=rest[0]["provider_id"] if rest else "",
                model=rest[0]["models"][0] if rest else "",
                uses=uses,
            )
        else:
            self.save_settings(
                actor=actor,
                provider_id=settings["provider_id"],
                model=settings["model"],
                uses=uses,
            )
        return [
            item["username"]
            for item in self.list()
            if item["model"]["source"] == "provider" and item["model"]["provider_id"] == provider_id
        ]

    def settings(self) -> dict[str, Any]:
        data, row = self._settings()
        provider_id = data.get("provider_id") or ""
        model = data.get("model") or ""
        return {
            # Models are on once a default is chosen: there is no separate switch (2026-10-25).
            "enabled": bool(provider_id and model),
            "provider_id": provider_id,
            "model": model,
            "uses": {
                str(use): choice
                for use, choice in (data.get("uses") or {}).items()
                if isinstance(choice, dict)
            },
            "allowed": models_allowed(),
            "updated_at": row["updated_at"] if row else None,
            "updated_by": row["updated_by"] if row else None,
        }

    def save_settings(
        self,
        *,
        actor: str,
        provider_id: str,
        model: str,
        uses: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """The installation's default provider and model (none: models off), and what each use
        writes with: ``{"source": "default" | "off" | "provider", "provider_id", "model"}``.
        ``uses`` None keeps them."""

        self._check_model(provider_id, model)
        if uses is None:
            uses = self.settings()["uses"]
        cleaned: dict[str, dict[str, Any]] = {}
        for use, choice in uses.items():
            source = choice.get("source") or "default"
            if source == "default":
                # Kept: a use that starts off (declared so, or of an app outside the suite)
                # writes with the default only once an administrator says so.
                cleaned[use] = {"source": "default"}
            elif source == "off":
                cleaned[use] = {"source": "off"}
            elif source == "provider":
                self._check_model(choice.get("provider_id") or "", choice.get("model") or "")
                if not choice.get("provider_id"):
                    raise ValueError(t("Choose the provider and model of {use}.", use=use))
                cleaned[use] = {
                    "source": "provider",
                    "provider_id": choice["provider_id"],
                    "model": choice["model"],
                }
            else:
                raise ValueError(t("Unknown choice: {source}.", source=source))
        self._write_settings(
            {"version": 3, "provider_id": provider_id, "model": model, "uses": cleaned},
            actor,
        )
        return self.settings()

    def _check_model(self, provider_id: str, model: str) -> None:
        if not provider_id:
            return
        found = self.provider(provider_id)
        if found is None:
            raise ValueError(t("Unknown provider: {provider}.", provider=provider_id))
        if model not in found["models"]:
            raise ValueError(t("{model} is not one of the provider's models.", model=model))

    def use_choice(self, use: str, declared: str = "default") -> dict[str, Any]:
        """What a use writes with: its own choice, else what its app declared (``"off"``
        waits for an administrator), else the default."""

        saved = self.settings()["uses"].get(use)
        if saved:
            return saved
        return {"source": "off"} if declared == "off" else {"source": "default"}

    def count_app_call(self, app: str, day: str, limit: int) -> bool:
        """Count one model call of an app on a plant day; False (and not counted) past
        ``limit``."""

        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT calls FROM app_llm_calls WHERE app = ? AND day = ?", (app, day)
            ).fetchone()
            if row and row["calls"] >= limit:
                return False
            connection.execute(
                """
                INSERT INTO app_llm_calls (app, day, calls) VALUES (?, ?, 1)
                ON CONFLICT(app, day) DO UPDATE SET calls = calls + 1
                """,
                (app, day),
            )
            connection.execute("DELETE FROM app_llm_calls WHERE day < ?", (day,))
        return True

    def use_model(self, use: str, declared: str = "default") -> dict[str, Any] | None:
        """``{kind, name, endpoint, key, label}`` of the model a use writes with, or None (off,
        nothing set up, or models forbidden in the installation)."""

        if not models_allowed():
            return None
        choice = self.use_choice(use, declared)
        if choice["source"] == "off":
            return None
        if choice["source"] == "provider":
            return self.resolve(choice["provider_id"], choice["model"])
        settings = self.settings()
        if not settings["enabled"]:
            return None
        return self.resolve(settings["provider_id"], settings["model"])

    def resolve(self, provider_id: str, model: str = "") -> dict[str, Any] | None:
        """``{kind, name, endpoint, key}`` of a provider's model (its first when not given)."""

        found = self.provider(provider_id)
        if found is None or not found["ready"]:
            return None
        return {
            "kind": found["kind"],
            "name": model if model in found["models"] else found["models"][0],
            "endpoint": found["endpoint"],
            "key": self.provider_key(provider_id) or "",
            "label": found["name"],
            "reasoning": found["reasoning"],
        }

    # The installation's default model, in the shape of the one connection of before.

    def connection(self) -> dict[str, Any]:
        """The installation's default model, without its key (the hint only)."""

        settings = self.settings()
        found = self.provider(settings["provider_id"])
        key = self.provider_key(found["provider_id"]) if found else None
        return {
            "enabled": settings["enabled"],
            "provider": found["kind"] if found else "openai",
            "provider_id": found["provider_id"] if found else "",
            "provider_name": found["name"] if found else "",
            "name": settings["model"] if found else "",
            "endpoint": found["endpoint"] if found else "",
            "reasoning": found["reasoning"] if found else "",
            "api_key_set": bool(key),
            "api_key_hint": key_hint(key),
            "ready": bool(found and found["ready"] and settings["model"]),
            "allowed": models_allowed(),
            "updated_at": settings["updated_at"],
            "updated_by": settings["updated_by"],
        }

    def connection_key(self) -> str | None:
        found = self.provider(self.settings()["provider_id"])
        return self.provider_key(found["provider_id"]) if found else None

    def save_connection(
        self,
        *,
        actor: str,
        enabled: bool,
        provider: str,
        name: str,
        endpoint: str = "",
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """The one-connection form of before: sets the provider "default" and makes it the default.

        ``api_key`` None keeps the saved key, "" removes it.
        """

        if provider not in PROVIDERS:
            raise ValueError(t("Unknown model provider: {provider}.", provider=provider))
        name = (name or "").strip()[:100]
        if enabled and not name:
            raise ValueError(t("Name the model to use, for example llama3.1:70b or gpt-4o."))
        endpoint = _endpoint(endpoint)
        if not name:
            self.save_settings(actor=actor, provider_id="", model="")
            return self.connection()
        current = self.provider("default") or {}
        others = [item for item in current.get("models", []) if item != name]
        self._write_provider(
            "default",
            {
                "name": current.get("name") or t("Installation model"),
                "kind": provider,
                "endpoint": endpoint,
                "models": [name, *others][:MAX_MODELS],
            },
            actor=actor,
        )
        if api_key is not None:
            self.keys.set(PROVIDER_KEY.format(id="default"), api_key.strip() or None)
        self.save_settings(
            actor=actor, provider_id="default" if enabled else "", model=name if enabled else ""
        )
        return self.connection()

    # Writing ----------------------------------------------------------------

    def save(
        self,
        username: str,
        *,
        actor: str,
        display_name: str,
        subject: str = "",
        instructions: str = "",
        apps: list[str] | None = None,
        active: bool = True,
        model: dict[str, Any] | None = None,
        create: bool = False,
    ) -> dict[str, Any]:
        """Create (``create=True``) or replace a specialist; ``model["api_key"]`` None keeps it."""

        username = (username or "").strip().lower()
        existing = self.get(username)
        if create:
            if not USERNAME.match(username):
                raise ValueError(
                    t(
                        "The username starts with a letter and has 2 to 40 lowercase letters, "
                        "digits, dots, dashes or underscores."
                    )
                )
            # A robot account left without a profile (the former monolith's) can be taken again.
            account = self.users.get_user(username)
            if existing or (account and account.get("kind") != "specialist"):
                raise ValueError(t("@{username} is already taken.", username=username))
        elif existing is None:
            raise KeyError(username)
        if len(instructions or "") > MAX_INSTRUCTIONS:
            raise ValueError(
                t("The instructions are longer than {count} characters.", count=MAX_INSTRUCTIONS)
            )
        model = dict(model or {})
        provider = model.get("provider") or DEFAULT_PROVIDER
        if provider not in PROVIDERS:
            raise ValueError(t("Unknown model provider: {provider}.", provider=provider))
        endpoint = _endpoint(model.get("endpoint") or "")
        source = model.get("source")
        if source not in SOURCES:
            # Older clients send only "enabled": on with a key of its own means its own.
            own = model.get("api_key") or (existing or {}).get("model", {}).get("api_key_set")
            source = ("own" if own else "installation") if model.get("enabled", True) else "off"
        provider_id = (model.get("provider_id") or "").strip()
        name = (model.get("name") or "").strip()[:100]
        if source == "provider":
            found = self.provider(provider_id)
            if found is None:
                raise ValueError(t("Choose one of the saved providers."))
            if name not in found["models"]:
                raise ValueError(
                    t("{model} is not one of the provider's models.", model=name or "—")
                )
        payload = {
            "subject": (subject or "").strip()[:200],
            "instructions": (instructions or "").strip(),
            "apps": sorted({str(app) for app in apps or [] if app}),
            "model": {
                "source": source,
                "enabled": source != "off",
                "provider": provider,
                "provider_id": provider_id if source == "provider" else "",
                "name": name,
                "endpoint": endpoint,
            },
        }
        role = t("Specialist (robot)")
        self.users.upsert_user(username, display_name.strip() or username, role, kind="specialist")
        if active:
            self.users.activate(username)
        else:
            self.users.deactivate(username)
        now = self._now()
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO specialists (username, payload_json, created_at, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at, updated_by = excluded.updated_by
                """,
                (username, self._json(payload), now, now, actor),
            )
        if "api_key" in model and model["api_key"] is not None:
            self.keys.set(username, str(model["api_key"]).strip() or None)
        self.sync_egress()
        return self.get(username) or {}

    def remove(self, username: str) -> bool:
        """The account is deactivated (its messages stay); the profile and key are removed."""

        if self.get(username) is None:
            return False
        self.users.deactivate(username)
        self.keys.set(username, None)
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM specialists WHERE username = ?", (username,))
        self.sync_egress()
        return True

    def count_answer(self, username: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE specialists SET answers = answers + 1, last_answer_at = ? WHERE username = ?",
                (self._now(), username),
            )


# The vendors' own sites, typed as a provider's address: their API is the default one.
VENDOR_SITES = {
    "openai": {"openai.com", "www.openai.com", "api.openai.com", "platform.openai.com"},
    "anthropic": {
        "anthropic.com",
        "www.anthropic.com",
        "api.anthropic.com",
        "console.anthropic.com",
    },
}


def vendor_endpoint(kind: str, endpoint: str) -> str:
    """An address on the vendor's own site (``https://openai.com``) means its API: empty, so
    the model service's default address is used (``https://api.openai.com/v1``)."""

    match = re.match(r"^https?://([^/:]+)", endpoint or "")
    if match and match.group(1).lower() in VENDOR_SITES.get(kind, set()):
        return ""
    return endpoint


def _endpoint(text: str) -> str:
    endpoint = (text or "").strip().rstrip("/")
    if endpoint and not re.match(r"^https?://[^\s/]+", endpoint):
        raise ValueError(t("The endpoint must be an http(s) address."))
    return endpoint
