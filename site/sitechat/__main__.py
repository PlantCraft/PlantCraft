"""python -m sitechat serve | contacts | eval (see README.md)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .app import Settings, create_app
from .evaluation import dump, load, report, run
from .llm import ModelError


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m sitechat")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="serve the built site and its chat")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    sub.add_parser("contacts", help="print the contact requests, newest last")
    watch = sub.add_parser("watch", help="sample the host's health for /stats and send alerts")
    watch.add_argument("--interval", type=float, default=30.0)
    ev = sub.add_parser("eval", help="ask the configured model every question of the eval set")
    ev.add_argument("--only", default="", help="question ids or kinds, comma separated")
    ev.add_argument("--judge", action="store_true", help="also have the model judge each answer")
    ev.add_argument("--out", type=Path, default=Path("eval-report"))
    args = parser.parse_args()
    settings = Settings.from_env()

    if args.command == "serve":
        import uvicorn

        if settings.dist is None:
            sys.exit("No built site: run `python build.py` first (or set SITE_DIST).")
        uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=False)
    elif args.command == "watch":
        from .health import run as watch_run

        watch_run(settings.data_dir, args.interval)
    elif args.command == "contacts":
        from .contacts import Inbox

        for contact in Inbox(settings.data_dir).contacts():
            print(json.dumps(contact, ensure_ascii=False))
    elif args.command == "eval":
        if settings.model is None or settings.knowledge is None:
            sys.exit("Set SITE_CHAT_PROVIDER and SITE_CHAT_API_KEY, and build the site first.")
        # One call first: a wrong key or model fails here, not as 59 fallback answers.
        try:
            settings.model.complete("Reply with OK.", [{"role": "user", "content": "OK?"}], 1000)
        except ModelError as exc:
            sys.exit(f"The model did not answer: {exc}. Check the key, the model and the provider.")
        questions = load()
        if args.only:
            wanted = set(args.only.split(","))
            questions = [q for q in questions if q["id"] in wanted or q["kind"] in wanted]
        try:
            results = run(
                settings.model,
                settings.knowledge,
                questions,
                settings.docs_url,
                settings.model if args.judge else None,
            )
        except ModelError as exc:
            sys.exit(f"Stopped: {exc}. No report written.")
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(report(results, questions, settings.model.name))
        dump(results, args.out / "results.json")
        passed = sum(r.ok for r in results)
        print(f"{passed}/{len(results)} passed; report in {args.out / 'report.md'}")


if __name__ == "__main__":
    main()
