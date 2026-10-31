"""API v1 reads, served by the Historian itself to every app of the suite (docs/data-layer.md).

PlantCraft's API v1 forwards its signal and series reads here (``/api/v1/data``); an app can
also send them straight to the Historian, saving a hop through PlantCraft and its JSON on long
reads. Same paths, shapes, limits and errors as PlantCraft's ``docs/api-v1.md``:

| Route | Answer |
|---|---|
| ``GET /api/v1/reads`` | ``{"api": 1}``: this Historian serves the reads below (the SDK asks once) |
| ``GET /api/v1/signals?q&app&subject&result`` | the signals |
| ``GET /api/v1/signals/{id}`` | one signal |
| ``GET /api/v1/signals/{id}/series?start&end&step&sampling&max_gap`` | its recorded values, or a grid (averaged or interpolated) |
| ``POST /api/v1/series`` | many signals' series (``{signals, start, end, step, sampling, max_gap}``) |
| ``GET /api/v1/signals/{id}/value?agg&window`` | an aggregate |
| ``GET /api/v1/signals/{id}/summary?start&end&per`` | count, time covered, % good, total, mean, min, max, std |

Who may read is who may read PlantCraft's API v1: a token PlantCraft signed (a person's or
an app's service token), not ended early (``/api/v1/auth/revoked``, read again every few
seconds), whose level is viewer, editor or admin. Access to the Historian app itself is not
needed: a person who reads series in Link reads them here too. Nothing here writes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from plantcraft_sdk.asset_scope import AssetScope
from plantcraft_sdk.auth import AuthError
from plantcraft_sdk.wire import FORMAT as WIRE_FORMAT

from histcraft.api.deps import RuntimeDep, in_scope
from histcraft.api.routers import data
from histcraft.db import read_timeout
from histcraft.i18n import t

router = APIRouter(prefix="/api/v1", tags=["reads"])
# The levels that read plant data in PlantCraft's API v1 (its ``READ_LEVELS``).
READ_LEVELS = {"viewer", "editor", "admin"}
# Raised when the routes or their shapes change in a way older clients cannot read.
READS_API = 1


def reader(request: Request, runtime: RuntimeDep) -> dict[str, Any]:
    """The verified claims of the caller; 401 without a valid token, 403 below viewer."""

    verifier = runtime.verifier
    token = verifier.token_from(request.headers, request.cookies)
    try:
        claims = verifier.claims(token)
        verifier.check_revoked(claims)
    except AuthError as error:
        headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
        raise HTTPException(error.status_code, error.detail, headers=headers) from error
    if str(claims.get("level") or "viewer") not in READ_LEVELS:
        raise HTTPException(403, t("Your access is limited to dashboards."))
    request.state.reader_token = token
    return claims


Reader = Annotated[dict[str, Any], Depends(reader)]


def reader_scope(request: Request, runtime: RuntimeDep, claims: Reader) -> AssetScope:
    """The part of the plant the caller sees (token claim ``assets``, PlantCraft's
    docs/asset-scope.md): a signal outside it reads as one that is not here."""

    return runtime.claims_scope(claims, request.state.reader_token)


ReaderScope = Annotated[AssetScope, Depends(reader_scope)]


@router.get("/reads")
def reads(_caller: Reader) -> dict[str, Any]:
    # ``formats``: the answers ``POST /series`` also writes besides JSON (``Accept``).
    return {"api": READS_API, "formats": [WIRE_FORMAT]}


@router.get("/signals")
def signals(
    runtime: RuntimeDep,
    scope: ReaderScope,
    q: str = Query(default="", max_length=200),
    app: str | None = Query(default=None, max_length=40),
    subject: str | None = Query(default=None, max_length=300),
    result: str | None = Query(default=None, max_length=60),
) -> Any:
    found = data.signals(runtime, None, q=q, app=app, subject=subject, result=result)
    if not scope.everything:
        found = [item for item in found if scope.signal(item["id"])]
    return JSONResponse(found)


@router.get("/signals/{signal_id:path}/series")
def series(
    signal_id: str,
    runtime: RuntimeDep,
    scope: ReaderScope,
    start: str | None = Query(default=None, max_length=64),
    end: str | None = Query(default=None, max_length=64),
    step: float | None = None,
    sampling: str | None = Query(default=None, max_length=20),
    max_gap: float | None = None,
) -> Any:
    in_scope(scope, signal_id)
    # Written straight to JSON: long lists skip FastAPI's per-item encoder.
    return data.series(
        signal_id,
        runtime,
        None,
        start=start,
        end=end,
        step=step,
        sampling=sampling,
        max_gap=max_gap,
    )


@router.get("/signals/{signal_id:path}/summary")
def summary(
    signal_id: str,
    runtime: RuntimeDep,
    scope: ReaderScope,
    start: str | None = Query(default=None, max_length=64),
    end: str | None = Query(default=None, max_length=64),
    per: str | None = Query(default=None, max_length=5),
) -> Any:
    in_scope(scope, signal_id)
    return JSONResponse(data.summary(signal_id, runtime, None, start=start, end=end, per=per))


@router.get("/signals/{signal_id:path}/value")
def value(
    signal_id: str,
    runtime: RuntimeDep,
    scope: ReaderScope,
    agg: str = Query(default="last", max_length=10),
    window: str = Query(default="1h", max_length=20),
    end: str | None = Query(default=None, max_length=40),
) -> Any:
    in_scope(scope, signal_id)
    return JSONResponse(data.value(signal_id, runtime, None, agg=agg, window=window, end=end))


@router.get("/signals/{signal_id:path}")
def signal(signal_id: str, runtime: RuntimeDep, scope: ReaderScope) -> Any:
    in_scope(scope, signal_id)
    return JSONResponse(data.signal(signal_id, runtime, None))


@router.post("/series")
def series_batch(
    body: data.BatchIn, runtime: RuntimeDep, scope: ReaderScope, request: Request
) -> Any:
    binary = data.wants_binary(request)
    hidden = [item for item in body.signals if isinstance(item, str) and not scope.signal(item)]
    if not hidden:
        return data.series_batch(body, runtime, None, request)
    # Signals outside the caller's part of the plant answer as signals that are not here.
    shown = [item for item in body.signals if item not in hidden]
    missing = [
        {"signal": item, "status": 404, "detail": t("Signal {id} not found.", id=item)}
        for item in dict.fromkeys(hidden)
    ]
    if not shown:
        return JSONResponse({"series": [], "errors": missing})
    with read_timeout(runtime.settings.query_timeout), runtime.read_budget.hold() as ticket:
        answer = data.read_batch(
            body.model_copy(update={"signals": shown}), runtime, ticket, binary=binary
        )
        return answer.response(missing)
