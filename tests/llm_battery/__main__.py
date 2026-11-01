"""Run the assistant's test battery and write its report.

    python -m tests.llm_battery                                  # the obedient fake model
    python -m tests.llm_battery --model gpt-5-mini \\
        --key-file ~/.config/plantcraft-tests/openai.env --reasoning low

The key file holds ``OPENAI_API_KEY=...`` (or the key alone). The key is never printed, and any
secret the battery planted (the key included) is blanked in the report before it is written.
The report goes to ``--out`` (default ``var/llm-battery/<model>-<time>/``): ``report.md`` and
``results.json``.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

from tests.llm_battery.cases import GROUPS
from tests.llm_battery.fake import MeteredModel, ObedientModel
from tests.llm_battery.harness import installation
from tests.llm_battery.runner import run_cases, run_load, run_quality, write_report


def read_key(path: str) -> str:
    text = Path(os.path.expanduser(path)).read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" in line:
            name, _, value = line.partition("=")
            if name.strip() in ("OPENAI_API_KEY", "PLANTCRAFT_TEST_OPENAI_KEY"):
                return value.strip().strip("'\"")
        elif line.startswith("sk-"):
            return line
    raise SystemExit(f"No OPENAI_API_KEY in {path}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.llm_battery", description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--model", default="fake", help="'fake' (obedient) or the OpenAI model's name"
    )
    parser.add_argument("--key-file", default="~/.config/plantcraft-tests/openai.env")
    parser.add_argument(
        "--endpoint", default="", help="the provider's base address (default OpenAI's)"
    )
    parser.add_argument(
        "--reasoning", default="low", choices=["", "none", "minimal", "low", "medium", "high"]
    )
    parser.add_argument("--groups", default="", help=f"comma-separated, of: {', '.join(GROUPS)}")
    parser.add_argument("--load-people", type=int, default=10)
    parser.add_argument("--load-questions", type=int, default=3)
    parser.add_argument(
        "--fake-latency",
        type=float,
        default=2.0,
        help="seconds per fake model call, in the load group",
    )
    parser.add_argument(
        "--price",
        default="",
        help="US$ per million tokens: input,cached,output (from the provider's page that day)",
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    groups = {item.strip() for item in args.groups.split(",") if item.strip()}
    unknown = groups - set(GROUPS)
    if unknown:
        parser.error(f"unknown groups: {', '.join(sorted(unknown))}")
    fake = args.model == "fake"
    if fake:
        factory, key, name, endpoint = ObedientModel, "", "obedient", None
    else:
        MeteredModel.reasoning_override = args.reasoning
        factory, key, name = MeteredModel, read_key(args.key_file), args.model
        endpoint = args.endpoint
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out = Path(args.out or f"var/llm-battery/{name}-{stamp}")
    prices = None
    if args.price:
        values = [float(item) for item in args.price.split(",")]
        prices = dict(zip(("input", "cached", "output"), values, strict=True))

    workdir = Path(tempfile.mkdtemp(prefix="llm-battery-"))
    options = {"model_name": name}
    if key:
        options["key"] = key
    if endpoint is not None:
        options["endpoint"] = endpoint
    print(f"battery: model {name}, installation in {workdir}", flush=True)
    with installation(workdir, factory, **options) as battery:
        secrets = dict(battery.canaries)

        def log(line: str) -> None:
            for secret in secrets.values():
                if secret:
                    line = line.replace(secret, "[secret]")
            print(line, flush=True)

        results = run_cases(battery, groups or None, log)
        if not groups or "quality" in groups:
            results += run_quality(battery, log)
        if not groups or "works" in groups:
            results += run_quality(battery, log, suite="works")
        load = None
        if not groups or "load" in groups:
            before = ObedientModel.latency
            ObedientModel.latency = args.fake_latency if fake else before
            try:
                found, load = run_load(battery, args.load_people, args.load_questions, log)
            finally:
                ObedientModel.latency = before
            results += found
        report = write_report(
            out,
            f"{name} (reasoning {args.reasoning or 'default'})"
            if not fake
            else "obedient fake model",
            results,
            load,
            prices,
            started_at=stamp,
            secrets=secrets,
        )
    print(f"battery: report in {report}", flush=True)
    failed = [r for r in results if r.passed is False and r.expected == "hold"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
