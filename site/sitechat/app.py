"""The site's server: the built page and its two calls, the chat and the contact form.

SITE_CHAT_PROVIDER     openai | anthropic | off (default off: the chat shows only the form)
SITE_CHAT_API_KEY      the provider's key (or SITE_CHAT_API_KEY_FILE, a file holding it)
SITE_CHAT_MODEL        the model (default gpt-5-mini / claude-haiku-5-5)
SITE_CHAT_BASE_URL     an OpenAI-compatible server instead of OpenAI's (vLLM, Ollama...)
SITE_CHAT_REASONING    reasoning effort for OpenAI reasoning models (minimal, low...)
SITE_CHAT_DAILY_LIMIT  answers a day for the whole site (default 1000), to cap the cost
SITE_DATA_DIR          where contacts and questions are kept (default ./site-data)
SITE_CONTACT_WEBHOOK   a chat webhook told of each contact request (optional)
SITE_LOG_QUESTIONS     keep visitors' questions, without addresses (default 1)
SITE_TRUST_PROXY       1 when a reverse proxy in front sets X-Forwarded-For; cloudflare behind a
                       Cloudflare Tunnel (the visitor is CF-Connecting-IP)
SITE_DIST              the built site (default ./dist); its knowledge.json is what the chat reads
SITE_DOCS_URL          where the cited pages are published (default: the public repository)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import chat
from .contacts import Contact, Inbox
from .guard import MAX_HISTORY, MAX_MESSAGE, MAX_TURNS, Limits
from .knowledge import Knowledge
from .llm import Model, make_model

DOCS_URL = "https://github.com/PlantCraft/PlantCraft/blob/main"
MAX_BODY = 64 * 1024

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'; object-src 'none'"
)


@dataclass
class Settings:
    model: Model | None = None
    knowledge: Knowledge | None = None
    data_dir: Path = Path("site-data")
    dist: Path | None = None
    docs_url: str = DOCS_URL
    webhook: str = ""
    log_questions: bool = True
    trust_proxy: bool | str = False  # True: X-Forwarded-For; "cloudflare": CF-Connecting-IP
    daily_limit: int = 1000

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        key = env.get("SITE_CHAT_API_KEY", "").strip()
        if not key and env.get("SITE_CHAT_API_KEY_FILE"):
            key = Path(env["SITE_CHAT_API_KEY_FILE"]).read_text().strip()
        model = make_model(
            env.get("SITE_CHAT_PROVIDER", "off"),
            key,
            env.get("SITE_CHAT_MODEL", ""),
            env.get("SITE_CHAT_BASE_URL", ""),
            env.get("SITE_CHAT_REASONING", ""),
        )
        dist = Path(env.get("SITE_DIST", "dist"))
        knowledge = None
        if (dist / "knowledge.json").exists():
            knowledge = Knowledge.load(dist / "knowledge.json")
        return cls(
            model=model,
            knowledge=knowledge,
            data_dir=Path(env.get("SITE_DATA_DIR", "site-data")),
            dist=dist if dist.exists() else None,
            docs_url=env.get("SITE_DOCS_URL", DOCS_URL),
            webhook=env.get("SITE_CONTACT_WEBHOOK", ""),
            log_questions=env.get("SITE_LOG_QUESTIONS", "1") not in ("0", "false", "off"),
            trust_proxy=_trust_proxy(env.get("SITE_TRUST_PROXY", "0")),
            daily_limit=int(env.get("SITE_CHAT_DAILY_LIMIT", "1000")),
        )


def _trust_proxy(value: str) -> bool | str:
    value = value.strip().lower()
    if value == "cloudflare":
        return value
    return value in ("1", "true", "on")


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=40)


LIMIT_TEXT = {
    "minute": "Too many questions in a minute. Wait a moment and ask again.",
    "day": "That is the limit of questions for today. Leave your contact and the team will "
    "answer you directly.",
    "budget": "The assistant has answered all it can today. Leave your contact and the team will "
    "answer you directly.",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    limits = Limits(settings.daily_limit)
    inbox = Inbox(settings.data_dir, settings.webhook, settings.log_questions)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings

    def address(request: Request) -> str:
        if settings.trust_proxy == "cloudflare":
            visitor = request.headers.get("cf-connecting-ip", "").strip()
            if visitor:
                return visitor
        elif settings.trust_proxy:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    @app.middleware("http")
    async def harden(request: Request, call_next):
        size = request.headers.get("content-length")
        if request.method == "POST" and (
            size is None or not size.isdigit() or int(size) > MAX_BODY
        ):
            return JSONResponse({"error": "request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/chat/status")
    def status() -> dict:
        return {"assistant": settings.model is not None and settings.knowledge is not None}

    @app.post("/api/chat")
    def ask(body: ChatRequest, request: Request):
        messages = [m.model_dump() for m in body.messages][-MAX_TURNS:]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        if not messages or messages[-1]["role"] != "user":
            return JSONResponse({"error": "the last message must be the visitor's"}, 422)
        if len(messages[-1]["content"]) > MAX_MESSAGE:
            return JSONResponse(
                {"error": f"A question can have up to {MAX_MESSAGE} characters."}, 422
            )
        # Drop the oldest turns until the history fits.
        while sum(len(m["content"]) for m in messages) > MAX_HISTORY and len(messages) > 1:
            messages = messages[2:] if len(messages) > 2 else messages[-1:]
        if settings.model is None or settings.knowledge is None:
            return {"answer": "", "sources": [], "contact": True, "assistant": False}
        blocked = limits.chat(address(request))
        if blocked:
            return JSONResponse(
                {"answer": LIMIT_TEXT[blocked], "sources": [], "contact": blocked != "minute"},
                status_code=429,
            )
        result = chat.answer(settings.model, settings.knowledge, messages, settings.docs_url)
        inbox.add_question(
            messages[-1]["content"],
            result.grounded,
            result.contact,
            [s.path for s in result.sources],
        )
        return {
            "answer": result.text,
            "sources": [s.__dict__ for s in result.sources],
            "contact": result.contact,
            "assistant": True,
        }

    @app.post("/api/contact")
    async def contact(request: Request):
        try:
            data = Contact.model_validate(await request.json())
        except (ValidationError, ValueError) as exc:
            fields = sorted({str(e["loc"][0]) for e in getattr(exc, "errors", lambda: [])()})
            return JSONResponse({"error": "check the form", "fields": fields}, status_code=422)
        if data.website:  # the hidden field: a bot
            return {"ok": True}
        if not limits.contact(address(request)):
            return JSONResponse({"error": "too many requests, try again later"}, status_code=429)
        inbox.add_contact(data)
        return {"ok": True}

    if settings.dist is not None:
        app.mount("/", StaticFiles(directory=settings.dist, html=True), name="site")
    return app
