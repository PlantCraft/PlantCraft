"""The engine runs in a process of its own: what the web process saves reaches its catalog."""

from __future__ import annotations

import shutil

from linkcraft.blocks import CATALOG, register_models
from linkcraft.blocks.models import model_block_id
from linkcraft.models.fmu import inspect_fmu, sha256_of
from tests.conftest import make_runtime
from tests.plant import make_fake
from tests.test_model_blocks import LOOP


def test_a_model_published_by_the_web_process_runs_in_the_engine(tmp_path):
    engine = make_runtime(tmp_path / "engine", make_fake())
    web = make_runtime(tmp_path / "engine", make_fake())
    try:
        upload = tmp_path / "upload.fmu"
        shutil.copy(LOOP, upload)
        # The web process keeps the model and registers it in its own memory only: here the
        # catalog is shared, so take the block out again as the engine process never had it.
        found = web.models.add_upload(
            upload,
            inspect_fmu(upload),
            sha256_of(upload),
            name="Furnaces (FMU)",
            description="",
            by="admin",
        )
        block_id = model_block_id(found["model_id"])
        register_models(engine.models.list()[:0])
        assert block_id not in CATALOG

        engine.sync_catalog()  # what Engine.execute does before each execution
        assert block_id in CATALOG
    finally:
        register_models([])
        engine.shutdown()
        web.shutdown()


def test_the_check_costs_nothing_when_nothing_changed(tmp_path):
    rt = make_runtime(tmp_path, make_fake())
    try:
        register_models([])
        rt.sync_catalog()
        # Nothing was saved since the runtime started: the catalog is left as it is.
        assert not [key for key in CATALOG if key.startswith("model.fmu_")]
    finally:
        rt.refresh_models()
        rt.shutdown()
