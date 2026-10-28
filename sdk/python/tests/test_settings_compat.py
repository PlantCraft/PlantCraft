"""Settings and imports named before the rename to PlantCraft (2026-10-27) still work."""

import subprocess
import sys

from plantcraft_sdk.settings_compat import adopt


def test_former_settings_are_copied_to_the_new_names():
    env = {
        "PROCESSCRAFT_URL": "http://old",
        "PROCESSCRAFT_APPS": "a=/a/",
        "PLANTCRAFT_APPS": "b=/b/",
    }
    assert adopt(env) == ["PLANTCRAFT_URL", "PLANTCRAFT_APPS"]
    assert env["PLANTCRAFT_URL"] == "http://old"
    # The old name wins: beside it the new one is an image's default (ENV in its Dockerfile).
    assert env["PLANTCRAFT_APPS"] == "a=/a/"
    assert adopt(env) == []


def test_the_simulators_old_version_setting_does_not_hide_the_platforms():
    env = {"PROCESSCRAFT_VERSION": "0.5.0", "PLANTCRAFT_VERSION": "0.4.1"}
    adopt(env)
    assert env["PLANTCRAFT_VERSION"] == "0.5.0"


def test_the_former_import_is_the_same_module():
    code = (
        "import processcraft_sdk.client as old, plantcraft_sdk.client as new;"
        "assert old is new;"
        "from processcraft_sdk.server.store import Store;"
        "from plantcraft_sdk.server.store import Store as S; assert Store is S"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_compose_files_before_the_rename_start_a_compute_worker():
    run = subprocess.run(
        [sys.executable, "-m", "processcraft_sdk.compute", "--help"],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert "gateway" in run.stdout
