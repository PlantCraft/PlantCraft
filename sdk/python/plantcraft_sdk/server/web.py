"""An app's web application: its API and built interface under one root path.

Everything lives under the app's prefix (``<APP>_ROOT_PATH``, ``/twin`` for example): the proxy
forwards ``/twin/*`` unchanged, PlantCraft serves ``/``. ``/healthz`` answers at both the root
and the prefix for container health checks. Every page needs a signed-in person, except the
``public_pages`` an app names (a public link checks its own token in the API). The endpoints every
app serves (``docs/app-standard.md``, section 7) are added here::

    api = suite_api(runtime, title="PlantCraft Twin", version=__version__, files=FILES,
                    routers=[twins.router, models.router], ui=ui_folder("twincraft", ROOT))
    app = mount(api, runtime, version=__version__)

The runtime has ``settings.root_path``, ``settings.processcraft_public_url``, ``verifier``,
``shutdown()`` and, for ``/api/status``, ``status()``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from plantcraft_sdk.auth import AuthError, User, wants_html
from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.i18n import LanguageMiddleware, t
from plantcraft_sdk.server import logread
from plantcraft_sdk.server.access import CurrentUser
from plantcraft_sdk.server.demo import DemoVisitLimit
from plantcraft_sdk.server.demo_slots import DemoSlots
from plantcraft_sdk.server.files import AppFiles
from plantcraft_sdk.server.logs import current_file
from plantcraft_sdk.server.memory import Releaser
from plantcraft_sdk.server.ops import RequestLog, can_read_metrics, metrics
from plantcraft_sdk.server.origin import SameSiteWrites
from plantcraft_sdk.server.queue import FORMAT as QUEUE_FORMAT
from plantcraft_sdk.server.search import search_answer
from plantcraft_sdk.utc import parse_instant


def _openapi() -> bool:
    return os.environ.get("PLANTCRAFT_OPENAPI", "").strip().lower() in {"1", "true", "yes", "on"}


LOGGER = logging.getLogger(__name__)
# A public page: never cached by a shared proxy, never sends its token on as a referrer.
PUBLIC_PAGE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def ui_folder(app_id: str, source_root: str | Path) -> Path | None:
    """The built interface: ``<APP>_UI_DIR``, else ``frontend/dist`` of a source checkout."""

    configured = os.environ.get(f"{app_id.upper()}_UI_DIR", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(source_root) / "frontend" / "dist")
    return next((path for path in candidates if (path / "index.html").is_file()), None)


def suite_api(
    runtime: Any,
    *,
    title: str,
    version: str,
    files: AppFiles,
    routers: Iterable[APIRouter] = (),
    ui: Path | None = None,
    me: Callable[[User], dict[str, Any]] | None = None,
    help_routes: bool = True,
    status_route: bool = True,
    public_pages: tuple[str, ...] = (),
) -> FastAPI:
    """The app's API and interface, mounted under its prefix by ``mount``.

    ``me`` adds the app's own fields to ``/api/me``. An app with its own ``/api/help`` passes
    ``help_routes=False`` and that router in ``routers``. ``public_pages`` are page prefixes
    (``"share/"``) served without a sign-in.
    """

    api = FastAPI(
        title=title,
        version=version,
        # The route list only when asked (PLANTCRAFT_OPENAPI=true, for development).
        docs_url="/api/docs" if _openapi() else None,
        openapi_url="/api/openapi.json" if _openapi() else None,
        redoc_url=None,
    )
    api.state.runtime = runtime
    api.state.files = files

    @api.exception_handler(PlantCraftError)
    async def processcraft_failed(_request: Request, exc: PlantCraftError) -> JSONResponse:
        # PlantCraft refused the request (a 4xx) or failed (502: this app's upstream).
        status = exc.status_code if 400 <= int(exc.status_code or 0) < 500 else 502
        return JSONResponse({"detail": str(exc.detail)}, status_code=status)

    @api.exception_handler(ValidationError)
    async def invalid_value(_request: Request, exc: ValidationError) -> JSONResponse:
        # A value the route built from the request failed its model's checks (a folder id with
        # other characters): the request was wrong, not the server (API fuzzing, 2026-10-31).
        errors = exc.errors()
        message = str(errors[0].get("msg", "")) if errors else ""
        return JSONResponse({"detail": message or t("Invalid value.")}, status_code=422)

    @api.exception_handler(UnicodeError)
    async def broken_text(_request: Request, _exc: UnicodeError) -> JSONResponse:
        return JSONResponse({"detail": t("The text has characters that are not valid.")}, 422)

    @api.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unexpected error", exc_info=exc)
        return JSONResponse({"detail": t("Unexpected error; see the server log.")}, 500)

    @api.get("/healthz", include_in_schema=False)
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": version}

    @api.get("/api/me")
    def who(user: CurrentUser) -> dict[str, Any]:
        # A public demo visit: the interface shows its editors, the API saves nothing
        # (plantcraft_sdk.server.demo).
        demo = user.demo
        return {
            "username": user.username,
            "name": user.name,
            "level": user.level,
            "access": "editor" if demo else user.access,
            # What the user menu shows: the PlantCraft level for an admin (whose app
            # access is still "editor"), else this app's access ("editor" or "viewer").
            "role": "admin" if user.is_admin else user.access,
            "can_edit": user.can_edit or demo is not None,
            "is_admin": user.is_admin,
            "demo": {"ends": demo.get("ends")} if demo else None,
            "processcraft_url": runtime.settings.processcraft_public_url or "/",
            "version": version,
            **(me(user) if me else {}),
        }

    @api.get("/api/meta")
    def app_meta(_user: CurrentUser) -> dict[str, Any]:
        """``app.toml`` and the build revision (the suite's app standard, section 7)."""

        return files.meta()

    if help_routes:

        @api.get("/api/help")
        def help_index(_user: CurrentUser) -> list[dict[str, str]]:
            return files.help_pages()

        @api.get("/api/help/{page_id}")
        def help_one(page_id: str, _user: CurrentUser) -> dict[str, str]:
            page = files.help_page(page_id)
            if page is None:
                raise HTTPException(status_code=404, detail=t("Help page not found."))
            return page

    @api.get("/api/ops/metrics", include_in_schema=False)
    def ops_metrics(user: CurrentUser) -> dict[str, Any]:
        """Requests, logged warnings and errors, uptime (PlantCraft's monitor reads them)."""

        if not can_read_metrics(user):
            raise HTTPException(status_code=403, detail=t("Only an administrator can do this."))
        return metrics(files.app_id, version)

    @api.get("/api/ops/logs", include_in_schema=False)
    def ops_logs(
        user: CurrentUser,
        since: str | None = None,
        until: str | None = None,
        level: str | None = None,
        text: str | None = Query(default=None, max_length=200),
        request_id: str | None = Query(default=None, max_length=64),
        logger: str | None = Query(default=None, max_length=200),
        limit: int = Query(default=logread.DEFAULT_LIMIT, ge=1, le=logread.MAX_LIMIT),
    ) -> dict[str, Any]:
        """This server's own log, newest first (PlantCraft's Operations › Logs reads it)."""

        if not can_read_metrics(user):
            raise HTTPException(status_code=403, detail=t("Only an administrator can do this."))
        bounds = {}
        for name, value in (("since", since), ("until", until)):
            moment = parse_instant(value) if value else None
            if value and moment is None:
                raise HTTPException(status_code=422, detail=t("Use an ISO 8601 time."))
            bounds[name] = moment
        if level and level.upper() not in logread.LEVELS:
            raise HTTPException(status_code=422, detail=t("Unknown log level."))
        found = logread.read_logs(
            current_file(),
            level=level,
            text=text,
            request_id=request_id,
            logger=logger,
            limit=limit,
            **bounds,
        )
        return {"app": files.app_id, "version": version, **found}

    if status_route:

        @api.get("/api/status")
        def status(_user: CurrentUser) -> dict[str, Any]:
            return {**runtime.status(), "version": version}

    for router in routers:
        api.include_router(router)

    # The suite's frame asks every app these two (docs/app-standard.md section 10). An app that
    # answers them passes its own routes in ``routers`` (registered first, so they win); any
    # other app says it holds nothing, so the frame's probes never end in a 404.
    @api.get("/api/search", include_in_schema=False)
    def no_search(_user: CurrentUser) -> dict[str, Any]:
        return search_answer([])

    @api.get("/api/queue", include_in_schema=False)
    def no_queue(_user: CurrentUser) -> dict[str, Any]:
        return {"format": QUEUE_FORMAT, "now": None, "history": []}

    @api.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def unknown_api(rest: str) -> None:
        raise HTTPException(status_code=404, detail=t("Not found."))

    if ui is not None:
        folder = ui
        # Built files live in static/: assets/<id> is the suite's page for one asset.
        if (folder / "static").is_dir():
            api.mount("/static", StaticFiles(directory=folder / "static"), name="static")

        @api.get("/{path:path}", include_in_schema=False)
        def interface(path: str, request: Request) -> Any:
            target = (folder / path).resolve()
            if path and folder in target.parents and target.is_file():
                return FileResponse(target)
            if public_pages and path.startswith(public_pages):
                return FileResponse(folder / "index.html", headers=PUBLIC_PAGE_HEADERS)
            # Pages need a signed-in person: send a browser without a token to sign in.
            try:
                runtime.verifier.user(runtime.verifier.token_from(request.headers, request.cookies))
            except AuthError as error:
                if error.status_code == 401 and wants_html(request.method, request.headers):
                    location = runtime.verifier.login_redirect(request.url.path, request.url.query)
                    return RedirectResponse(location, status_code=303)
                raise HTTPException(error.status_code, error.detail) from error
            return FileResponse(folder / "index.html", headers={"Cache-Control": "no-cache"})

    return api


def mount(
    api: FastAPI,
    runtime: Any,
    *,
    version: str,
    on_start: Callable[[], None] | None = None,
) -> FastAPI:
    """The application the server runs: ``api`` under the runtime's root path, ``/healthz`` at
    the root, and the runtime started (``on_start``, else ``runtime.start()``) and shut down
    with it. Every request gets an id and a log line (``plantcraft_sdk.server.ops``)."""

    root = runtime.settings.root_path
    start = on_start or getattr(runtime, "start", None)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start is not None:
            start()
        files = getattr(api.state, "files", None)
        send = getattr(runtime, "send_contributions", None) or getattr(
            runtime, "send_event_catalog", None
        )
        if files is not None and send is not None:
            try:
                send(files.manifest())
            except Exception:  # what the app adds never stops it from starting
                LOGGER.exception("Contributions not sent")
        # What requests freed goes back to the system every minute (server.memory).
        releaser = Releaser().start()
        try:
            yield
        finally:
            releaser.stop()
            runtime.shutdown()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime
    app.state.api = api

    @app.get("/healthz", include_in_schema=False)
    def health() -> Any:
        # A runtime may name a problem the web server alone does not show, such as a child
        # process that keeps dying for lack of memory (pc-carga, 2026-11-01): the container's
        # health check then fails and System health, Operations and monitoring see it.
        check = getattr(runtime, "health_problem", None)
        problem = check() if callable(check) else None
        if problem:
            return JSONResponse(
                {"status": "unhealthy", "version": version, "problem": str(problem)},
                status_code=503,
            )
        return {"status": "ok", "version": version}

    if root:

        @app.get("/", include_in_schema=False)
        def home() -> RedirectResponse:
            return RedirectResponse(f"{root}/", status_code=307)

        @app.get(root, include_in_schema=False)
        def bare_root() -> RedirectResponse:
            return RedirectResponse(f"{root}/", status_code=307)

        app.mount(root, api)
    else:
        app.mount("/", api)
    # A public demo visit's requests, a few at once (plantcraft_sdk.server.demo).
    app.add_middleware(DemoVisitLimit)
    # An isolated demo visit works on its own copy of the app's database (server.demo_slots).
    app.add_middleware(DemoSlots, runtime=runtime)
    # A write with the cookie from another site of the domain is refused (server.origin).
    app.add_middleware(SameSiteWrites)
    # Text in the language the page chose (plantcraft_sdk.i18n).
    app.add_middleware(LanguageMiddleware)
    app.add_middleware(RequestLog)
    return app
