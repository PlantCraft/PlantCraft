"""The demo seed's documents (``demo_seed.doccraft``): the Simulator plant's manuals, narratives,
guides and incidents sent to Documents once, in their folders, linked to their assets, and the
files the manifest names are the ones in ``deploy/demo/documents``."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from plantcraft import demo_seed

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "deploy" / "demo" / "documents"


class Library(demo_seed.Http):
    """Documents as the seed sees it: folders and documents kept in memory."""

    def __init__(self) -> None:
        super().__init__("http://doccraft:8150/docs")
        self.folders: list[dict] = []
        self.documents: list[dict] = []
        self.assets: dict[str, list[str]] = {}

    def call(self, method, path, body=None, *, ok=(), raw=None, content_type="application/json"):
        if (method, path) == ("GET", "/api/folders"):
            return 200, self.folders
        if (method, path) == ("POST", "/api/folders"):
            self.folders.append({"folder_id": f"f{len(self.folders)}", **body})
            return 201, self.folders[-1]
        if (method, path) == ("GET", "/api/documents"):
            return 200, self.documents
        if method == "POST" and path.startswith("/api/documents?"):
            fields = {key: values[0] for key, values in parse_qs(urlsplit(path).query).items()}
            self.documents.append({"doc_id": f"d{len(self.documents)}", "size": len(raw), **fields})
            return 201, self.documents[-1]
        if method == "PUT" and path.endswith("/assets"):
            self.assets[path.split("/")[3]] = body["assets"]
            return 200, {}
        raise AssertionError(f"unexpected {method} {path}")


def test_the_demo_documents_go_to_their_folders_once_and_name_their_assets(tmp_path):
    manifest = json.loads((DOCS / "manifest.json").read_text(encoding="utf-8"))
    suite = demo_seed.Suite(
        "http://processcraft:8060",
        {},
        "admin",
        "x",
        "y",
        ROOT / "deploy" / "demo" / demo_seed.DEMO_MAP,
    )
    library = Library()
    demo_seed.doccraft(library, suite)
    assert len(library.documents) == len(manifest["documents"]) == 12
    assert {folder["name"] for folder in library.folders} == set(demo_seed.DOC_FOLDERS)
    guide = next(doc for doc in library.documents if doc["number"] == "DOC-TG-001")
    assert (
        guide["kind"] == "Troubleshooting guide"
        and guide["filename"].endswith(".pdf")
        and guide["size"] > 10_000
    )
    assert (
        next(f for f in library.folders if f["folder_id"] == guide["folder"])["name"]
        == "Process control"
    )
    history = next(doc for doc in library.documents if doc["number"] == "DOC-MH-001")
    assert (
        "FV-1003" in library.assets[history["doc_id"]]
        and "U-200" in library.assets[guide["doc_id"]]
    )
    # Run again: nothing is sent twice.
    demo_seed.doccraft(library, suite)
    assert len(library.documents) == 12 and len(library.folders) == 3


def test_every_file_the_manifest_names_is_there_and_every_question_names_a_document():
    manifest = json.loads((DOCS / "manifest.json").read_text(encoding="utf-8"))
    numbers = {doc["number"] for doc in manifest["documents"]}
    for doc in manifest["documents"]:
        assert (DOCS / doc["file"]).is_file(), doc["file"]
    questions = json.loads((DOCS / "eval-questions.json").read_text(encoding="utf-8"))
    assert len(questions) == 40
    assert all(item["document"] in numbers or item["document"] in ("", None) for item in questions)
