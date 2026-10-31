"""Files Models reads back after a restart are written whole or not at all (plantcraft_sdk.files).

Storage test of 2026-10-31: a process killed while ``Path.write_text`` writes leaves half a JSON
file (71 of 100 kills). The write that fails half way here stands in for the kill.
"""

from __future__ import annotations

import json

import pytest
from plantcraft_sdk.files import write_atomic, write_json


class Boom(RuntimeError):
    pass


def test_a_write_that_fails_half_way_keeps_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "files.json"
    write_json(target, {"a.mo": "model A end A;"})

    import os

    real_fdopen = os.fdopen

    class HalfFile:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()
            return False

        def write(self, data):
            self.handle.write(data[: len(data) // 2])
            raise Boom("killed")

        def flush(self):
            self.handle.flush()

        def fileno(self):
            return self.handle.fileno()

    monkeypatch.setattr(os, "fdopen", lambda *a, **k: HalfFile(real_fdopen(*a, **k)))
    with pytest.raises(Boom):
        write_json(target, {"a.mo": "model A Real x; end A;" * 100})

    assert json.loads(target.read_text()) == {"a.mo": "model A end A;"}
    assert [p.name for p in tmp_path.iterdir()] == ["files.json"]  # no temporary left behind


def test_write_replaces_text_and_bytes(tmp_path):
    target = tmp_path / "names.json"
    write_atomic(target, "[1]")
    write_atomic(target, b"[2]")
    assert json.loads(target.read_text()) == [2]


def test_service_and_results_write_through_it():
    """The run files and result headers no longer write JSON in place."""

    from pathlib import Path

    import modelcraft.omc.results as results
    import modelcraft.runs.service as service

    for module in (service, results):
        assert "write_text(json.dumps(" not in Path(module.__file__).read_text()
