"""Files written whole or not at all, created with their final mode (plantcraft.files)."""

from __future__ import annotations

import os
import stat

import pytest

from plantcraft.files import write_atomic


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_a_secret_is_never_readable_by_others_whatever_the_umask(tmp_path, monkeypatch):
    seen: list[int] = []
    real_fdopen = os.fdopen

    def fdopen(descriptor, *args, **kwargs):
        seen.append(stat.S_IMODE(os.fstat(descriptor).st_mode))  # before a byte is written
        return real_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", fdopen)
    old = os.umask(0)
    try:
        write_atomic(tmp_path / "secrets.json", '{"key": "s3cret"}')
    finally:
        os.umask(old)
    assert seen == [0o600]
    assert _mode(tmp_path / "secrets.json") == 0o600
    assert (tmp_path / "secrets.json").read_text() == '{"key": "s3cret"}'
    assert [p.name for p in tmp_path.iterdir()] == ["secrets.json"]


def test_it_replaces_the_old_file_with_the_mode_asked(tmp_path):
    target = tmp_path / "request.json"
    target.write_text("old")
    write_atomic(target, b"new", mode=0o640)
    assert target.read_bytes() == b"new" and _mode(target) == 0o640


def test_a_failed_write_keeps_the_old_file_and_leaves_nothing_behind(tmp_path, monkeypatch):
    target = tmp_path / "settings.json"
    target.write_text("old")
    monkeypatch.setattr(os, "chmod", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        write_atomic(target, "new")
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]
