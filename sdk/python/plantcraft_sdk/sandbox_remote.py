"""Code written on the site, run in a separate container with no network and no secret.

The sandbox (``plantcraft_sdk.sandbox``) checks the code and runs it in worker processes, but a
worker in the app's own container still shares its network and its secret files: a way out of
the Python checks reaches both (security test 2026-10-31, D8). Here the workers live in another
container of the same image (``<app>-sandbox`` in compose.yaml: ``network_mode: none``, no
secrets, read-only, no capabilities), which only answers on a Unix socket in a folder the two
share. The app sends ``{"payload": ...}``; the container runs the handler it was started with
(never a function named by the caller) in its ``CodePool`` and answers ``{"value": ...}`` or
``{"error": ...}``.

The app uses it when ``<PREFIX>_SOCKET`` names the socket (``sandbox.pool``):

    python -m plantcraft_sdk.sandbox_remote serve --socket /sandbox/code.sock \\
        --prefix ALARMCRAFT_CODE --handler alarmcraft.engine.python:_evaluate

Each message is a 4-byte big-endian length and JSON (at most ``MAX_MESSAGE`` bytes).
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import socket
import socketserver
import struct
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from plantcraft_sdk.i18n import t
from plantcraft_sdk.sandbox import (
    DEFAULT_MEMORY_MB,
    DEFAULT_TIMEOUT_SECONDS,
    CodeError,
    CodePool,
)

LOGGER = logging.getLogger(__name__)
MAX_MESSAGE = 8 * 1024 * 1024
HEADER = struct.Struct(">I")


def _send(connection: socket.socket, document: Any) -> None:  # noqa: ANN401
    body = json.dumps(document, default=str).encode()
    if len(body) > MAX_MESSAGE:
        body = json.dumps({"error": t("The answer of the code is too large.")}).encode()
    connection.sendall(HEADER.pack(len(body)) + body)


def _receive(connection: socket.socket) -> Any:  # noqa: ANN401
    header = _exactly(connection, HEADER.size)
    (size,) = HEADER.unpack(header)
    if size > MAX_MESSAGE:
        raise CodeError(t("The message to the sandbox is too large."))
    return json.loads(_exactly(connection, size))


def _exactly(connection: socket.socket, size: int) -> bytes:
    chunks, left = [], size
    while left:
        chunk = connection.recv(min(left, 1 << 16))
        if not chunk:
            raise ConnectionError("the sandbox closed the connection")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


class RemotePool:
    """The app's side: ``run`` sends the payload to the sandbox container and waits.

    ``fn`` is ignored: the container runs the handler it was started with."""

    crashes = 0

    def __init__(self, path: str, timeout: float) -> None:
        self.path = path
        # The container stops the code at its own timeout; this one only covers a lost container.
        self.timeout = timeout + 5.0

    def run(self, fn: Callable[[Any], Any], payload: Any) -> Any:  # noqa: ANN401, ARG002
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(self.path)
                _send(connection, {"payload": payload})
                answer = _receive(connection)
        except (OSError, ConnectionError, ValueError) as exc:
            raise CodeError(
                t("The code sandbox did not answer ({why}).", why=type(exc).__name__)
            ) from exc
        if "error" in answer:
            raise CodeError(str(answer["error"]))
        return answer.get("value")

    def shutdown(self) -> None:
        return None


def _handler(spec: str) -> Callable[[Any], Any]:
    module, _, name = spec.partition(":")
    found = getattr(importlib.import_module(module), name)
    if not callable(found):
        raise SystemExit(f"{spec} is not a function")
    return found


def serve(path: str, prefix: str, spec: str) -> None:
    handler = _handler(spec)
    pool = CodePool(
        workers=int(float(os.environ.get(f"{prefix}_WORKERS", "") or 2)),
        timeout=float(os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "") or DEFAULT_TIMEOUT_SECONDS),
        memory_mb=int(float(os.environ.get(f"{prefix}_MEMORY_MB", "") or DEFAULT_MEMORY_MB)),
    )

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            connection = self.request
            connection.settimeout(pool.timeout + 2)
            try:
                payload = _receive(connection)["payload"]
                try:
                    _send(connection, {"value": pool.run(handler, payload)})
                except CodeError as exc:
                    _send(connection, {"error": str(exc)})
                except Exception as exc:  # the person's code failed: say how, keep serving
                    _send(connection, {"error": f"{type(exc).__name__}: {exc}"[:500]})
            except (OSError, ConnectionError, ValueError, KeyError, TypeError) as exc:
                LOGGER.warning("A request to the sandbox failed: %s", exc)

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    if os.path.exists(path):
        os.unlink(path)
    with Server(path, Handler) as server:
        os.chmod(path, 0o660)
        LOGGER.info("Sandbox for %s on %s", spec, path)
        heartbeat = os.path.join(os.path.dirname(path), "sandbox.json")

        def beat() -> None:
            while True:
                try:
                    with open(heartbeat + ".tmp", "w", encoding="utf-8") as handle:
                        json.dump({"at": time.time(), "crashes": pool.crashes}, handle)
                    os.replace(heartbeat + ".tmp", heartbeat)
                except OSError:
                    pass
                time.sleep(10)

        threading.Thread(target=beat, daemon=True).start()
        server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m plantcraft_sdk.sandbox_remote")
    commands = parser.add_subparsers(dest="command", required=True)
    served = commands.add_parser("serve", help="run code for an app on a Unix socket")
    served.add_argument("--socket", required=True)
    served.add_argument("--prefix", required=True)
    served.add_argument("--handler", required=True, metavar="MODULE:FUNCTION")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    serve(args.socket, args.prefix, args.handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
