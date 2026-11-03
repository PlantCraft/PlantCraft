"""Interface languages: English source text, complete and consistent catalogs."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plantcraft import i18n
from plantcraft.api.app import create_app
from plantcraft.i18n import t

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = {
    "backend": ROOT / "plantcraft" / "i18n" / "locales" / "pt-BR.json",
    "frontend": ROOT / "frontend" / "src" / "locales" / "pt-BR.json",
}
FIELD = re.compile(r"\{(\w*)\}")


@pytest.fixture(autouse=True)
def _translations_on(monkeypatch):
    # Translations ship switched off; these tests keep the catalogs working for when they return.
    monkeypatch.setenv("PLANTCRAFT_TRANSLATIONS", "1")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def _catalog(name: str) -> dict[str, str]:
    return json.loads(CATALOGS[name].read_text(encoding="utf-8"))


def test_catalogs_are_flat_and_keep_their_fields():
    for name in CATALOGS:
        for english, portuguese in _catalog(name).items():
            assert isinstance(portuguese, str) and portuguese.strip(), (name, english)
            assert sorted(FIELD.findall(english)) == sorted(FIELD.findall(portuguese)), (
                name,
                english,
            )


def test_language_comes_from_the_request_and_defaults_to_english():
    assert i18n.normalize("pt-BR,en;q=0.8") == "pt-BR"
    assert i18n.normalize("pt") == "pt-BR"
    assert i18n.normalize("en-US") == "en"
    assert i18n.normalize("de-DE") is None
    token = i18n.set_language("fr")
    try:
        assert i18n.current_language() == "en"
    finally:
        i18n.reset_language(token)


def test_t_translates_and_fills_fields():
    english = next((key for key in _catalog("backend") if "{" not in key), None)
    if english is None:
        return
    token = i18n.set_language("pt-BR")
    try:
        assert t(english) == _catalog("backend")[english]
        assert t("No such text {x}.", x=1) == "No such text 1."
    finally:
        i18n.reset_language(token)
    assert t(english) == english


def test_api_answers_in_the_language_asked(client: TestClient):
    english = client.get("/api/map/format").json()
    portuguese = client.get("/api/map/format", headers={"X-Language": "pt-BR"}).json()
    assert english != portuguese


def test_translations_off_answers_in_english(monkeypatch):
    monkeypatch.delenv("PLANTCRAFT_TRANSLATIONS")
    assert i18n.normalize("pt-BR") == "en"
    assert i18n.normalize("") is None
    token = i18n.set_language("pt-BR")
    try:
        assert i18n.current_language() == "en"
    finally:
        i18n.reset_language(token)


def test_pages_learn_whether_translations_are_on(client, monkeypatch):
    # Every page of the suite (apps included) offers other languages only from this cookie.
    assert client.get("/healthz").cookies.get(i18n.TRANSLATIONS_COOKIE) == "1"
    assert i18n.TRANSLATIONS_COOKIE not in client.get("/healthz").headers.get("set-cookie", "")
    monkeypatch.setenv("PLANTCRAFT_TRANSLATIONS", "0")
    assert client.get("/healthz").cookies.get(i18n.TRANSLATIONS_COOKIE) == "0"


def test_sdk_text_is_translated_through_the_platform(monkeypatch):
    from plantcraft_sdk import i18n as sdk_i18n

    monkeypatch.setattr(sdk_i18n, "catalog", lambda language: {"Only in the SDK": "Só no SDK"})
    i18n.catalog.cache_clear()
    token = i18n.set_language("pt-BR")
    try:
        assert t("Only in the SDK") == "Só no SDK"
    finally:
        i18n.reset_language(token)
        i18n.catalog.cache_clear()
