"""Token verification in an app: dependency, middleware, redirects and key refresh."""

from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from plantcraft_sdk.auth import AuthError, TokenMiddleware, TokenVerifier, User, current_user
from plantcraft_sdk.testing import FakePlantCraft


@pytest.fixture()
def fake():
    return FakePlantCraft()


def _app(verifier: TokenVerifier) -> FastAPI:
    app = FastAPI()
    CurrentUser = Annotated[User, Depends(verifier.dependency)]

    @app.get("/api/whoami")
    def whoami(user: CurrentUser) -> dict:
        return {"username": user.username, "access": user.access, "can_edit": user.can_edit}

    @app.get("/loops")
    def page(user: CurrentUser) -> dict:
        return {"username": user.username}

    return app


def test_bearer_and_cookie_tokens_let_the_user_in(fake):
    client = TestClient(_app(fake.verifier("linkcraft")))
    bearer = {"Authorization": f"Bearer {fake.token('engineer')}"}
    assert client.get("/api/whoami", headers=bearer).json() == {
        "username": "engineer",
        "access": "editor",
        "can_edit": True,
    }
    client.cookies.set("processcraft_token", fake.token("operator"))
    assert client.get("/api/whoami").json()["access"] == "viewer"


def test_missing_or_bad_tokens_answer_401_or_redirect_browsers(fake):
    client = TestClient(_app(fake.verifier("linkcraft")), follow_redirects=False)
    response = client.get("/api/whoami")
    assert response.status_code == 401 and "detail" in response.json()
    assert response.headers["www-authenticate"] == "Bearer"
    page = client.get("/loops?area=north", headers={"Accept": "text/html"})
    assert page.status_code == 303
    assert page.headers["location"] == "/login?next=/loops%3Farea%3Dnorth"
    expired = {"Authorization": f"Bearer {fake.token('engineer', ttl=-120)}"}
    assert client.get("/api/whoami", headers=expired).status_code == 401
    wrong_aud = {"Authorization": f"Bearer {fake.token('engineer', aud='dashcraft')}"}
    assert client.get("/api/whoami", headers=wrong_aud).status_code == 401


def test_own_app_id_is_an_accepted_audience_and_access_is_checked(fake):
    client = TestClient(_app(fake.verifier("linkcraft")))
    own = {"Authorization": f"Bearer {fake.token('engineer', aud='linkcraft')}"}
    assert client.get("/api/whoami", headers=own).status_code == 200
    outsider = {"Authorization": f"Bearer {fake.token('outsider')}"}
    response = client.get("/api/whoami", headers=outsider)
    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to this application."


def test_unknown_kid_refreshes_the_cached_keys(fake):
    verifier = fake.verifier("linkcraft")
    assert verifier.user(fake.token("engineer")).username == "engineer"
    fake.rotate_key()
    # Cached keys are fresh, but the new kid forces one refresh.
    assert verifier.user(fake.token("engineer")).username == "engineer"
    assert len(verifier.keys()["keys"]) == 2


def test_forged_kids_do_not_hammer_processcraft(fake):
    calls = []
    http = fake.http_client()
    original = http.get

    def counting_get(url, **kwargs):
        if url.endswith("/auth/keys"):
            calls.append(url)
        return original(url, **kwargs)

    http.get = counting_get
    verifier = TokenVerifier("http://processcraft.test", "linkcraft", http_client=http)
    verifier.user(fake.token("engineer"))
    fake.rotate_key()
    for _ in range(2):
        verifier.user(fake.token("engineer"))  # first refreshes; the second uses the cache
    for _ in range(5):
        with pytest.raises(AuthError):
            verifier.user(FakePlantCraft().token("engineer"))
    assert len(calls) <= 2


def test_keys_unavailable_is_503_not_a_crash():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    verifier = TokenVerifier(
        "http://down.test", "linkcraft", http_client=httpx.Client(transport=transport)
    )
    with pytest.raises(AuthError) as error:
        verifier.user(FakePlantCraft().token("engineer"))
    assert error.value.status_code == 503


def test_middleware_guards_everything_but_public_paths(fake):
    app = FastAPI()

    @app.get("/healthz")
    def health() -> dict:
        return {"ok": True}

    @app.get("/static/app.js")
    def script() -> dict:
        return {"js": True}

    @app.get("/api/me")
    def me(request: __import__("fastapi").Request) -> dict:
        return {"username": current_user(request).username}

    app.add_middleware(
        TokenMiddleware, verifier=fake.verifier("linkcraft"), public_paths=("/healthz", "/static/")
    )
    client = TestClient(app, follow_redirects=False)
    assert client.get("/healthz").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Accept": "text/html"}).status_code == 303
    bearer = {"Authorization": f"Bearer {fake.token('operator')}"}
    assert client.get("/api/me", headers=bearer).json() == {"username": "operator"}
    outsider = {"Authorization": f"Bearer {fake.token('outsider')}"}
    assert client.get("/api/me", headers=outsider).status_code == 403


def test_a_revoked_person_is_shut_out_at_once(fake):
    verifier = fake.verifier("linkcraft")
    old = fake.token("engineer")
    assert verifier.user(old).username == "engineer"
    fake.revoke("engineer")
    verifier._revoked_at = -float("inf")  # the next read of the list, as after REVOKED_TTL
    with pytest.raises(AuthError) as error:
        verifier.user(old)
    assert error.value.status_code == 401
    # A token issued after the change (a fresh sign-in) is let in.
    assert verifier.user(fake.token("engineer")).username == "engineer"
    # Others are not affected.
    assert verifier.user(fake.token("operator")).username == "operator"


def test_a_revoked_app_key_ends_its_service_tokens(fake):
    verifier = fake.verifier("linkcraft")
    token = fake.token("app:linkcraft", apps={"linkcraft": "viewer"}, key_id="k1")
    assert verifier.user(token).is_service
    fake.revoked_keys.add("k1")
    verifier._revoked_at = -float("inf")
    with pytest.raises(AuthError):
        verifier.user(token)


def test_the_list_is_read_at_most_every_few_seconds_and_survives_an_outage(fake):
    verifier = fake.verifier("linkcraft")
    token = fake.token("engineer")
    before = fake.requests
    for _ in range(5):
        verifier.user(token)
    assert fake.requests - before <= 2  # the key set once, the list once
    fake.revoke("engineer")
    down = httpx.MockTransport(lambda request: httpx.Response(503))
    verifier.http = httpx.Client(transport=down)
    verifier._revoked_at = -float("inf")
    # Keys cached; the revocation list cannot be read: the last list read stays in force.
    assert verifier.user(token).username == "engineer"


def test_an_older_processcraft_without_the_list_still_lets_people_in():
    fake = FakePlantCraft()
    original = fake.http_client()
    verifier = TokenVerifier(
        "http://processcraft.test",
        "linkcraft",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (
                    httpx.Response(404)
                    if request.url.path.endswith("/revoked")
                    else original.get(str(request.url))
                )
            )
        ),
    )
    assert verifier.user(fake.token("engineer")).username == "engineer"
