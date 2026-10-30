"""FastAPI application factory for PlantCraft, the central app of the suite."""

from __future__ import annotations

import atexit
import os
import secrets
from contextlib import asynccontextmanager
from importlib import metadata
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from plantcraft.api.deps import access_guard
from plantcraft.api.routers import (
    actions,
    app_keys,
    apps,
    asset_file,
    asset_model,
    assets,
    assistant_access,
    assistant_chat,
    audit,
    compute,
    compute_worker,
    data,
    demo,
    desk,
    directory,
    groups,
    home,
    home_system,
    installation,
    mcp,
    messages,
    notebooks,
    notebooks_pair,
    notifications,
    operations,
    plant_map,
    platform,
    prompts,
    search,
    session,
    setup_apps,
    specialists,
    sso,
    users,
    v1,
    v1_assistant,
    v1_compute,
    v1_desk,
    v1_explore,
    v1_links,
    v1_llm,
    v1_notebooks,
    v1_objects,
    v1_people,
    v1_tools,
)
from plantcraft.api.runtime import PROJECT_ROOT, ApiRuntime
from plantcraft.api.usage import EDGE_HEADER, install_usage_limits
from plantcraft.auth.public_demo import RateLimiter, public_demo
from plantcraft.config import env_flag, plant_timezone
from plantcraft.i18n import COOKIE, reset_language, set_language, t
from plantcraft.ops.workers import startup
from plantcraft_sdk.server.logs import configure_logging
from plantcraft_sdk.server.memory import Releaser
from plantcraft_sdk.server.ops import RequestLog

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
# The plant's time zone for the browser (ui timeZone.ts reads it).
TIME_ZONE_COOKIE = "processcraft_time_zone"
ROUTERS = (
    platform,
    session,
    demo,
    assets,
    asset_model,
    asset_file,
    home,
    home_system,
    data,
    plant_map,
    prompts,
    users,
    groups,
    directory,
    installation,
    setup_apps,
    sso,
    notifications,
    audit,
    app_keys,
    assistant_access,
    mcp,
    apps,
    operations,
    messages,
    actions,
    desk,
    assistant_chat,
    specialists,
    notebooks,
    notebooks_pair,
    search,
    v1,
    v1_links,
    v1_explore,
    v1_llm,
    v1_assistant,
    v1_people,
    v1_notebooks,
    v1_objects,
    v1_tools,
    v1_desk,
    v1_compute,
    compute,
    compute_worker,
)
# Routers anyone may call: signing in and out (also with the company's account), and API v1 (which checks its own
# signed tokens, see ``api/identity.py``). Every other router goes through
# ``access_guard`` (the person's access level).
PUBLIC = {
    session,
    # A public demo's visits: entering one, and its frame's signs of life (api/routers/demo.py).
    demo,
    sso,
    v1,
    v1_links,
    v1_explore,
    v1_llm,
    v1_assistant,
    v1_people,
    v1_notebooks,
    v1_objects,
    v1_tools,
    v1_desk,
    mcp,
    # The Notebooks app trades a one-time code for its token (it checks the code itself).
    notebooks_pair,
    v1_compute,
    # The compute workers prove themselves with their own credential (docs/compute.md).
    compute_worker,
}

# Methods that change nothing, and where a browser says a request comes from this installation
# ("none": typed in the address bar or a bookmark).
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SAME_ORIGIN = {"same-origin", "none"}


def _mount_frontend(app: FastAPI) -> None:
    if not FRONTEND_DIST.is_dir():
        return
    # Built files are served from /static/; /assets/<id> is the asset deep link, a page of the
    # interface (docs/app-standard.md, sections 2 and 7).
    static = FRONTEND_DIST / "static"
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            # An API route that does not exist here (an app's routes live in the app).
            raise HTTPException(status_code=404, detail=t("Route not found."))
        if path == "static" or path.startswith("static/"):
            # A built file that does not exist: never answer it with the page.
            raise HTTPException(status_code=404, detail=t("Route not found."))
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


def _session_secret(runtime: ApiRuntime) -> str:
    """A random key kept beside the database, so it never derives from a password."""

    configured = os.environ.get("PLANTCRAFT_SESSION_SECRET_FILE", "").strip()
    path = (
        Path(configured)
        if configured
        else Path(runtime.scenario.storage.sqlite_path).with_name("session.secret")
    )
    try:
        secret = path.read_text(encoding="utf-8").strip()
        if secret:
            return secret
    except OSError:
        pass
    secret = secrets.token_hex(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create: server processes starting together end up with one key.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(secret)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip() or secret
    except OSError:
        # Read-only storage: sessions last until the next restart.
        pass
    return secret


def platform_version() -> str:
    """PlantCraft's version (the installed package's)."""

    try:
        return metadata.version("plantcraft")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def create_app(runtime: ApiRuntime | None = None) -> FastAPI:
    runtime = runtime or ApiRuntime.from_environment()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.start()
        atexit.register(runtime.stop)
        # What requests and the watch freed goes back to the system every minute.
        releaser = Releaser().start()
        yield
        releaser.stop()
        runtime.stop()

    app = FastAPI(
        title="PlantCraft API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    if runtime.auth.enabled:
        # The environment's administrator is a person too (listed with the users, audited).
        users, name = runtime.workspace.users, runtime.auth.username.strip().lower()
        if not users.get_user(name):
            users.upsert_user(name, "Administrator", "Administration")
        users.set_admin(name)

    demo = public_demo()
    if demo is not None:
        limiter = RateLimiter(demo.rate_per_minute)

        @app.middleware("http")
        async def public_demo_rate(request: Request, call_next):
            # Only what comes through the proxy counts: the suite's apps call PlantCraft inside the
            # internal network, without its mark, and Analytics' rounds alone pass 600 a minute.
            # Each demo visit has its own budget (visitors behind one company address must not
            # share one); anyone else, the client's address as the proxy forwarded it
            # (FORWARDED_ALLOW_IPS). The session is signed: a visit cannot be made up.
            visit = request.session.get("demo_visit") if "session" in request.scope else None
            client = (
                f"visit:{visit}" if visit else request.client.host if request.client else "unknown"
            )
            outside = EDGE_HEADER in request.headers
            if outside and request.url.path != "/healthz" and not limiter.allow(client):
                return JSONResponse(
                    status_code=429,
                    content={"detail": t("Too many requests. Wait a minute and try again.")},
                    headers={"Retry-After": "60"},
                )
            return await call_next(request)

    # How much one person asks API v1 for: notebooks, scripts, assistants (docs/en/notebooks.md).
    install_usage_limits(app, runtime)

    @app.middleware("http")
    async def same_site_writes(request: Request, call_next):
        # A write the browser sends with the session cookie from another site is refused
        # (review S1, 2026-10-27): SameSite=Lax lets a sibling server of the company's domain
        # (same site, other origin) post with the cookie. Browsers say where a request comes
        # from in Sec-Fetch-Site; a request with its own bearer token carries no cookie risk.
        if (
            request.method not in SAFE_METHODS
            and request.headers.get("sec-fetch-site", "same-origin") not in SAME_ORIGIN
            and not request.headers.get("authorization")
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": t("This change must come from PlantCraft's own pages.")},
            )
        return await call_next(request)

    @app.middleware("http")
    async def interface_language(request: Request, call_next):
        # The browser says which language to answer in; English when it says nothing we know.
        token = set_language(
            request.headers.get("x-language")
            or request.cookies.get(COOKIE)
            or request.headers.get("accept-language")
        )
        try:
            return await call_next(request)
        finally:
            reset_language(token)

    @app.middleware("http")
    async def plant_time_zone(request: Request, call_next):
        # Times are stored in UTC and shown in the plant's local time: every page of the suite
        # (the apps share this origin) reads the zone from this cookie (ui timeZone.ts).
        response = await call_next(request)
        zone = quote(plant_timezone().key, safe="")
        if request.cookies.get(TIME_ZONE_COOKIE) != zone:
            response.set_cookie(
                TIME_ZONE_COOKIE, zone, max_age=31_536_000, path="/", samesite="lax"
            )
        return response

    # Asset and signal lists grow with the plant (thousands of signals).
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    # Request ids and one log line per request, as in every app (docs/operations.md).
    app.add_middleware(RequestLog)
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(runtime),
        max_age=60 * 60 * 24 * runtime.auth.session_days,
        same_site="lax",
        # Behind HTTPS (a reverse proxy) the cookie never travels in clear.
        https_only=env_flag("PLANTCRAFT_SESSION_HTTPS_ONLY"),
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_body(_request: Request, exc: RequestValidationError):
        # Never echo the input: it may hold NaN or Infinity, which JSON cannot carry (G33).
        errors = [
            {
                "loc": list(error.get("loc", ())),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    for module in ROUTERS:
        # Conversations are open to readers (``open_to("viewer")`` on their writes).
        guard = [] if module in PUBLIC else [Depends(access_guard())]
        app.include_router(module.router, dependencies=guard)
    _mount_frontend(app)
    return app


def __getattr__(name: str):
    # ``uvicorn plantcraft.api.app:app`` builds the application on first access.
    if name == "app":
        runtime = ApiRuntime.from_environment()
        # JSON logs to the console and to <data>/logs/processcraft.jsonl (docs/operations.md).
        configure_logging(
            "processcraft",
            version=platform_version(),
            data_dir=Path(runtime.scenario.storage.sqlite_path).parent,
        )
        # The administrator's row is written here: one process at a time (``ops.workers``).
        with startup(Path(runtime.scenario.storage.sqlite_path).parent):
            globals()["app"] = create_app(runtime)
        return globals()["app"]
    raise AttributeError(name)
