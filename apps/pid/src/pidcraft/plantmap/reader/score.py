"""Precision and recall of a read drawing against its answer key (``sample/draw.py``)."""

from __future__ import annotations

from typing import Any

KINDS = ("feeds", "measures", "controls", "signal", "on")


def score(result: dict[str, Any], key: dict[str, Any]) -> dict[str, Any]:
    found_tags = {i["tag"] for i in result["items"] if i.get("tag")}
    true_tags = {e["tag"] for e in key["equipment"]} | {i["tag"] for i in key["instruments"]}
    found_eq = {i["tag"] for i in result["items"] if i["family"] == "equipment"}
    true_eq = {e["tag"] for e in key["equipment"]}
    rels = {(r["from"], r["type"], r["to"]) for r in result["relations"]}
    truth = (
        {(a, "feeds", b) for a, b in key["feeds"]}
        | {(a, "measures", b) for a, b in key["measures"]}
        | {(a, "controls", b) for a, b in key["controls"]}
        | {(a, "signal", b) for a, b in key["signals"]}
        | {(a, "on", b) for a, b in key["valve_on"]}
    )
    out = {
        "sheet": key["sheet"],
        "sheet_read": result.get("sheet") == key["sheet"],
        "tags": _pr(found_tags, true_tags),
        "equipment": _pr(found_eq, true_eq),
        "relations": _pr(rels, truth),
    }
    for kind in KINDS:
        out[kind] = _pr({r for r in rels if r[1] == kind}, {r for r in truth if r[1] == kind})
    out["line_numbers_taken_as_tags"] = sum(
        1 for n in key.get("line_numbers", []) if n in found_tags
    )
    out["missed"] = sorted(map(str, true_tags - found_tags))[:20]
    out["extra"] = sorted(map(str, found_tags - true_tags))[:20]
    out["missed_relations"] = sorted(" ".join(r) for r in truth - rels)[:30]
    out["extra_relations"] = sorted(" ".join(r) for r in rels - truth)[:30]
    return out


def _pr(found: set, true: set) -> dict[str, Any]:
    tp = len(found & true)
    return {
        "tp": tp,
        "found": len(found),
        "true": len(true),
        "precision": round(tp / len(found), 3) if found else (1.0 if not true else 0.0),
        "recall": round(tp / len(true), 3) if true else 1.0,
    }


def total(scores: list[dict[str, Any]], field: str) -> dict[str, Any]:
    tp = sum(s[field]["tp"] for s in scores)
    found = sum(s[field]["found"] for s in scores)
    true = sum(s[field]["true"] for s in scores)
    return {
        "tp": tp,
        "found": found,
        "true": true,
        "precision": round(tp / found, 3) if found else 1.0,
        "recall": round(tp / true, 3) if true else 1.0,
    }
