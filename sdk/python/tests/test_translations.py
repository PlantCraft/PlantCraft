"""The suite's translations: catalogs per module, the request's language, the coverage check."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plantcraft_sdk import i18n, i18n_check


@pytest.fixture()
def app_catalog(tmp_path, monkeypatch):
    folder = tmp_path / "locales"
    folder.mkdir()
    (folder / "pt-BR.json").write_text(
        json.dumps({"Rule {name} not found.": "Regra {name} não encontrada."})
    )
    monkeypatch.setattr(i18n, "_folders", [i18n.LOCALES])
    monkeypatch.setattr(i18n, "_translate", None)
    monkeypatch.setattr(i18n, "_language", None)
    i18n.catalog.cache_clear()
    i18n.use_catalogs(folder)
    yield folder
    i18n.catalog.cache_clear()


def test_text_is_english_outside_a_request(app_catalog):
    assert i18n.current_language() == "en"
    assert i18n.t("Rule {name} not found.", name="R1") == "Rule R1 not found."


def test_text_follows_the_language_set_for_the_request(app_catalog):
    token = i18n.set_language("pt-BR")
    try:
        assert i18n.t("Rule {name} not found.", name="R1") == "Regra R1 não encontrada."
        assert i18n.t("Not in any catalog") == "Not in any catalog"
    finally:
        i18n.reset_language(token)


def test_language_comes_from_the_page_header_or_the_suite_cookie(app_catalog):
    app = FastAPI()

    @app.get("/sync")
    def sync() -> dict:
        return {
            "language": i18n.current_language(),
            "text": i18n.t("Rule {name} not found.", name="R"),
        }

    @app.get("/async")
    async def not_sync() -> dict:
        return {"language": i18n.current_language()}

    app.add_middleware(i18n.LanguageMiddleware)
    client = TestClient(app)
    assert client.get("/sync", headers={"X-Language": "pt-BR"}).json() == {
        "language": "pt-BR",
        "text": "Regra R não encontrada.",
    }
    client.cookies.set(i18n.COOKIE, "pt-BR")
    assert client.get("/async").json() == {"language": "pt-BR"}
    client.cookies.set(i18n.COOKIE, "en")
    assert client.get("/sync").json()["language"] == "en"
    client.cookies.clear()
    # The browser's own Accept-Language never turns a translation on: the page chooses.
    assert client.get("/async", headers={"Accept-Language": "pt-BR"}).json() == {"language": "en"}


def test_normalize_knows_the_suite_languages():
    assert i18n.normalize("pt-BR,en;q=0.8") == "pt-BR"
    assert i18n.normalize("pt_br") == "pt-BR"
    assert i18n.normalize("en-GB") == "en"
    assert i18n.normalize("de") is None
    assert i18n.normalize(None) is None


def test_the_sdk_catalog_is_shipped_and_well_formed():
    data = json.loads((i18n.LOCALES / "pt-BR.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def _module(tmp_path, catalog: dict) -> None:
    src = tmp_path / "app" / "frontend" / "src"
    (src / "locales").mkdir(parents=True)
    (src / "Page.tsx").write_text(
        'const a = t("Save"); const b = t(\'Open {name}\', { name }); const c = tt("Tour only");\n'
    )
    (src / "Page.test.tsx").write_text('t("Only in a test")\n')
    (src / "locales" / "pt-BR.json").write_text(json.dumps(catalog))
    pkg = tmp_path / "app" / "src" / "appcraft"
    (pkg / "locales").mkdir(parents=True)
    (pkg / "rules.py").write_text(
        'raise ValueError(t("Rule {name} "\n    "not found.", name=name))\n'
    )


def test_check_counts_missing_texts_and_fails_only_when_strict(tmp_path, capsys):
    _module(tmp_path, {"Save": "Salvar"})
    assert i18n_check.main([str(tmp_path / "app")]) == 0
    out = capsys.readouterr().out
    assert "1/2 translated" in out and "0/1 translated" in out
    assert i18n_check.main([str(tmp_path / "app"), "--strict"]) == 1
    capsys.readouterr()
    assert i18n_check.main([str(tmp_path / "app"), "--missing"]) == 0
    out = capsys.readouterr().out
    assert "missing: Open {name}" in out and "missing: Rule {name} not found." in out
    assert "Tour only" not in out and "Only in a test" not in out


def test_check_fails_on_a_broken_catalog(tmp_path):
    _module(tmp_path, {"Open {name}": "Abrir {nome}"})
    assert i18n_check.main([str(tmp_path / "app")]) == 1


def test_a_document_is_read_in_the_current_language_when_translated(app_catalog, tmp_path):
    english = tmp_path / "help" / "alarms.md"
    english.parent.mkdir()
    english.write_text("# Alarms\n")
    other = tmp_path / "help" / "rules.md"
    other.write_text("# Rules\n")
    (tmp_path / "help" / "pt-BR").mkdir()
    (tmp_path / "help" / "pt-BR" / "alarms.md").write_text("# Alarmes\n")
    assert i18n.localized(english) == english
    token = i18n.set_language("pt-BR")
    try:
        assert i18n.localized(english).read_text() == "# Alarmes\n"
        assert i18n.localized(other) == other
    finally:
        i18n.reset_language(token)
