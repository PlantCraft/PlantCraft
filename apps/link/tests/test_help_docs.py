"""The help browser's pages: every guide and method is listed and served as Markdown."""

from __future__ import annotations

from linkcraft.catalog import signal_checks
from linkcraft.catalog.help_docs import GUIDES, GUIDES_DIR
from linkcraft.catalog.registry import METHOD_SPECS


def test_every_guide_file_is_listed_and_every_listed_guide_exists():
    files = {path.stem for path in GUIDES_DIR.glob("*.md")}
    listed = {name for name, _ in GUIDES} - {"loop-types"}
    assert files == listed


def test_the_index_has_guides_and_three_method_folders(client):
    docs = client.get("/link/api/help/docs").json()
    ids = [doc["id"] for doc in docs]
    assert ids[0] == "guides/overview"
    assert {f"methods/{key}" for key in METHOD_SPECS} <= set(ids)
    assert {f"methods/{key}" for key in signal_checks.CHECKS} <= set(ids)
    assert {doc["category"] for doc in docs if doc["id"].startswith("methods/")} == {
        "Methods/Data quality",
        "Methods/Loop data gate",
        "Methods/Control loop performance",
    }
    assert all(doc["title"] for doc in docs)


def test_every_page_is_served_as_markdown(client):
    for doc in client.get("/link/api/help/docs").json():
        response = client.get(f"/link/api/help/docs/{doc['id']}")
        assert response.status_code == 200, doc["id"]
        page = response.json()
        assert page["markdown"].startswith("# "), doc["id"]
        assert page["title"] == doc["title"]
    assert client.get("/link/api/help/docs/guides/nothing").status_code == 404
    assert client.get("/link/api/help/docs/methods/sq_nothing").status_code == 404
    assert client.get("/link/api/help/docs/other").status_code == 404


def test_method_pages_show_their_parameters_and_references(client):
    page = client.get("/link/api/help/docs/methods/oscillation_autocorrelation").json()
    assert "| Parameter | Default | This site | Meaning |" in page["markdown"]
    assert "doi.org" in page["markdown"]
    check = client.get("/link/api/help/docs/methods/sq_spikes").json()["markdown"]
    assert "`half_window` | 5 |" in check
    assert "Hampel" in check


def test_loop_types_guide_is_a_table_of_the_defaults(client):
    page = client.get("/link/api/help/docs/guides/loop-types").json()["markdown"]
    assert "| Loop type | Starting algorithm |" in page
    assert "missing or unknown" in page


def test_the_app_index_points_at_the_help_browser(client):
    pages = client.get("/link/api/help").json()["pages"]
    assert pages[0]["url"] == "/link/help?doc=guides/overview"
    assert all(page["api"].startswith("/link/api/help/docs/") for page in pages)
