"""Inputs the API fuzzing of 2026-10-31 (D17) turned into 500s: each is now refused, not a crash."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_security import ADMIN_PASSWORD, _login, app  # noqa: F401  (fixture)


def test_numbers_larger_than_the_database_takes_are_not_found(app):  # noqa: F811
    with TestClient(app):
        admin = _login(app, "admin", ADMIN_PASSWORD)
        answer = admin.get("/api/desk/events/5934862729859490119680")
        assert answer.status_code in (404, 422), answer.text
        answer = admin.post(
            "/api/messages/conversations/-205411290084619517952/messages", json={"text": "hi"}
        )
        assert answer.status_code in (404, 422), answer.text


def test_broken_unicode_and_null_characters_are_refused(app):  # noqa: F811
    with TestClient(app):
        client = TestClient(app)
        answer = client.post(
            "/api/login",
            content=b'{"password": "x", "username": "\\u00a1\\u0084L\\udb94\\udf82"}',
            headers={"Content-Type": "application/json"},
        )
        assert answer.status_code in (401, 422), answer.text
        admin = _login(app, "admin", ADMIN_PASSWORD)
        answer = admin.post(
            "/api/messages/conversations/1/messages",
            content=b'{"text": "a\\ud89c\\udfdb", "ref": "\\u0000x"}',
            headers={"Content-Type": "application/json"},
        )
        assert answer.status_code < 500, answer.text
