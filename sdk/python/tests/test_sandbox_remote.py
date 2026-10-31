"""Code run by a sandbox container through a Unix socket (plantcraft_sdk.sandbox_remote)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from plantcraft_sdk import sandbox
from plantcraft_sdk.sandbox import CodeError
from plantcraft_sdk.sandbox_remote import RemotePool


def _serve(tmp_path: Path, handler: str) -> tuple[subprocess.Popen, str]:
    path = str(tmp_path / "code.sock")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "plantcraft_sdk.sandbox_remote",
            "serve",
            "--socket",
            path,
            "--prefix",
            "TEST_CODE",
            "--handler",
            handler,
        ],
        env={**os.environ, "TEST_CODE_TIMEOUT_SECONDS": "3"},
    )
    for _ in range(100):
        if os.path.exists(path):
            break
        time.sleep(0.1)
    return process, path


def test_the_container_answers_and_reports_the_code_s_error(tmp_path):
    process, path = _serve(tmp_path, "math:sqrt")
    try:
        remote = RemotePool(path, timeout=3)
        assert remote.run(None, 16) == 4.0  # type: ignore[arg-type]
        with pytest.raises(CodeError, match="ValueError"):
            remote.run(None, -1)  # type: ignore[arg-type]
        # The caller names no function: the container runs only its own handler.
        assert remote.run(print, 9) == 3.0
    finally:
        process.terminate()
        process.wait(5)


def test_a_missing_container_is_a_code_error(tmp_path):
    with pytest.raises(CodeError, match="did not answer"):
        RemotePool(str(tmp_path / "none.sock"), timeout=1).run(None, 1)  # type: ignore[arg-type]


def test_the_pool_goes_remote_when_a_socket_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("REMOTE_CODE_SOCKET", str(tmp_path / "code.sock"))
    sandbox.use_pool("REMOTE_CODE", None)
    try:
        assert isinstance(sandbox.pool("REMOTE_CODE"), RemotePool)
    finally:
        sandbox.use_pool("REMOTE_CODE", None)
