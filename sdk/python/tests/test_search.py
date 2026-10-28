"""An app's part of the suite's search (plantcraft_sdk.server.search) and the answers every
app gives the frame's probes when it does not search or queue (docs/app-standard.md section 10)."""

from fastapi import APIRouter
from fastapi.testclient import TestClient
from test_server import _repo, _runtime

from plantcraft_sdk.server.search import SearchItem, matches, search_answer, search_text
from plantcraft_sdk.server.web import mount, suite_api
from plantcraft_sdk.testing import FakePlantCraft


def test_search_text_needs_two_letters_and_folds_spaces():
    assert search_text(None) == "" and search_text(" a ") == ""
    assert search_text("  FIC   101 ") == "FIC 101"


def test_matches_wants_every_word_in_any_field():
    assert matches("fic flow", "FIC-101", "Feed flow")
    assert not matches("fic level", "FIC-101", "Feed flow", None)


def test_answer_ranks_exact_then_prefix_and_cuts_to_size():
    items = [
        SearchItem("Feed FIC-101", "a"),
        SearchItem("FIC-1011", "/b", type="Point", detail="x" * 300),
        SearchItem("fic-101", "/c"),
    ]
    answer = search_answer(items, "FIC-101", limit=2)
    assert answer["format"] == "plantcraft-search/1"
    assert [item["href"] for item in answer["items"]] == ["/c", "/b"]
    assert len(answer["items"][1]["detail"]) == 160 and answer["items"][0]["type"] is None
    assert search_answer(items, "x", limit=0)["items"] == []


def _client(tmp_path, routers=()):
    fake = FakePlantCraft()
    runtime = _runtime(fake)
    api = suite_api(runtime, title="Demo", version="0.1.0", files=_repo(tmp_path), routers=routers)
    return fake, TestClient(mount(api, runtime, version="0.1.0"))


def test_an_app_that_neither_searches_nor_queues_answers_the_probes(tmp_path):
    fake, client = _client(tmp_path)
    headers = {"Authorization": f"Bearer {fake.token('engineer')}"}
    assert client.get("/demo/api/search?q=fic", headers=headers).json() == {
        "format": "plantcraft-search/1",
        "items": [],
    }
    queue = client.get("/demo/api/queue?window=1h", headers=headers).json()
    assert queue["format"] == "plantcraft-queue/1" and queue["now"] is None
    assert client.get("/demo/api/search?q=fic").status_code == 401


def test_an_apps_own_search_wins(tmp_path):
    router = APIRouter()

    @router.get("/api/search")
    def own(q: str = "") -> dict:
        return search_answer([SearchItem("Mine", "/mine")], q)

    fake, client = _client(tmp_path, [router])
    headers = {"Authorization": f"Bearer {fake.token('engineer')}"}
    found = client.get("/demo/api/search?q=mi", headers=headers).json()
    assert found["items"][0]["href"] == "/mine"
