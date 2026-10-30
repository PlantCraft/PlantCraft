import os

# Tests never fill the history cache in the background, whatever the shell exports.
os.environ.setdefault("PLANTCRAFT_PREWARM_HISTORY", "false")
os.environ.setdefault("PLANTCRAFT_WATCH", "false")
os.environ.setdefault("PLANTCRAFT_MAIL_OUTBOX", "false")

# Passwords hash with the cheapest Argon2id in tests: the product's (64 MiB, 3 passes, about a
# tenth of a second) ran several times per test and was minutes of every run. The hashes are
# still Argon2id, so what the tests check about them holds; the product's own parameters are
# held by test_security.py.
# CI's isolation job runs its tests against the built image, with no platform installed.
try:
    from argon2 import PasswordHasher

    import plantcraft.auth.users as _users
except ImportError:
    _users = None

if _users is not None and not hasattr(_users, "PRODUCT_HASHER"):  # may load twice (tests.conftest)
    _users.PRODUCT_HASHER = _users._HASHER
    _users._HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


# Tests never reach a machine outside this one (docs/testing.md). A source or server address
# that is not loopback (the plant map's template points at 10.0.0.15) is refused at once, as an
# unreachable server would be after its timeout, instead of waiting that timeout out.
import asyncio.base_events  # noqa: E402
import ipaddress  # noqa: E402
import socket  # noqa: E402


def _outside(host) -> bool:
    if host is None:
        return False
    name = host.decode() if isinstance(host, bytes) else str(host)
    if name in ("", "localhost") or name.endswith(".localhost"):
        return False
    try:
        return not ipaddress.ip_address(name.strip("[]")).is_loopback
    except ValueError:
        return True  # a host name: tests resolve only localhost


def _refuse(host, port) -> ConnectionRefusedError:
    if os.environ.get("PLANTCRAFT_TEST_NET_LOG"):
        with open(os.environ["PLANTCRAFT_TEST_NET_LOG"], "a") as log:
            log.write(f"{os.environ.get('PYTEST_CURRENT_TEST', '?')} {host}:{port}\n")
    return ConnectionRefusedError(f"tests reach no machine outside this one ({host}:{port})")


_create_connection = socket.create_connection
_loop_create_connection = asyncio.base_events.BaseEventLoop.create_connection


def _guarded_create_connection(address, *args, **kwargs):
    if _outside(address[0]):
        raise _refuse(*address[:2])
    return _create_connection(address, *args, **kwargs)


async def _guarded_loop_create_connection(self, protocol_factory, host=None, port=None, **kwargs):
    if _outside(host):
        raise _refuse(host, port)
    return await _loop_create_connection(self, protocol_factory, host, port, **kwargs)


socket.create_connection = _guarded_create_connection
asyncio.base_events.BaseEventLoop.create_connection = _guarded_loop_create_connection
