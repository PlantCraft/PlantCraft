"""HTTP routes: the specialists (robot users) and the installation's language model, configured
by administrators.

The installation's language model is the one connection (usually the company's own model or
a local one) every specialist answers with unless it has a model of its own. API keys are
write-only: a request sets, keeps (``null``) or clears (``""``)
one, and answers show only its last four characters.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from processcraft import egress
from processcraft.api.deps import AdminUser, Runtime
from processcraft.api.routers.v1_llm import first_choice
from processcraft.i18n import t
from processcraft.specialists import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    PROVIDERS,
    models_allowed,
)
from processcraft.specialists.profiles import MAX_PROVIDERS, PLATFORM_USES

router = APIRouter()


Provider = Literal["anthropic", "openai"]


class ModelPayload(BaseModel):
    # "installation": the default set up in Setup; "provider": a saved provider and one of its
    # models (provider_id, name); "own": the fields below (older profiles); "off": scripts.
    source: Literal["installation", "provider", "own", "off"] | None = None
    enabled: bool = True
    provider: Provider = "anthropic"
    provider_id: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=100)
    endpoint: str = Field(default="", max_length=300)
    api_key: str | None = Field(default=None, max_length=400)


class SpecialistPayload(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    subject: str = Field(default="", max_length=200)
    instructions: str = Field(default="", max_length=8000)
    apps: list[str] = Field(default_factory=list, max_length=40)
    active: bool = True
    model: ModelPayload = Field(default_factory=ModelPayload)


class SpecialistCreate(SpecialistPayload):
    username: str = Field(min_length=2, max_length=40)


class ConnectionPayload(BaseModel):
    enabled: bool = False
    provider: Provider = "openai"
    name: str = Field(default="", max_length=100)
    endpoint: str = Field(default="", max_length=300)
    api_key: str | None = Field(default=None, max_length=400)


class ProviderPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Provider = "openai"
    endpoint: str = Field(default="", max_length=300)
    models: list[str] = Field(default_factory=list, max_length=30)
    api_key: str | None = Field(default=None, max_length=400)
    # How hard OpenAI's reasoning models think; empty leaves it to the service.
    reasoning: Literal["", "none", "minimal", "low", "medium", "high"] = ""


class UseChoice(BaseModel):
    source: Literal["default", "off", "provider"] = "default"
    provider_id: str = Field(default="", max_length=40)
    model: str = Field(default="", max_length=100)


class SettingsPayload(BaseModel):
    # The default provider and model; empty turns models off.
    provider_id: str = Field(default="", max_length=40)
    model: str = Field(default="", max_length=100)
    # What each use writes with; None keeps them.
    uses: dict[str, UseChoice] | None = Field(default=None, max_length=100)


class ProbePayload(BaseModel):
    model: str = Field(default="", max_length=100)


def _apps(rt: Any, apps: list[str]) -> list[str]:
    known = {app.id for app in rt.suite_apps()}
    unknown = sorted(set(apps) - known)
    if unknown:
        raise HTTPException(
            status_code=422, detail=t("Unknown apps: {apps}.", apps=", ".join(unknown))
        )
    return apps


def _save(rt: Any, username: str, payload: SpecialistPayload, actor: str, *, create: bool):
    try:
        return rt.specialists.save(
            username,
            actor=actor,
            display_name=payload.display_name,
            subject=payload.subject,
            instructions=payload.instructions,
            apps=_apps(rt, payload.apps),
            active=payload.active,
            model=payload.model.model_dump(),
            create=create,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Specialist not found.")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/specialists")
def list_specialists(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    return {
        "items": rt.specialists.list(),
        "apps": [{"application_id": app.id, "name": app.name} for app in rt.suite_apps()],
        "model_allowed": models_allowed(),
        "providers": [{"id": key, "label": label} for key, label in PROVIDERS.items()],
        "defaults": {"provider": DEFAULT_PROVIDER, "model": DEFAULT_MODEL},
        "connection": rt.specialists.connection(),
        "language_providers": [
            {key: item[key] for key in ("provider_id", "name", "kind_label", "models", "ready")}
            for item in rt.specialists.providers()
        ],
    }


def _kinds() -> list[dict[str, str]]:
    return [{"id": key, "label": t(label)} for key, label in PROVIDERS.items()]


def _models(rt: Any) -> dict[str, Any]:
    """Settings › Language models: the saved providers, the default and who uses which."""

    store = rt.specialists
    used: dict[str, list[str]] = {}
    for item in store.list():
        if item["model"]["source"] == "provider":
            used.setdefault(item["model"]["provider_id"], []).append(item["display_name"])
    return {
        "providers": [
            {**item, "used_by": used.get(item["provider_id"], [])} for item in store.providers()
        ],
        "settings": store.settings(),
        "uses": _uses(rt),
        "kinds": _kinds(),
        "max_providers": MAX_PROVIDERS,
        "egress": _egress(store),
    }


def _egress(store: Any) -> dict[str, Any]:
    """The way out to models in the cloud: the hosts PlantCraft lets llm-egress open, and
    whether llm-egress answers (None where the suite runs without it, as in development)."""

    seen = egress.status(timeout=1) if egress.proxy_url() else None
    return {
        "configured": bool(egress.proxy_url()),
        "running": seen is not None,
        "hosts": store.egress_hosts(),
        "refused": [item for item in (seen or {}).get("recent", []) if item["outcome"] != "opened"][
            :5
        ],
    }


def _uses(rt: Any) -> list[dict[str, Any]]:
    """The parts of the suite that write with a model, each with its choice and whether it
    writes now."""

    store = rt.specialists
    rows = [
        (use, t(label), t(description), "", None, "default")
        for use, (label, description) in PLATFORM_USES.items()
    ]
    # Each installed app's own ([[contributes.llm]], sent when the app starts).
    names = {app.id: app.name for app in rt.suite_apps()}
    for item in rt.contributions.listing(list(names)):
        rows.extend(
            (
                f"{item['app']}:{use['id']}",
                use["title"],
                use.get("description", ""),
                use.get("reads", ""),
                names[item["app"]],
                first_choice(item["app"], use.get("default", "default")),
            )
            for use in item["contributes"].get("llm", [])
        )
    return [
        {
            "use": use,
            "label": label,
            "description": description,
            "reads": reads,
            "app": app,
            "choice": store.use_choice(use, declared),
            "ready": store.use_model(use, declared) is not None,
        }
        for use, label, description, reads, app, declared in rows
    ]


def _test_models(rt: Any, provider_id: str, models: list[str]) -> dict[str, dict[str, Any]]:
    """One short call to each model, side by side: address, key and names checked on save."""

    def one(model: str) -> dict[str, Any]:
        found = rt.specialists.resolve(provider_id, model)
        if found is None:
            return {"ok": False, "writer": "script", "text": t("Give the provider its key.")}
        return _probe(
            rt.specialist_chat.model_factory(
                found["key"],
                provider=found["kind"],
                model=found["name"],
                endpoint=found["endpoint"],
                reasoning=found["reasoning"],
            )
        )

    if not models_allowed():
        return {model: {"ok": False, "writer": "script", "text": _OFF()} for model in models}
    with ThreadPoolExecutor(max_workers=min(8, len(models) or 1)) as pool:
        return dict(zip(models, pool.map(one, models), strict=True))


def _first_default(rt: Any, admin: str, provider_id: str, tests: dict[str, dict[str, Any]]) -> None:
    """No default yet: the first model that answered becomes it, which turns models on."""

    store = rt.specialists
    if store.settings()["enabled"]:
        return
    model = next((name for name, test in tests.items() if test["ok"]), None)
    if model is None:
        return
    store.save_settings(actor=admin, provider_id=provider_id, model=model)
    rt.workspace.audit.record(
        admin,
        "language_model.changed",
        "settings:language-model",
        {"provider_id": provider_id, "model": model, "first": True},
    )


def _saved(rt: Any, admin: str, provider: dict[str, Any]) -> dict[str, Any]:
    tests = _test_models(rt, provider["provider_id"], provider["models"])
    _first_default(rt, admin, provider["provider_id"], tests)
    return {**_models(rt), "saved": provider["provider_id"], "tests": tests}


def _provider_audit(provider: dict[str, Any]) -> dict[str, Any]:
    return {key: provider[key] for key in ("name", "kind", "endpoint", "models", "api_key_set")}


@router.get("/api/language-models")
def language_models(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    return _models(rt)


@router.post("/api/language-models/providers", status_code=201)
def create_provider(payload: ProviderPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        provider = rt.specialists.save_provider(None, actor=admin, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(
        admin,
        "language_model.provider_added",
        f"settings:language-model:{provider['provider_id']}",
        _provider_audit(provider),
    )
    return _saved(rt, admin, provider)


@router.put("/api/language-models/providers/{provider_id}")
def update_provider(
    provider_id: str, payload: ProviderPayload, admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    try:
        provider = rt.specialists.save_provider(provider_id, actor=admin, **payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Provider not found.")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(
        admin,
        "language_model.provider_changed",
        f"settings:language-model:{provider_id}",
        _provider_audit(provider),
    )
    return _saved(rt, admin, provider)


@router.delete("/api/language-models/providers/{provider_id}")
def delete_provider(provider_id: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        orphans = rt.specialists.remove_provider(provider_id, actor=admin)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Provider not found.")) from exc
    rt.workspace.audit.record(
        admin,
        "language_model.provider_removed",
        f"settings:language-model:{provider_id}",
        {"specialists": orphans},
    )
    return {**_models(rt), "orphans": orphans}


@router.post("/api/language-models/providers/{provider_id}/test")
def test_provider(
    provider_id: str, payload: ProbePayload, admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    """One short call to one of the provider's models: address, key and model name together.
    With no default yet, a model that answers becomes it."""

    found = rt.specialists.provider(provider_id)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Provider not found."))
    model = payload.model if payload.model in found["models"] else found["models"][0]
    tests = _test_models(rt, provider_id, [model])
    _first_default(rt, admin, provider_id, tests)
    return tests[model]


@router.put("/api/language-models/settings")
def save_model_settings(payload: SettingsPayload, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    data = payload.model_dump()
    unknown = sorted(set(data["uses"] or {}) - {item["use"] for item in _uses(rt)})
    if unknown:
        raise HTTPException(
            status_code=422, detail=t("Unknown uses: {uses}.", uses=", ".join(unknown))
        )
    try:
        rt.specialists.save_settings(actor=admin, **data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(
        admin, "language_model.changed", "settings:language-model", payload.model_dump()
    )
    return _models(rt)


@router.get("/api/language-model")
def language_model(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """The installation's language model (its key only as a hint) and the providers it can be."""

    return {
        **rt.specialists.connection(),
        "providers": [{"id": key, "label": label} for key, label in PROVIDERS.items()],
    }


@router.put("/api/language-model")
def save_language_model(
    payload: ConnectionPayload, admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    try:
        connection = rt.specialists.save_connection(actor=admin, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(
        admin,
        "language_model.changed",
        "settings:language-model",
        {
            key: connection[key]
            for key in ("enabled", "provider", "name", "endpoint", "api_key_set")
        },
    )
    return connection


@router.post("/api/language-model/test")
def test_language_model(_admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """One short call to the installation's model, to check the address, the key and the name."""

    connection = rt.specialists.connection()
    if not models_allowed():
        return {"ok": False, "writer": "script", "text": _OFF()}
    if not connection["ready"]:
        return {"ok": False, "writer": "script", "text": t("Name the model, and give its key.")}
    model = rt.specialist_chat.model_factory(
        rt.specialists.connection_key() or "",
        provider=connection["provider"],
        model=connection["name"],
        endpoint=connection["endpoint"],
        reasoning=connection["reasoning"],
    )
    return _probe(model)


def _OFF() -> str:  # noqa: N802
    return t("Language models are turned off in this installation by whoever installed it.")


# The test offers one tool, as the assistant does: some services take a model without tools
# and refuse it with them (OpenAI's reasoning models in chat completions).
PROBE_TOOL = {
    "name": "plant_clock",
    "description": "The plant's current date and time.",
    "input_schema": {"type": "object", "properties": {}},
}


def _probe(model: Any) -> dict[str, Any]:
    try:
        text = model.answer(
            "Answer with one short sentence. You may call plant_clock.",
            [{"role": "user", "content": "Say that the connection works."}],
            lambda _name, _args: datetime.now(UTC).isoformat(timespec="minutes"),
            [PROBE_TOOL],
        )
    except Exception as exc:
        return {"ok": False, "writer": model.label, "text": str(exc)[:400]}
    return {"ok": True, "writer": model.label, "text": text[:400]}


@router.post("/api/specialists", status_code=201)
def create_specialist(payload: SpecialistCreate, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    specialist = _save(rt, payload.username, payload, admin, create=True)
    rt.workspace.audit.record(
        admin, "specialist.created", f"user:{specialist['username']}", _audit(specialist)
    )
    return specialist


@router.put("/api/specialists/{username}")
def update_specialist(
    username: str, payload: SpecialistPayload, admin: AdminUser, rt: Runtime
) -> dict[str, Any]:
    specialist = _save(rt, username, payload, admin, create=False)
    rt.workspace.audit.record(
        admin, "specialist.changed", f"user:{specialist['username']}", _audit(specialist)
    )
    return specialist


@router.delete("/api/specialists/{username}")
def delete_specialist(username: str, admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    if not rt.specialists.remove(username):
        raise HTTPException(status_code=404, detail=t("Specialist not found."))
    rt.workspace.audit.record(admin, "specialist.removed", f"user:{username}", {})
    return {"removed": username}


@router.post("/api/specialists/{username}/test")
def test_specialist(username: str, _admin: AdminUser, rt: Runtime) -> dict[str, Any]:
    """One short call to the specialist's model, to check the key and the network."""

    profile = rt.specialists.get(username)
    if profile is None:
        raise HTTPException(status_code=404, detail=t("Specialist not found."))
    if not models_allowed():
        return {"ok": False, "writer": "script", "text": _OFF()}
    if profile["model"]["source"] == "off":
        return {"ok": False, "writer": "script", "text": t("The language model is off.")}
    model = rt.specialist_chat.model_for(profile)
    if model is None:
        if profile["model"]["source"] == "installation":
            text = t(
                "The installation's language model is not set up: see Settings, Language model."
            )
        elif profile["model"]["source"] == "provider":
            text = t("The provider is not ready: see Settings, Language models.")
        else:
            text = t("No API key is saved.")
        return {"ok": False, "writer": "script", "text": text}
    return _probe(model)


def _audit(specialist: dict[str, Any]) -> dict[str, Any]:
    """What changed is recorded without the key."""

    model = specialist["model"]
    return {
        "apps": specialist["apps"],
        "active": specialist["active"],
        "model": {
            key: model[key] for key in ("source", "provider", "provider_id", "name", "endpoint")
        },
        "api_key_set": model["api_key_set"],
    }
