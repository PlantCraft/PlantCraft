"""Files written whole or not at all (plantcraft_sdk.files)."""

from __future__ import annotations

import json
import os
import stat

import pytest

from plantcraft_sdk.files import write_atomic, write_json


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class Killed(RuntimeError):
    pass


def test_a_write_killed_half_way_keeps_the_old_file_and_leaves_nothing(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    write_json(target, {"round": 1})
    real_fdopen = os.fdopen

    class Half:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()
            return False

        def write(self, data):
            self.handle.write(data[: len(data) // 2])
            raise Killed("killed")

    monkeypatch.setattr(os, "fdopen", lambda *a, **k: Half(real_fdopen(*a, **k)))
    with pytest.raises(Killed):
        write_json(target, {"round": 2, "pad": "x" * 1000})
    assert json.loads(target.read_text()) == {"round": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_a_secret_is_created_private_and_a_plain_file_follows_the_umask(tmp_path):
    old = os.umask(0o022)
    try:
        write_atomic(tmp_path / "key", b"s3cret", mode=0o600)
        write_json(tmp_path / "plain.json", [1], indent=2)
    finally:
        os.umask(old)
    assert _mode(tmp_path / "key") == 0o600 and (tmp_path / "key").read_bytes() == b"s3cret"
    assert _mode(tmp_path / "plain.json") == 0o644
    assert json.loads((tmp_path / "plain.json").read_text()) == [1]
