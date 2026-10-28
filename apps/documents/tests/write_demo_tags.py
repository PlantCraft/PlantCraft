"""Writes PlantCraft's ``tests/fixtures/demo-documents-tags.json.gz``: what ``find_tags`` answers
for every tag the twelve demo documents (``deploy/demo/documents``) name, read by this app.

PlantCraft's plant-draft tests (``tests/test_plant_draft.py``) read it in place of a running
Documents, so its rules are measured against the real passages. After changing the demo
documents or how this app cuts them into passages: ``python -m tests.write_demo_tags``.
"""

from __future__ import annotations

import gzip
import json
import re
import tempfile
from pathlib import Path

from tests.conftest import client_for, index, make_runtime, send
from tests.plant import make_fake

SUITE = Path(__file__).resolve().parents[3]
DOCS = SUITE / "deploy" / "demo" / "documents"
OUT = SUITE / "tests" / "fixtures" / "demo-documents-tags.json.gz"
TAG = re.compile(r"\b([A-Z]{1,5})-\s?(\d{2,5}[A-Z]?)\b")


def write() -> None:
    manifest = json.loads((DOCS / "manifest.json").read_text(encoding="utf-8"))
    fake = make_fake()
    with tempfile.TemporaryDirectory() as folder:
        runtime = make_runtime(Path(folder), fake)
        try:
            with client_for(runtime, fake) as client:
                tags: set[str] = set()
                for doc in manifest["documents"]:
                    fields = {
                        key: doc[key]
                        for key in ("number", "title", "kind", "unit", "revision")
                        if doc.get(key)
                    }
                    send(client, doc["file"], (DOCS / doc["file"]).read_bytes(), **fields)
                while index(runtime):
                    pass
                for doc in client.get("/api/documents").json():
                    passages = client.get(f"/api/documents/{doc['doc_id']}/passages").json()
                    for passage in passages:
                        text = f"{passage['section']} {passage['text']}"
                        tags |= {f"{a}-{b}" for a, b in TAG.findall(text)}
                answers: dict[str, list] = {}
                ordered = sorted(tags)
                for start in range(0, len(ordered), 40):
                    batch = ", ".join(ordered[start : start + 40])
                    found = client.post("/api/assistant/tools/find_tags", json={"tags": batch})
                    assert found.status_code == 200, found.text
                    for tag, passages in found.json()["tags"].items():
                        for passage in passages:
                            passage["ref"] = f"doc:{passage['number']}"  # ids differ per run
                        if passages:
                            answers[tag] = passages
        finally:
            runtime.shutdown()
    data = json.dumps(answers, ensure_ascii=False, sort_keys=True, indent=0).encode()
    OUT.write_bytes(gzip.compress(data, mtime=0))
    print(f"{len(answers)} tags, {len(data) // 1024} KB, {OUT.stat().st_size // 1024} KB gzipped")


if __name__ == "__main__":
    write()
