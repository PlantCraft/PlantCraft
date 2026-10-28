"""One holder at a time for a FileLease, and the next one takes over once it is released."""

from __future__ import annotations

from plantcraft_sdk.server.lease import FileLease


def test_a_second_lease_waits_until_the_first_is_released(tmp_path):
    path = tmp_path / "engine.lock"
    first, second = FileLease(path), FileLease(path)
    assert first.acquire()
    assert first.acquire()  # held already: still granted
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()
    second.release()  # releasing twice is harmless
