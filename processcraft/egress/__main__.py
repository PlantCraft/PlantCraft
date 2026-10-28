"""``python -m processcraft.egress serve`` runs the proxy; ``health`` is its healthcheck."""

from __future__ import annotations

import asyncio
import logging
import sys

from processcraft.egress import PORT, serve, status


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "serve"
    if command == "health":
        return 0 if status(f"http://127.0.0.1:{PORT}") is not None else 1
    if command == "serve":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        asyncio.run(serve())
        return 0
    print("usage: python -m processcraft.egress [serve|health]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
