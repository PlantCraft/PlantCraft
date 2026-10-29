"""The site's server: the built page and its calls (the chat, the contact form, the page views)
and the owner's private stats page.

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
SITE_STATS_PASSWORD    the password of /stats, the owner's stats page (or SITE_STATS_PASSWORD_FILE);
                       unset: /stats is a 404
SITE_STATS_TIMEZONE    the time zone /stats counts days in (default UTC)
SITE_DEMO_STATS_URL    the public demo's GET /api/demo/stats, shown on /stats (optional), with
SITE_DEMO_STATS_KEY_FILE  a file holding the demo's PLANTCRAFT_PUBLIC_DEMO_STATS_KEY

/stats also shows the host's health ("Server now") from SITE_DATA_DIR/health.jsonl, which
`python -m sitechat watch` writes (health.py; WATCH_* settings there).
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import chat, health
from .contacts import Contact, Inbox
from .guard import MAX_HISTORY, MAX_MESSAGE, MAX_TURNS, Limits, Window
from .knowledge import Knowledge
from .llm import Model, make_model
from .stats import DAYS, DemoSource, events_csv, journeys, render, summary
from .visits import Visits

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
    stats_password: str = ""
    stats_timezone: str = "UTC"
    demo_stats: DemoSource = field(default_factory=DemoSource)

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
        demo_key = ""
        if env.get("SITE_DEMO_STATS_KEY_FILE") and Path(env["SITE_DEMO_STATS_KEY_FILE"]).exists():
            demo_key = Path(env["SITE_DEMO_STATS_KEY_FILE"]).read_text().strip()
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
            stats_password=_secret(env, "SITE_STATS_PASSWORD"),
            stats_timezone=env.get("SITE_STATS_TIMEZONE", "UTC").strip() or "UTC",
            demo_stats=DemoSource(env.get("SITE_DEMO_STATS_URL", "").strip(), demo_key),
        )


def _secret(env, name: str) -> str:
    value = env.get(name, "").strip()
    if not value and env.get(f"{name}_FILE") and Path(env[f"{name}_FILE"]).exists():
        value = Path(env[f"{name}_FILE"]).read_text().strip()
    return value


def _trust_proxy(value: str) -> bool | str:
    value = value.strip().lower()
    if value == "cloudflare":
        return value
    return value in ("1", "true", "on")


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class VisitRequest(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    # Only on the page view's first call.
    page: str | None = Field(default=None, max_length=200)
    ref: str = Field(default="", max_length=200)
    # A button or link clicked: its words and where it goes.
    click: str = Field(default="", max_length=200)


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
    visits = Visits(settings.data_dir)
    stats_failures = Window(10, 600)
    try:
        zone = ZoneInfo(settings.stats_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
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
        if request.url.path.startswith(("/api/", "/stats")):
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

    @app.post("/api/visit")
    def visit(body: VisitRequest, request: Request):
        visits.hit(
            body.id,
            address=address(request),
            agent=request.headers.get("user-agent", "")[:400],
            page=body.page,
            referrer=body.ref,
            click=body.click,
            # Cloudflare's guess of the visitor's country (when its IP Geolocation is on).
            country=request.headers.get("cf-ipcountry", "")
            if settings.trust_proxy == "cloudflare"
            else "",
        )
        return Response(status_code=204)

    def owner(request: Request) -> Response | None:
        """None for the owner (the stats password); otherwise the answer to give."""
        if not settings.stats_password:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        given = ""
        scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "basic":
            try:
                given = base64.b64decode(encoded).decode().partition(":")[2]
            except (binascii.Error, UnicodeDecodeError):
                given = ""
        if given and secrets.compare_digest(given.encode(), settings.stats_password.encode()):
            return None
        if given and not stats_failures.allow(address(request)):
            return JSONResponse({"error": "too many tries, wait a few minutes"}, 429)
        return Response(
            status_code=401, headers={"WWW-Authenticate": 'Basic realm="PlantCraft stats"'}
        )

    def window(now: float) -> float:
        start = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
        return (start - timedelta(days=DAYS - 1)).timestamp()

    @app.get("/stats")
    def stats(request: Request):
        refused = owner(request)
        if refused is not None:
            return refused
        now = time.time()
        start = window(now)
        views = visits.since(start)
        demo = settings.demo_stats.read(DAYS + 1)
        data = summary(
            views,
            demo,
            inbox.questions(),
            inbox.contacts(),
            zone,
            now,
            visits.clicks(start),
            journeys(views, visits.clicked(start), demo),
        )
        return HTMLResponse(render(data, zone, now, health.now(settings.data_dir, now)))

    @app.get("/stats/now.json")
    def stats_now(request: Request):
        """The server's health and who is on the site and in the demo now, for a script."""
        refused = owner(request)
        if refused is not None:
            return refused
        now = time.time()
        demo = settings.demo_stats.read(1)
        live = health.now(settings.data_dir, now)
        return {
            "at": now,
            "site_now": len(
                {v["visitor"] for v in visits.since(now - 86400) if now - v["last_seen"] <= 75}
            ),
            "demo_now": demo.get("now") if isinstance(demo, dict) else demo,
            "health": {k: live[k] for k in ("last", "stale", "traffic", "open", "alerts")},
        }

    @app.get("/stats/events.csv")
    def events(request: Request):
        refused = owner(request)
        if refused is not None:
            return refused
        start = window(time.time())
        views = visits.since(start)
        paths = journeys(views, visits.clicked(start), settings.demo_stats.read(DAYS + 1))
        return Response(
            events_csv(paths, zone),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="plantcraft-events.csv"'},
        )

    if settings.dist is not None:
        app.mount("/", StaticFiles(directory=settings.dist, html=True), name="site")
    return app
