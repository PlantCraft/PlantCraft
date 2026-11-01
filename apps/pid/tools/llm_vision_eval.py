#!/usr/bin/env python3
"""Test an LLM with vision on the demo P&IDs and score it like the classical reader.

Run on the Mac mini, never in the cloud, and never print the key::

    set -a; . ~/.config/plantcraft-tests/openai.env; set +a
    python tools/llm_vision_eval.py --sheets 3 --model gpt-5-mini --out /tmp/llm-eval

Modes (``--mode``):

- ``vision``: the page image only; the model returns items and relations.
- ``hybrid``: the page image plus what the classical reader found; the model corrects it.
  This is the likely product path for scans.

Real public P&IDs (``--dexpi DIR --xml DIR``): every PDF or PNG in the first folder whose
DEXPI XML is in the second (same name, or the longest name the drawing starts with) is sent as
an image and scored on tags and equipment-to-equipment feeds, next to the classical reader's
score on the same file. ``--noise`` makes the demo scans dirty (speckle, skew).

Each sheet is one call. Default is 3 sheets, which is a few cents on a cheap model. The
script prints tokens per call, writes the answers and ``scores.json`` to ``--out``, and
stops at ``--max-calls``. It uses only the standard library to call the API.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pidcraft.plantmap.reader import read_drawing  # noqa: E402
from pidcraft.plantmap.reader.score import KINDS, score, total  # noqa: E402
from pidcraft.plantmap.sample.draw import draw_all  # noqa: E402

PROMPT = """You read a P&ID (piping and instrumentation diagram, ISA-5.1 symbols).
Return JSON only, with this shape:
{"sheet": "<drawing number>", "unit": "<unit>", "title": "<title>",
 "items": [{"tag": "P-1001", "family": "equipment|instrument", "cls": "pump|vessel|column|
 heat_exchanger|reactor|tank|furnace|compressor|controller|transmitter|valve|indicator|other"}],
 "relations": [{"from": "TAG", "type": "feeds|measures|controls|signal|on", "to": "TAG"}]}
Rules: feeds = process line from equipment to equipment (through valves, following arrows, or
to the equipment named by an off-page connector). measures = instrument to the equipment it
measures. controls = controller to its valve. signal = transmitter to its controller (dashed
line). on = valve to the equipment upstream on its line. A valve without a tag takes the
controller's number with V (FIC-1003 gives FV-1003). Line numbers like 8"-P-1001-A1A and sheet
numbers are not tags. Do not invent anything not drawn."""


def ask(model: str, image: bytes, extra: str, key: str) -> tuple[dict, dict]:
    content = [
        {"type": "input_text", "text": PROMPT + extra},
        {
            "type": "input_image",
            "image_url": "data:image/png;base64," + base64.b64encode(image).decode(),
        },
    ]
    body = {
        "model": model,
        "input": [{"role": "user", "content": content}],
        "text": {"format": {"type": "json_object"}},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 - fixed URL
        answer = json.loads(response.read())
    text = "".join(
        part.get("text", "")
        for out in answer.get("output", [])
        for part in out.get("content", []) or []
    )
    return json.loads(text or "{}"), answer.get("usage", {})


def as_result(answer: dict) -> dict:
    items = [i for i in answer.get("items", []) if isinstance(i, dict) and i.get("tag")]
    rels = [
        r
        for r in answer.get("relations", [])
        if isinstance(r, dict) and r.get("from") and r.get("to") and r.get("type") in KINDS
    ]
    return {"sheet": answer.get("sheet"), "items": items, "relations": rels}


def classical_found(page: dict) -> str:
    found = {
        "items": [{"tag": i["tag"], "cls": i["cls"]} for i in page["items"] if i.get("tag")],
        "relations": [{k: r[k] for k in ("from", "type", "to")} for r in page["relations"]],
    }
    return (
        "\nA classical reader found this; it may miss or misread tags and lines. "
        "Correct and complete it:\n" + json.dumps(found)
    )


def _pr(found: set, true: set) -> dict:
    hit = len(found & true)
    return {
        "precision": round(hit / len(found), 3) if found else 0.0,
        "recall": round(hit / len(true), 3) if true else 0.0,
        "found": len(found),
        "true": len(true),
    }


def dexpi_score(page: dict, key: dict) -> dict:
    tags = {i["tag"] for i in page["items"] if i.get("tag")}
    feeds = {(r["from"], r["to"]) for r in page["relations"] if r["type"] == "feeds"}
    return {
        "tags": _pr(tags, set(key["tags"])),
        "feeds": _pr(feeds, {tuple(f) for f in key["feeds"]}),
    }


def run_dexpi(args, key: str) -> None:
    from dexpi_truth import norm, truth

    xmls = {p.stem.upper(): p for p in Path(args.xml).iterdir() if p.suffix.lower() == ".xml"}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, calls, tokens = [], 0, 0
    for drawing in sorted(Path(args.dexpi).iterdir()):
        if drawing.suffix.lower() not in {".pdf", ".png"} or calls >= args.max_calls:
            continue
        stem = drawing.stem.upper()
        match = max((s for s in xmls if stem.startswith(s)), key=len, default=None)
        if match is None:
            continue
        answer_key = truth(xmls[match])
        if not answer_key["feeds"]:
            continue
        data = drawing.read_bytes()
        if drawing.suffix.lower() == ".pdf":
            import pypdfium2

            image = pypdfium2.PdfDocument(data)[0].render(scale=args.dpi / 72).to_pil()
            png = out / f"{drawing.stem}.png"
            image.save(png)
            data_png = png.read_bytes()
        else:
            data_png = data
        classical = read_drawing(data, drawing.name)
        page = classical[0] if classical else {"items": [], "relations": []}
        extra = classical_found(page) if args.mode == "hybrid" else ""
        started = time.perf_counter()
        answer, usage = ask(args.model, data_png, extra, key)
        calls += 1
        tokens += int(usage.get("total_tokens", 0))
        llm = as_result(answer)
        for item in llm["items"]:
            item["tag"] = norm(str(item["tag"]).upper().replace(" ", ""))
        for rel in llm["relations"]:
            rel["from"] = norm(str(rel["from"]).upper().replace(" ", ""))
            rel["to"] = norm(str(rel["to"]).upper().replace(" ", ""))
        (out / f"{drawing.stem}.{args.mode}.json").write_text(json.dumps(answer, indent=1))
        row = {
            "file": drawing.name,
            "classical": dexpi_score(page, answer_key),
            "llm": dexpi_score(llm, answer_key),
            "seconds": round(time.perf_counter() - started, 1),
            "tokens": usage.get("total_tokens"),
        }
        rows.append(row)
        print(
            f"{drawing.name}: feeds classical {row['classical']['feeds']}  "
            f"llm {row['llm']['feeds']}  {row['seconds']} s, {row['tokens']} tokens"
        )
    summary = {"model": args.model, "mode": args.mode, "calls": calls, "total_tokens": tokens}
    for who in ("classical", "llm"):
        for what in ("tags", "feeds"):
            hit = sum(round(r[who][what]["recall"] * r[who][what]["true"]) for r in rows)
            found = sum(r[who][what]["found"] for r in rows)
            true = sum(r[who][what]["true"] for r in rows)
            summary[f"{who}_{what}"] = {
                "precision": round(hit / found, 3) if found else 0.0,
                "recall": round(hit / true, 3) if true else 0.0,
            }
    (out / "dexpi-scores.json").write_text(
        json.dumps({"summary": summary, "files": rows}, indent=1)
    )
    print(json.dumps(summary))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/llm-eval")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--mode", choices=["vision", "hybrid"], default="vision")
    parser.add_argument("--sheets", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=6)
    parser.add_argument("--noise", type=float, default=0.0)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--dexpi", help="folder of public P&IDs (PDF, PNG)")
    parser.add_argument("--xml", help="folder of their DEXPI XML files")
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("OPENAI_API_KEY is not set: load ~/.config/plantcraft-tests/openai.env first.")
    if args.dexpi:
        run_dexpi(args, key)
        return
    from pidcraft.plantmap.sample.raster import scan

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scores, calls, tokens = [], 0, 0
    for sheet, canvas, truth in draw_all():
        if calls >= min(args.sheets, args.max_calls):
            break
        pdf, png = out / f"{sheet}.pdf", out / f"{sheet}.png"
        canvas.pdf(pdf)
        scan(pdf, png, dpi=args.dpi, noise=args.noise, seed=len(sheet))
        extra = ""
        if args.mode == "hybrid":
            extra = classical_found(read_drawing(png.read_bytes(), png.name)[0])
        started = time.perf_counter()
        answer, usage = ask(args.model, png.read_bytes(), extra, key)
        calls += 1
        tokens += int(usage.get("total_tokens", 0))
        result = as_result(answer)
        (out / f"{sheet}.{args.mode}.json").write_text(json.dumps(answer, indent=1))
        s = score(result, truth)
        s["seconds"] = round(time.perf_counter() - started, 1)
        s["usage"] = usage
        scores.append(s)
        print(
            f"{sheet}: tags R {s['tags']['recall']} P {s['tags']['precision']}  "
            f"relations R {s['relations']['recall']} P {s['relations']['precision']}  "
            f"{s['seconds']} s, {usage.get('total_tokens')} tokens"
        )
    summary = {f: total(scores, f) for f in ("tags", "equipment", "relations", *KINDS)}
    summary.update(model=args.model, mode=args.mode, calls=calls, total_tokens=tokens)
    (out / "scores.json").write_text(json.dumps({"summary": summary, "sheets": scores}, indent=1))
    print(json.dumps({k: summary[k] for k in ("tags", "relations", "calls", "total_tokens")}))


if __name__ == "__main__":
    main()
