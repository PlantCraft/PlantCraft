"""The suite's one way out to a language model in the cloud (docs/security-guide.md).

Every container of the suite resolves only the suite's own names, so a model service on the
internet (``api.openai.com``) cannot be reached. ``llm-egress`` is the exception, and the only
one: a small HTTPS proxy that opens a tunnel (``CONNECT host:443``) only to the hosts of the
providers an administrator added in Settings › Language models, and to nothing else.

- PlantCraft writes the hosts to a file (``write_allowlist``) whenever a provider changes; the
  proxy reads it again on each connection. No provider in the cloud: the list is empty and
  every connection is refused. ``PLANTCRAFT_LLM=off``: always empty.
- Only port 443, only names on the list, never an address inside the plant or the host
  (a name that resolves to a private address is refused too).
- PlantCraft sends only its calls to a model through it (``proxy_for``); PI, OPC UA and
  everything else keep their own routes.

Standard library only: the proxy runs in PlantCraft's image with nothing else imported.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import socket
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOGGER = logging.getLogger("plantcraft.egress")

PORT = 3128
# The host each kind of provider calls when no address is given (plantcraft/specialists/model.py).
DEFAULT_HOSTS = {"openai": "api.openai.com", "anthropic": "api.anthropic.com"}
# Names that never leave the plant: a model served on the plant's own network.
LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".intranet", ".corp", ".home.arpa", ".localdomain")
IDLE_SECONDS = 120
MAX_TUNNELS = 32
HEADER_LIMIT = 8192


def allowlist_path() -> Path | None:
    """The file of allowed hosts PlantCraft writes and the proxy reads, if configured."""

    value = os.environ.get("PLANTCRAFT_EGRESS_ALLOWLIST", "").strip()
    return Path(value) if value else None


def proxy_url() -> str:
    """The proxy's address for PlantCraft (``http://llm-egress:3128``), empty without one."""

    return os.environ.get("PLANTCRAFT_LLM_PROXY", "").strip()


def _no_proxy() -> set[str]:
    return {
        item.strip().lower()
        for item in os.environ.get("PLANTCRAFT_LLM_NO_PROXY", "").split(",")
        if item.strip()
    }


def is_public_host(host: str) -> bool:
    """A name or address on the internet, not inside the plant (where a local model may run)."""

    host = (host or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host in _no_proxy():
        return False
    try:
        return ipaddress.ip_address(host.strip("[]")).is_global
    except ValueError:
        pass
    return "." in host and not host.endswith(LOCAL_SUFFIXES)


def provider_host(kind: str, endpoint: str) -> str:
    """The host a provider's calls go to: its address, or the vendor's when none is given."""

    if endpoint:
        return (urlsplit(endpoint).hostname or "").lower()
    return DEFAULT_HOSTS.get(kind, "")


def proxy_for(url: str) -> str:
    """The proxy a call to ``url`` goes through: the suite's when the host is on the internet."""

    parts = urlsplit(url)
    if parts.scheme != "https" or not is_public_host(parts.hostname or ""):
        return ""
    return proxy_url()


def write_allowlist(hosts: list[str], path: Path | None = None) -> bool:
    """Write the allowed hosts (whole or not at all). False when no file is configured."""

    target = path or allowlist_path()
    if target is None:
        return False
    clean = sorted({host.lower() for host in hosts if is_public_host(host)})
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_suffix(".tmp")
    scratch.write_text(json.dumps({"hosts": clean, "at": int(time.time())}), encoding="utf-8")
    os.chmod(scratch, 0o644)
    os.replace(scratch, target)
    return True


def read_allowlist(path: Path | None = None) -> set[str]:
    """The hosts allowed now; empty (refuse everything) when the file is missing or broken."""

    target = path or allowlist_path()
    if target is None:
        return set()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    hosts = data.get("hosts") if isinstance(data, dict) else None
    return {str(host).lower() for host in hosts or [] if isinstance(host, str)}


class Gate:
    """The proxy: ``CONNECT`` tunnels to allowed hosts on 443, and ``GET /status`` for Health."""

    def __init__(self, allowlist: Path | None, *, resolve: Any = None, open_connection: Any = None):
        self.allowlist = allowlist
        self.resolve = resolve or _resolve
        self.open_connection = open_connection or asyncio.open_connection
        self.started = time.time()
        self.tunnels = 0
        self.opened = 0
        self.refused = 0
        self.recent: deque[dict[str, Any]] = deque(maxlen=20)

    def status(self) -> dict[str, Any]:
        return {
            "hosts": sorted(read_allowlist(self.allowlist)),
            "open": self.tunnels,
            "opened": self.opened,
            "refused": self.refused,
            "since": int(self.started),
            "recent": list(self.recent),
        }

    def _note(self, host: str, outcome: str, detail: str = "") -> None:
        entry = {"at": int(time.time()), "host": host, "outcome": outcome, "detail": detail}
        self.recent.appendleft(entry)
        LOGGER.info(json.dumps({"egress": entry}))

    async def check(self, host: str, port: int) -> tuple[str | None, str]:
        """The address to connect to, or None and why not."""

        if port != 443:
            return None, "only port 443"
        if host not in read_allowlist(self.allowlist):
            return None, "not a provider added in Settings › Language models"
        try:
            addresses = await self.resolve(host, port)
        except OSError as exc:
            return None, f"could not resolve: {exc}"
        if not addresses:
            return None, "could not resolve"
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                return None, f"resolves to {address}, inside the plant or the host"
        return addresses[0], ""

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split()
        if len(parts) == 3 and parts[0] == "GET" and parts[1] == "/status":
            body = json.dumps(self.status()).encode()
            await self._reply(writer, 200, "OK", body, "application/json")
            return
        if len(parts) != 3 or parts[0] != "CONNECT" or ":" not in parts[1]:
            await self._reply(writer, 405, "Method Not Allowed", b"CONNECT host:443 only\n")
            return
        host, _, port_text = parts[1].rpartition(":")
        host = host.strip("[]").lower()
        port = int(port_text) if port_text.isdigit() else 0
        if self.tunnels >= MAX_TUNNELS:
            self.refused += 1
            self._note(host, "refused", "too many open connections")
            await self._reply(writer, 503, "Service Unavailable", b"too many connections\n")
            return
        address, why = await self.check(host, port)
        if address is None:
            self.refused += 1
            self._note(host, "refused", why)
            await self._reply(writer, 403, "Forbidden", f"{host}: {why}\n".encode())
            return
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                self.open_connection(address, port), timeout=15
            )
        except (OSError, asyncio.TimeoutError) as exc:
            self.refused += 1
            self._note(host, "failed", str(exc) or "timeout")
            await self._reply(writer, 502, "Bad Gateway", f"{host}: {exc or 'timeout'}\n".encode())
            return
        self.opened += 1
        self.tunnels += 1
        self._note(host, "opened", address)
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        try:
            await writer.drain()
            await asyncio.gather(
                _pipe(reader, upstream_writer),
                _pipe(upstream_reader, writer),
                return_exceptions=True,
            )
        finally:
            self.tunnels -= 1
            for stream in (writer, upstream_writer):
                stream.close()

    @staticmethod
    async def _reply(
        writer: asyncio.StreamWriter, code: int, reason: str, body: bytes, kind: str = "text/plain"
    ) -> None:
        head = (
            f"HTTP/1.1 {code} {reason}\r\nContent-Type: {kind}\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        )
        try:
            writer.write(head.encode() + body)
            await writer.drain()
        except OSError:
            pass
        writer.close()


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), timeout=IDLE_SECONDS)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    finally:
        try:
            writer.write_eof()
        except (OSError, RuntimeError):
            pass


async def serve(host: str = "0.0.0.0", port: int = PORT) -> None:  # noqa: S104 - its own network only
    gate = Gate(allowlist_path())
    server = await asyncio.start_server(gate.handle, host, port, limit=HEADER_LIMIT)
    LOGGER.info("llm-egress listening on %s:%s, hosts from %s", host, port, gate.allowlist)
    async with server:
        await server.serve_forever()


def status(url: str | None = None, timeout: float = 3) -> dict[str, Any] | None:
    """The proxy's ``/status`` (Health), or None when it does not answer."""

    target = urlsplit(url or proxy_url() or f"http://127.0.0.1:{PORT}")
    try:
        with socket.create_connection(
            (target.hostname, target.port or PORT), timeout=timeout
        ) as sock:
            sock.sendall(b"GET /status HTTP/1.1\r\nHost: llm-egress\r\n\r\n")
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
    except OSError:
        return None
    head, _, body = data.partition(b"\r\n\r\n")
    if not head.startswith(b"HTTP/1.1 200"):
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None
