"""Documents: the Simulator plant's library, each document linked to its assets."""

from __future__ import annotations

import json
import urllib.parse

from .base import Http, Suite, log

# Documents ------------------------------------------------------------------------------------

# Where each kind of the demo documents goes: who reads them is the same for all (everyone).
DOC_FOLDERS = {
    "Operating manuals and procedures": ("Operating manual", "Procedure"),
    "Process control": ("Control narrative", "Troubleshooting guide", "P&ID", "Datasheet"),
    "Maintenance and incidents": ("Maintenance record", "Incident report"),
}


def doccraft(docs: Http, suite: Suite) -> None:
    """The Simulator plant's documents (deploy/demo/documents): manuals, control narratives,
    troubleshooting guide, maintenance history, incidents, each linked to its assets. A document
    whose number is already in the library is left as it is."""

    folder = suite.demo_map.parent / "documents"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    folders = {item["name"]: item["folder_id"] for item in docs.get("/api/folders") or []}
    for name in DOC_FOLDERS:
        if name not in folders:
            folders[name] = docs.post("/api/folders", {"name": name})["folder_id"]
    present = {item["number"] for item in docs.get("/api/documents") or []}
    sent = 0
    for item in manifest["documents"]:
        if item["number"] in present:
            continue
        place = next((name for name, kinds in DOC_FOLDERS.items() if item["kind"] in kinds), "")
        fields = {
            "filename": item["file"],
            "folder": folders.get(place, ""),
            "number": item["number"],
            "title": item["title"],
            "kind": item["kind"],
            "unit": item.get("unit", ""),
            "language": item.get("language", ""),
            "revision": item.get("revision", ""),
            "issued": item.get("date", ""),
        }
        query = urllib.parse.urlencode({key: value for key, value in fields.items() if value})
        raw = (folder / item["file"]).read_bytes()
        doc = docs.post(f"/api/documents?{query}", raw=raw, content_type="application/octet-stream")
        if item.get("assets"):
            docs.put(f"/api/documents/{doc['doc_id']}/assets", {"assets": item["assets"]})
        sent += 1
    log(f"documents: {sent} sent, {len(present)} already there; reading them takes a minute")
