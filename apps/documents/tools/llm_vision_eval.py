#!/usr/bin/env python3
"""Test an LLM with vision on the demo P&IDs and score it like the classical reader.

Run on the Mac mini, never in the cloud, and never print the key::

    set -a; . ~/.config/plantcraft-tests/openai.env; set +a
    python tools/llm_vision_eval.py --sheets 3 --model gpt-5-mini --out /tmp/llm-eval

Modes (``--mode``):

- ``vision``: the page image only; the model returns items and relations.
- ``hybrid``: the page image plus what the classical reader found; the model corrects it.
  This is the likely product path for scans.

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

from doccraft.plantmap.reader import read_drawing  # noqa: E402
from doccraft.plantmap.reader.score import KINDS, score, total  # noqa: E402
from doccraft.plantmap.sample.draw import draw_all  # noqa: E402

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/llm-eval")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--mode", choices=["vision", "hybrid"], default="vision")
    parser.add_argument("--sheets", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=6)
    parser.add_argument("--noise", type=float, default=0.0)
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("OPENAI_API_KEY is not set: load ~/.config/plantcraft-tests/openai.env first.")
    from doccraft.plantmap.sample.raster import scan

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
            classical = read_drawing(png.read_bytes(), png.name)[0]
            found = {
                "items": [
                    {"tag": i["tag"], "cls": i["cls"]} for i in classical["items"] if i.get("tag")
                ],
                "relations": [
                    {k: r[k] for k in ("from", "type", "to")} for r in classical["relations"]
                ],
            }
            extra = (
                "\nA classical reader (OCR) found this; it may miss or misread tags "
                "(PY for PV, 0 for O). Correct and complete it:\n" + json.dumps(found)
            )
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
