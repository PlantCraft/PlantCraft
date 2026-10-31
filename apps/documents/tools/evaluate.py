#!/usr/bin/env python3
"""Draw the demo plant's P&IDs, read them back and score the reader.

``python tools/evaluate.py [--out DIR] [--formats svg,pdf,png] [--sheet PID-U-100-01]``
writes the drawings, what was read and ``scores.json`` to DIR, and prints the totals.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from doccraft.plantmap.reader import read_drawing  # noqa: E402
from doccraft.plantmap.reader.score import KINDS, score, total  # noqa: E402
from doccraft.plantmap.sample.draw import draw_all  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/doccraft-eval")
    parser.add_argument("--formats", default="svg,pdf")
    parser.add_argument("--sheet", default="")
    parser.add_argument("--noise", type=float, default=0.0, help="raster: noise and tilt level")
    parser.add_argument("--jitter", type=float, default=0.0, help="line ends off by up to N pt")
    parser.add_argument("--split", action="store_true", help="lines drawn in pieces")
    parser.add_argument("--no-arrows", action="store_true")
    parser.add_argument("--no-valve-tags", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    formats = args.formats.split(",")
    scores: dict[str, list] = {f: [] for f in formats}
    seconds: dict[str, float] = {f: 0.0 for f in formats}
    untidy = {
        "jitter": args.jitter,
        "split": args.split,
        "arrows": not args.no_arrows,
        "valve_tags": not args.no_valve_tags,
    }
    for sheet, canvas, key in draw_all(**untidy):
        if args.sheet and sheet != args.sheet:
            continue
        (out / f"{sheet}.key.json").write_text(json.dumps(key, indent=1))
        files = {}
        if "svg" in formats:
            files["svg"] = out / f"{sheet}.svg"
            files["svg"].write_text(canvas.svg())
        if "pdf" in formats or "png" in formats:
            pdf = out / f"{sheet}.pdf"
            canvas.pdf(pdf)
            files["pdf"] = pdf
        if "png" in formats:
            from doccraft.plantmap.sample.raster import scan

            files["png"] = out / f"{sheet}.png"
            scan(files["pdf"], files["png"], noise=args.noise, seed=len(sheet))
        for fmt in formats:
            started = time.perf_counter()
            pages = read_drawing(files[fmt].read_bytes(), files[fmt].name)
            seconds[fmt] += time.perf_counter() - started
            result = pages[0]
            (out / f"{sheet}.{fmt}.read.json").write_text(json.dumps(result, indent=1))
            s = score(result, key)
            scores[fmt].append(s)
            print(
                f"{fmt} {sheet}: tags R {s['tags']['recall']} P {s['tags']['precision']}  "
                f"relations R {s['relations']['recall']} P {s['relations']['precision']}"
            )
    summary = {}
    for fmt in formats:
        summary[fmt] = {
            f: total(scores[fmt], f) for f in ("tags", "equipment", "relations", *KINDS)
        }
        summary[fmt]["seconds_per_sheet"] = round(seconds[fmt] / max(len(scores[fmt]), 1), 3)
        summary[fmt]["sheets"] = len(scores[fmt])
    (out / "scores.json").write_text(json.dumps({"summary": summary, "sheets": scores}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
