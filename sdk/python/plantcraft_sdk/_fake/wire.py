"""What the fake PlantCraft receives and answers: the request, the response and the refusal."""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


class _Abort(Exception):
    def __init__(self, status: int, detail: Any, headers: dict[str, str] | None = None):
        super().__init__(str(detail))
        self.status = status
        self.detail = detail
        self.headers = headers or {}


@dataclass
class FakeResponse:
    """What ``FakePlantCraft.handle`` answers: a status, a JSON body, headers, cookies."""

    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)
    # (name, value, max_age) set on the caller, as PlantCraft's Set-Cookie does.
    cookies: list[tuple[str, str, int]] = field(default_factory=list)

    def content(self) -> bytes:
        return json.dumps(self.body, separators=(",", ":"), allow_nan=False).encode()

    def set_cookie_headers(self) -> list[str]:
        return [
            f"{name}={value}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=lax"
            for name, value, max_age in self.cookies
        ]


# Derived kinds kept as written and read back as recorded values (no grid; only agg=last).
_TYPED_KINDS = ("integer", "boolean", "instant", "structured")


def _multi(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Query pairs by name, repeated names kept in order."""

    found: dict[str, list[str]] = {}
    for key, value in pairs:
        found.setdefault(key, []).append(value)
    return found


@dataclass
class _Request:
    method: str
    path: str
    # Each parameter's last value; ``lists`` keeps every value of a repeated one.
    query: dict[str, str]
    headers: dict[str, str]
    cookies: dict[str, str]
    body: bytes
    lists: dict[str, list[str]] = field(default_factory=dict)

    def json(self) -> Any:
        try:
            return json.loads(self.body or b"null")
        except ValueError as exc:
            raise _Abort(422, "The body is not JSON.") from exc
