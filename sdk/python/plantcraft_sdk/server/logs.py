"""The suite's logs: one JSON line per record, to the console and to rotating files.

Every server of the suite (PlantCraft and each app) starts with::

    from plantcraft_sdk.server.logs import configure_logging

    configure_logging("twincraft", version=__version__, data_dir=settings.data_dir)

and runs uvicorn with ``log_config=None, access_log=False`` (``mount`` logs each request
itself, with its id). A record is one JSON object per line::

    {"time": "2026-10-21T12:00:00.123+00:00", "level": "ERROR", "app": "twincraft",
     "version": "0.4.1", "logger": "twincraft.monitor", "message": "...",
     "request_id": "3f2a...", "error": "Traceback ..."}

It goes to standard error (Docker keeps it, rotated) and, with ``data_dir``, to
``<data_dir>/logs/<app>.jsonl``, rotated at ``max_bytes`` with ``backups`` old files, so the
logs of a container that was replaced (an update, a rollback) are still on disk. Secrets never
reach either: passwords, tokens, keys and ``Authorization`` values are replaced by ``***``
before a record is written. ``counts()`` holds how many warnings and errors were logged since
start, for ``GET /api/ops/metrics`` (``docs/operations.md``).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import threading
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 4
MAX_MESSAGE = 8000
LOG_FOLDER = "logs"
REDACTED = "***"
# The request a record belongs to (set by ``mount`` from X-Request-ID, else a new id).
REQUEST_ID: ContextVar[str] = ContextVar("processcraft_request_id", default="")
# "password=...", "token: ...", "api_key '...'", JSON "secret": "...": the value goes.
# The name starts where a word starts (the look-behind): without it every position inside a long
# run of letters was a new start and a log line of 8,000 letters took 2.6 s to redact.
_NAMED_SECRET = re.compile(
    r"""(?P<name>["']?(?<![A-Za-z0-9_-])[A-Za-z0-9_-]*(?:password|passwd|secret|token|api[_-]?key|app[_-]?key|"""
    r"""private[_-]?key|authorization|cookie)[A-Za-z0-9_-]*["']?\s*[:=]\s*)"""
    r"""(?P<value>"[^"]*"|'[^']*'|[^\s,;&}\]]+)""",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
# A JWT anywhere (three base64url parts, the first a JSON header).
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)
_STANDARD = frozenset(vars(logging.makeLogRecord({})))

_counts_lock = threading.Lock()
_counts = {"warning": 0, "error": 0}
_configured: dict[str, Any] = {}


def redact(text: str) -> str:
    """``text`` with every secret it carries replaced by ``***``."""

    text = _PEM.sub(REDACTED, text)
    text = _BEARER.sub(lambda match: f"{match.group(1)} {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)

    def named(match: re.Match[str]) -> str:
        value = match.group("value")
        quote = value[0] if value[:1] in {'"', "'"} else ""
        return f"{match.group('name')}{quote}{REDACTED}{quote}"

    return _NAMED_SECRET.sub(named, text)


def counts() -> dict[str, int]:
    """Warnings and errors (ERROR and CRITICAL) logged since this process started."""

    with _counts_lock:
        return dict(_counts)


class _Counter(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        key = "error" if record.levelno >= logging.ERROR else "warning"
        with _counts_lock:
            _counts[key] += 1


class JsonFormatter(logging.Formatter):
    """One JSON object per record, secrets redacted."""

    def __init__(self, app: str, version: str):
        super().__init__()
        self.app = app
        self.version = version

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:  # a bad format string must not lose the record
            message = f"{record.msg!r} {record.args!r}"
        item: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "app": self.app,
            "version": self.version,
            "logger": record.name,
            "message": redact(message[:MAX_MESSAGE]),
        }
        request_id = REQUEST_ID.get()
        if request_id:
            item["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_") and key not in item:
                item[key] = value if isinstance(value, int | float | bool) else redact(str(value))
        if record.exc_info:
            item["error"] = redact("".join(traceback.format_exception(*record.exc_info)))
        return json.dumps(item, ensure_ascii=False, default=str)


def log_file(app: str, data_dir: str | Path) -> Path:
    """Where an app's log file lives: ``<data_dir>/logs/<app>.jsonl``."""

    return Path(data_dir) / LOG_FOLDER / f"{app}.jsonl"


def configure_logging(
    app: str,
    *,
    version: str,
    data_dir: str | Path | None = None,
    level: str | None = None,
    max_bytes: int | None = None,
    backups: int | None = None,
) -> Path | None:
    """Send every record of this process as JSON to standard error and, with ``data_dir``, to
    the rotating file; returns the file's path (None without a file or when it cannot be
    written: the console still works). ``level`` defaults to ``<APP>_LOG_LEVEL`` or INFO."""

    level_name = (level or os.environ.get(f"{app.upper()}_LOG_LEVEL") or "INFO").strip().upper()
    formatter = JsonFormatter(app, version)
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_processcraft", False):
            root.removeHandler(handler)
            handler.close()
    handlers: list[logging.Handler] = [logging.StreamHandler(), _Counter()]
    path: Path | None = None
    if data_dir is not None:
        path = log_file(app, data_dir)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(
                logging.handlers.RotatingFileHandler(
                    path,
                    maxBytes=max_bytes or MAX_BYTES,
                    backupCount=BACKUPS if backups is None else backups,
                    encoding="utf-8",
                )
            )
        except OSError as exc:
            path = None
            logging.getLogger(__name__).warning("Log file not written: %s", exc)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler._processcraft = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(getattr(logging, level_name, logging.INFO))
    # uvicorn's own loggers go through the root handlers (run it with log_config=None).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    _configured.update(app=app, version=version, file=path)
    return path


__all__ = [
    "BACKUPS",
    "JsonFormatter",
    "MAX_BYTES",
    "REQUEST_ID",
    "configure_logging",
    "counts",
    "log_file",
    "redact",
]
