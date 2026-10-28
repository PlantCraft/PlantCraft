"""Blocks written on the site: the block file, the checks on its code, versions and the API."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest
from plantcraft_sdk.blocks import Context, execute

from linkcraft.blocks import CATALOG, compile_algorithm, sandbox
from linkcraft.blocks.catalog import CURRENT
from linkcraft.blocks.files import read_file
from linkcraft.blocks.guide import EXAMPLE
from tests.conftest import client_for
from tests.plant import NOW

SMOOTH = {
    "name": "Smooth",
    "library": "custom",
    "docs": {"summary": "A moving average."},
    "inputs": [{"port": "x", "type": "series", "description": "The signal."}],
    "outputs": [
        {"port": "y", "type": "series", "description": "Smoothed."},
        {"port": "runs", "type": "number", "description": "How many times it ran."},
    ],
    "parameters": [{"name": "window", "type": "integer", "default": 3, "minimum": 1}],
    "code": (
        "def run(inputs, params, ctx):\n"
        "    ctx.state['runs'] = ctx.state.get('runs', 0) + 1\n"
        "    return {'y': inputs['x'].rolling(params.window, min_periods=1).mean(),\n"
        "            'runs': float(ctx.state['runs'])}\n"
    ),
}


def series(count: int = 10) -> pd.Series:
    return pd.Series(
        np.arange(count, dtype=float), index=pd.date_range("2026-01-01", periods=count, freq="min")
    )


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"library": "input"}, "library must be one of"),
        ({"outputs": []}, "outputs"),
        ({"inputs": [{"port": "x", "type": "series"}, {"port": "x", "type": "number"}]}, "share"),
        (
            {"parameters": [{"name": "w", "type": "integer", "default": 0, "minimum": 1}]},
            "below its minimum",
        ),
        ({"parameters": [{"name": "w", "type": "choice", "choices": []}]}, "lists its choices"),
        ({"block_id": "transform.smooth"}, "starts with the block's library"),
    ],
)
def test_a_block_file_says_what_is_wrong(change, problem):
    with pytest.raises(ValueError, match=problem):
        read_file({**SMOOTH, **change})


@pytest.mark.parametrize(
    ("code", "problem"),
    [
        ("import os\ndef run(i, p, c):\n    return {}\n", "importing os"),
        ("from pandas.io import sql\ndef run(i, p, c):\n    return {}\n", "importing pandas.io"),
        ("def run(i, p, c):\n    return ().__class__\n", "start with _"),
        ("def run(i, p, c):\n    return eval('1')\n", "eval is not allowed"),
        ("def run(i, p, c):\n    return open('/etc/passwd')\n", "open is not allowed"),
        ("import numpy as np\ndef run(i, p, c):\n    np.save('x', 1)\n", "save is not allowed"),
        ("def run(i, p, c):\n    return '{0.x}'.format(i)\n", "format is not allowed"),
        ("def go(i, p, c):\n    return {}\n", "no run(inputs, params, ctx)"),
        ("def run(i):\n    return {}\n", "exactly three arguments"),
        ("def run(i, p, c)\n    return {}\n", "Line 1"),
        ("import pandas as pd\ndef run(i, p, c):\n    pd.read_csv('/etc/x')\n", "read_csv"),
        ("from pandas import read_pickle\ndef run(i, p, c):\n    return {}\n", "read_pickle"),
        ("from numpy.testing import runstring\ndef run(i, p, c):\n    return {}\n", "numpy"),
    ],
)
def test_block_code_is_checked_before_it_runs(code, problem):
    assert any(problem in item for item in sandbox.check_code(code))


@pytest.mark.parametrize(
    "reach",
    [
        "from typing import sys\nos = sys.modules['os']",
        "import typing\nos = typing.sys.modules['os']",
        "import re\nos = re.enum.sys.modules['os']",
        "import dataclasses\nos = dataclasses.sys.modules['os']",
        "import numpy as np\nos = np.testing",
        "import linkcraft.blocks.base\nos = linkcraft.config",
    ],
)
def test_allowed_modules_never_lead_to_the_system(reach):
    # Allowed modules import sys, os and the rest themselves: code that passes the check still
    # finds only allowed modules through their attributes.
    code = f"{reach}\ndef run(i, p, c):\n    return {{}}\n"
    assert sandbox.check_code(code) == []
    with pytest.raises((AttributeError, ImportError), match="not allowed|cannot import"):
        sandbox.execute(sandbox.Call(key=reach, code=code, inputs={}, params={}))


def test_allowed_modules_still_work_through_their_guard():
    code = (
        "import numpy as np\nimport pandas as pd\nfrom numpy import linalg\n"
        "import linkcraft.blocks.base\nimport plantcraft_sdk.blocks as blocks\n"
        "def run(i, p, c):\n"
        "    s = pd.Series([1.0, 2.0, 3.0]).rolling(2).mean()\n"
        "    return {'y': float(np.nanmean(s)) + float(linalg.norm(np.array([3.0, 4.0]))),\n"
        "            'z': blocks.Result is not None and linkcraft.blocks.base is not None}\n"
    )
    outputs, _ = sandbox.execute(sandbox.Call(key="guarded", code=code, inputs={}, params={}))
    assert outputs == {"y": 7.0, "z": True}


def test_the_example_the_assistant_reads_is_a_valid_block():
    file = read_file(EXAMPLE)
    assert sandbox.check_code(file.code) == []


def test_site_blocks_are_versioned_and_algorithms_keep_their_version(runtime, fake):
    with client_for(runtime, fake, "admin") as admin, client_for(runtime, fake) as engineer:
        refused = engineer.post("/link/api/blocks", json={"file": SMOOTH})
        assert refused.status_code == 403
        created = admin.post("/link/api/blocks", json={"file": SMOOTH, "version_name": "First"})
        assert created.status_code == 200, created.text
        assert created.json()["pinned"] == "custom.smooth.v1"

        page = engineer.get("/link/api/blocks/custom.smooth").json()
        assert (page["author"], page["owner"], page["site"], page["number"]) == (
            "admin",
            "admin",
            True,
            1,
        )
        assert [item["name"] for item in page["versions"]] == ["First"]
        code = engineer.get("/link/api/blocks/custom.smooth/code").json()
        assert "rolling" in code["sources"][0]["source"]

        # An algorithm names version 1.
        diagram = {
            "nodes": [
                {"id": "pv", "block": "input.signal", "parameters": {"role": "pv"}},
                {"id": "s", "block": "custom.smooth.v1", "record": ["y"]},
            ],
            "edges": [{"source": "pv", "source_port": "value", "target": "s", "target_port": "x"}],
        }
        assert compile_algorithm(diagram).valid

        wider = copy.deepcopy(SMOOTH)
        wider["parameters"][0]["default"] = 5
        check = engineer.post(
            "/link/api/blocks/check", json={"file": {**wider, "block_id": "custom.smooth"}}
        ).json()
        assert check["valid"] and check["contract_changed"] is False
        saved = admin.post(
            "/link/api/blocks/custom.smooth/versions",
            json={"file": wider, "name": "Window 5", "description": "Smoother."},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["pinned"] == "custom.smooth.v2"

        palette = engineer.get("/link/api/blocks").json()["blocks"]
        mine = [item for item in palette if item["library"] == "custom"]
        assert [(item["block_id"], item["author"]) for item in mine] == [
            ("custom.smooth.v2", "admin")
        ]
        # Version 1 still runs with its own default, as the algorithm saved it.
        plan = compile_algorithm(diagram)
        values = execute(
            plan,
            CATALOG,
            context=Context(),
            preset={("pv", "value"): series(), ("pv", "recorded"): series()},
        )
        assert values.get("s", "y").iloc[-1] == pytest.approx(8.0)
        two = CATALOG["custom.smooth.v2"]
        assert two.run({"x": series()}, two.spec.parameters(), Context(node_id="n"))["y"].iloc[
            -1
        ] == pytest.approx(7.0)

        updated = admin.patch(
            "/link/api/blocks/custom.smooth",
            json={"owner": "engineer", "owner_name": "Process Engineer", "tags": ["Filters"]},
        ).json()
        assert (updated["owner"], updated["tags"]) == ("engineer", ["filters"])
        versions = engineer.get("/link/api/blocks/custom.smooth").json()["versions"]
        assert [item["number"] for item in versions] == [2, 1]
        downloaded = engineer.get("/link/api/blocks/custom.smooth/file?version=1").json()
        assert downloaded["version"]["number"] == 1
        assert downloaded["parameters"][0]["default"] == 3

        assert admin.delete("/link/api/blocks/custom.smooth").status_code == 200
        assert engineer.get("/link/api/blocks/custom.smooth").status_code == 404


def test_a_new_version_that_changes_the_ports_says_so(runtime, fake):
    with client_for(runtime, fake, "admin") as admin:
        admin.post("/link/api/blocks", json={"file": SMOOTH})
        changed = {**SMOOTH, "outputs": SMOOTH["outputs"][:1]}
        check = admin.post(
            "/link/api/blocks/check", json={"file": {**changed, "block_id": "custom.smooth"}}
        ).json()
        assert check["contract_changed"] is True
        saved = admin.post(
            "/link/api/blocks/custom.smooth/versions",
            json={"file": changed, "name": "One output"},
        ).json()
        assert saved["contract_changed"] is True


def test_a_shipped_block_shows_its_code_and_copies_into_a_site_block(runtime, fake):
    with client_for(runtime, fake, "admin") as admin:
        # One code: the calculation alone (owner, 2026-10-24), not the block's declaration.
        code = admin.get("/link/api/blocks/transform.moving_average/code").json()
        assert code["site"] is False and len(code["sources"]) == 1
        assert code["sources"][0]["filename"].endswith("transforms.py")
        assert code["sources"][0]["source"].startswith("def calculate(i, p, _c):")
        assert "rolling" in code["sources"][0]["source"]
        filtered = admin.get("/link/api/blocks/transform.first_order_filter/code").json()
        assert filtered["sources"][0]["source"].startswith("def _ewm(")
        stiction = admin.get("/link/api/blocks/cpm.stiction_screening/code").json()
        assert len(stiction["sources"]) == 1
        assert stiction["sources"][0]["source"].startswith("def run(")
        frozen = admin.get("/link/api/blocks/dq.frozen/code").json()["sources"][0]["source"]
        assert frozen.startswith("def frozen(") and "@method" not in frozen
        assert admin.get("/link/api/blocks/input.signal/copy").status_code == 422

        start = admin.get("/link/api/blocks/transform.moving_average/copy").json()
        assert start["library"] == "custom" and "shipped(" in start["code"]
        created = admin.post("/link/api/blocks", json={"file": start}).json()
        block = CATALOG[created["pinned"]]
        given = block.run({"x": series()}, block.spec.parameters(), Context(node_id="n"))
        assert given["value"].iloc[-1] == pytest.approx(7.0)

        # A control loop block duplicates too (owner, 2026-10-27): the copy runs the method on
        # the signals wired to it, as the original does on an asset.
        start = admin.get("/link/api/blocks/cpm.error_metrics_basic/copy").json()
        assert start["library"] == "custom" and "shipped(" in start["code"]
        created = admin.post("/link/api/blocks", json={"file": start}).json()
        block = CATALOG[created["pinned"]]
        pv = series()
        given = block.run(
            {"pv": pv, "sp": pv * 0 + 5.0}, block.spec.parameters(), Context(node_id="n")
        )
        assert set(given) >= {"result", "mae"}


def _legacy_version(runtime, file: dict, name: str) -> None:
    """A site's version of a block Link ships, saved before round 10 locked them (owner D2,
    2026-10-25): the store still holds and runs them; the API takes no new one."""

    block_id = file["block_id"]
    if runtime.blocks.get(block_id) is None:
        runtime.blocks.create(
            read_file(file).model_copy(update={"origin": "user"}),
            "admin",
            version_name=name,
            shipped=True,
        )
    else:
        runtime.blocks.add_version(block_id, read_file(file), "admin", name=name)


def test_a_shipped_block_takes_no_new_version_on_the_site(runtime, fake):
    """Round 10 (2026-10-26): a block PlantCraft ships changes with PlantCraft; the server holds
    the lock the page shows, even for a block the site gave versions before."""

    with client_for(runtime, fake, "admin") as admin, client_for(runtime, fake) as engineer:
        start = admin.get("/link/api/blocks/transform.moving_average/copy?edit=true").json()
        refused = admin.post(
            "/link/api/blocks/transform.moving_average/versions",
            json={"file": start, "name": "Mine"},
        )
        assert refused.status_code == 409 and "Duplicate" in refused.json()["detail"]
        assert runtime.blocks.get("transform.moving_average") is None
        page = engineer.get("/link/api/blocks/transform.moving_average").json()
        assert page["locked"] and not page["site"]
        _legacy_version(runtime, start, "Before the lock")
        page = engineer.get("/link/api/blocks/transform.moving_average").json()
        assert page["site"] and page["locked"]
        again = admin.post(
            "/link/api/blocks/transform.moving_average/versions",
            json={"file": start, "name": "Again"},
        )
        assert again.status_code == 409
        assert admin.post("/link/api/blocks", json={"file": SMOOTH}).status_code == 200
        assert not engineer.get("/link/api/blocks/custom.smooth").json()["locked"]


def test_a_shipped_blocks_older_site_version_is_2_and_algorithms_keep_version_1(runtime, fake):
    """Owner D2 (2026-10-25): a site's version of a block Link ships is version 2 of the same
    block; Link's own stays version 1 for the algorithms that use it."""

    with client_for(runtime, fake, "admin") as admin, client_for(runtime, fake) as engineer:
        assert admin.get("/link/api/blocks/input.signal/copy?edit=true").status_code == 422
        start = admin.get("/link/api/blocks/transform.moving_average/copy?edit=true").json()
        assert start["block_id"] == "transform.moving_average"
        assert start["library"] == "transform" and "shipped(" in start["code"]
        start["code"] = start["code"].replace(
            "return outputs", "return {'value': outputs['value'] * 2}"
        )
        _legacy_version(runtime, start, "Doubled")

        page = engineer.get("/link/api/blocks/transform.moving_average").json()
        assert page["site"] and page["number"] == 2 and page["editable"]
        assert [(item["number"], item.get("shipped", False)) for item in page["versions"]] == [
            (2, False),
            (1, True),
        ]
        one = engineer.get("/link/api/blocks/transform.moving_average/code?version=1").json()
        assert one["sources"][0]["source"].startswith("def calculate(")
        assert (
            engineer.get("/link/api/blocks/transform.moving_average/file?version=1").json()[
                "block_id"
            ]
            == "transform.moving_average"
        )

        # The palette lists the site's version only; version 1 still runs where it is used.
        palette = [item["block_id"] for item in engineer.get("/link/api/blocks").json()["blocks"]]
        assert "transform.moving_average.v2" in palette
        assert "transform.moving_average" not in palette
        one_block = CATALOG["transform.moving_average"]
        two_block = CATALOG["transform.moving_average.v2"]
        context = Context(node_id="n")
        first = one_block.run({"x": series()}, one_block.spec.parameters(), context)["value"]
        second = two_block.run({"x": series()}, two_block.spec.parameters(), context)["value"]
        assert second.iloc[-1] == pytest.approx(2 * first.iloc[-1])

        _legacy_version(runtime, start, "Again")
        assert [item["number"] for item in runtime.blocks.versions("transform.moving_average")] == [
            3,
            2,
        ]
        assert admin.delete("/link/api/blocks/transform.moving_average").status_code == 200
        palette = [item["block_id"] for item in engineer.get("/link/api/blocks").json()["blocks"]]
        assert "transform.moving_average" in palette


def test_a_block_page_opens_any_version_and_one_is_selected_for_use(runtime, fake):
    """Owner D17 (2026-10-26): a version opens the block's page at that version; Select version
    sets the one in use, which the palette and new algorithms take."""

    with client_for(runtime, fake, "admin") as admin, client_for(runtime, fake) as engineer:
        admin.post("/link/api/blocks", json={"file": SMOOTH, "version_name": "First"})
        wider = copy.deepcopy(SMOOTH)
        wider["parameters"][0]["default"] = 5
        admin.post("/link/api/blocks/custom.smooth/versions", json={"file": wider, "name": "Five"})

        one = engineer.get("/link/api/blocks/custom.smooth?version=1").json()
        assert (one["number"], one["current"]) == (1, False)
        assert one["parameters"][0]["default"] == 3
        assert [item["number"] for item in one["versions"]] == [2, 1]
        assert engineer.get("/link/api/blocks/custom.smooth?version=9").status_code == 404
        assert one["in_use"] == 2
        duplicate = engineer.get("/link/api/blocks/custom.smooth/copy?version=1").json()
        assert duplicate["block_id"] == "" and duplicate["parameters"][0]["default"] == 3

        assert (
            engineer.post("/link/api/blocks/custom.smooth/current", json={"number": 1}).status_code
            == 403
        )
        assert (
            admin.post("/link/api/blocks/custom.smooth/current", json={"number": 7}).status_code
            == 404
        )
        selected = admin.post("/link/api/blocks/custom.smooth/current", json={"number": 1})
        assert selected.status_code == 200, selected.text
        page = engineer.get("/link/api/blocks/custom.smooth").json()
        assert (page["number"], page["current"]) == (1, True)
        palette = [item["block_id"] for item in engineer.get("/link/api/blocks").json()["blocks"]]
        assert "custom.smooth.v1" in palette and "custom.smooth.v2" not in palette
        # The next version still follows the newest one.
        saved = admin.post(
            "/link/api/blocks/custom.smooth/versions", json={"file": SMOOTH, "name": "Three"}
        ).json()
        assert saved["pinned"] == "custom.smooth.v3"

        # A block Link ships: selecting version 1 brings Link's own back, the site's stay.
        start = admin.get("/link/api/blocks/transform.moving_average/copy?edit=true").json()
        _legacy_version(runtime, start, "Mine")
        admin.post("/link/api/blocks/transform.moving_average/current", json={"number": 1})
        page = engineer.get("/link/api/blocks/transform.moving_average").json()
        assert (page["site"], page["number"], page["current"]) == (True, 1, True)
        assert [item["number"] for item in page["versions"]] == [2, 1]
        two = engineer.get("/link/api/blocks/transform.moving_average?version=2").json()
        assert (two["number"], two["current"], two["in_use"]) == (2, False, 1)
        shipped = engineer.get("/link/api/blocks/transform.moving_average/copy?version=1").json()
        assert "shipped(" in shipped["code"] and shipped["library"] == "custom"
        palette = [item["block_id"] for item in engineer.get("/link/api/blocks").json()["blocks"]]
        assert "transform.moving_average" in palette
        assert "transform.moving_average.v2" not in palette
        # Another process (the engine) sees the same choice.
        CURRENT["transform.moving_average"] = "transform.moving_average.v2"
        assert runtime.blocks.sync() == []
        assert "transform.moving_average" not in CURRENT
        palette = [item["block_id"] for item in engineer.get("/link/api/blocks").json()["blocks"]]
        assert "transform.moving_average" in palette


def test_a_block_runs_on_an_asset_before_it_is_saved(runtime, fake):
    runtime.sync_loops()
    draft = {"file": SMOOTH, "asset_id": "fic-101", "roles": {"x": "pv"}, "end": NOW.isoformat()}
    # A draft is code nobody saved: only those who write blocks (administrators) run one.
    with client_for(runtime, fake) as engineer:
        assert engineer.post("/link/api/blocks/test", json=draft).status_code == 403
    with client_for(runtime, fake, "admin") as engineer:
        tested = engineer.post("/link/api/blocks/test", json=draft)
        assert tested.status_code == 200, tested.text
        found = tested.json()
        assert found["check"]["valid"], found["check"]
        assert found["outputs"]["y"]["type"] == "series" and found["outputs"]["y"]["count"] > 10
        assert found["outputs"]["runs"] == {"type": "number", "value": 1.0}
        # The draft is never listed.
        palette = engineer.get("/link/api/blocks").json()["blocks"]
        assert not [item for item in palette if item["block_id"].startswith("draft.")]


def test_the_new_block_prompt_carries_the_request_the_format_and_the_catalog(runtime, fake):
    with client_for(runtime, fake) as client:
        prompt = client.get(
            "/link/api/prompts/new-block", params={"request": "Detect fouling from UA."}
        ).json()
    assert "Detect fouling from UA." in prompt["text"]
    assert "plantcraft-block/1" in prompt["text"] and "transform.moving_average" in prompt["text"]
    item = runtime.explain("block:linkcraft/new")
    assert item and "A complete example" in item["text"]


def test_block_workers_stop_slow_code_and_refuse_files_and_network():
    pool = sandbox.CodePool(workers=1, timeout=4)
    try:

        def call(code: str) -> sandbox.Call:
            return sandbox.Call(key=str(hash(code)), code=code, inputs={}, params={})

        assert pool.run(call("def run(i, p, c):\n    return {'y': 2.0}\n"))[0] == {"y": 2.0}
        # Passes the checks, but the worker may not write a file.
        writes = (
            "import pandas as pd\n"
            "def run(i, p, c):\n"
            "    pd.Series([1.0]).to_json('/tmp/linkcraft-block-test.json')\n"
            "    return {}\n"
        )
        assert sandbox.check_code(writes) == []
        with pytest.raises((OSError, sandbox.BlockCodeError)):
            pool.run(call(writes))
        with pytest.raises(sandbox.BlockCodeError, match="did not finish"):
            pool.run(call("def run(i, p, c):\n    while True:\n        pass\n"))
        assert any("socket" in item for item in sandbox.check_code("import socket\n"))
        with pytest.raises(sandbox.BlockCodeError, match="not allowed"):
            pool.run(call("import urllib.request\ndef run(i, p, c):\n    return {}\n"))
    finally:
        pool.shutdown()


def test_a_block_keeps_its_image_with_the_version_and_serves_it_by_a_tagged_url(runtime, fake):
    """Round 9 M2: the image is part of the version; the catalog carries its path, not the
    picture; an SVG loses its script; anything that is not a picture is refused."""

    import base64

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>x</script><rect width="4" height="4"/></svg>'
    pictured = {**SMOOTH, "image": "data:image/png;base64," + base64.b64encode(png).decode()}
    with client_for(runtime, fake, "admin") as admin, client_for(runtime, fake) as engineer:
        bad = engineer.post(
            "/link/api/blocks/check",
            json={"file": {**SMOOTH, "image": "data:image/png;base64,R0lGODlh"}},
        ).json()
        assert not bad["valid"] and any(
            "PNG, JPEG, WebP or SVG" in item for item in bad["problems"]
        )
        assert admin.post("/link/api/blocks", json={"file": pictured}).status_code == 200

        palette = engineer.get("/link/api/blocks").json()["blocks"]
        mine = next(item for item in palette if item["block_id"] == "custom.smooth.v1")
        assert mine["image"].startswith("/api/blocks/custom.smooth.v1/image?v=")
        served = engineer.get("/link" + mine["image"])
        assert served.status_code == 200 and served.content == png
        assert served.headers["content-type"] == "image/png"
        assert "immutable" in served.headers["cache-control"]

        drawn = {**SMOOTH, "image": "data:image/svg+xml;base64," + base64.b64encode(svg).decode()}
        assert (
            admin.post(
                "/link/api/blocks/custom.smooth/versions", json={"file": drawn, "name": "Drawn"}
            ).status_code
            == 200
        )
        page = engineer.get("/link/api/blocks/custom.smooth").json()
        assert page["image"].startswith("/api/blocks/custom.smooth.v2/image?v=")
        text = engineer.get("/link" + page["image"]).text
        assert "rect" in text and "script" not in text and "onload" not in text
        # Version 1 keeps its own picture, and a block without one has none.
        assert (
            engineer.get("/link/api/blocks/custom.smooth?version=1").json()["image"]
            == mine["image"]
        )
        assert (
            engineer.get("/link/api/blocks/custom.smooth/file?version=1").json()["image"]
            == pictured["image"]
        )
        assert engineer.get("/link/api/blocks/stats.mean/image").status_code == 404


def test_a_site_makes_its_own_libraries_and_puts_blocks_in_them(runtime, fake):
    """Round 10 (owner, 2026-10-26): blocks sit in libraries, not folders; New library makes one
    of this site, listed after Link's (before Outputs), and a block joins it."""

    with client_for(runtime, fake, "admin") as admin, client_for(runtime, fake) as engineer:
        assert (
            engineer.post("/link/api/blocks/libraries", json={"name": "Exchangers"}).status_code
            == 403
        )
        made = admin.post(
            "/link/api/blocks/libraries",
            json={"name": "Heat exchangers", "description": "Fouling and UA."},
        )
        assert made.status_code == 200, made.text
        assert made.json()["library"] == "heat_exchangers"
        again = admin.post("/link/api/blocks/libraries", json={"name": "heat exchangers"})
        assert again.status_code == 422 and "already exists" in again.json()["detail"]
        shipped_name = admin.post("/link/api/blocks/libraries", json={"name": "Transforms"})
        assert shipped_name.status_code == 422
        # Its id never takes one of Link's, even from a name that would.
        other = admin.post("/link/api/blocks/libraries", json={"name": "Input"}).json()
        assert other["library"] == "input_2"

        palette = engineer.get("/link/api/blocks").json()
        keys = [item["library"] for item in palette["libraries"]]
        assert keys[-1] == "output" and keys.index("heat_exchangers") > keys.index("custom")
        mine = next(item for item in palette["libraries"] if item["library"] == "heat_exchangers")
        assert mine["site"] and mine["count"] == 0 and mine["description"] == "Fouling and UA."
        assert "heat_exchangers" in palette["open_libraries"]

        block = {**SMOOTH, "name": "UA trend", "library": "heat_exchangers"}
        saved = admin.post("/link/api/blocks", json={"file": block})
        assert saved.status_code == 200, saved.text
        assert saved.json()["block_id"] == "heat_exchangers.ua_trend"
        palette = engineer.get("/link/api/blocks").json()
        mine = next(item for item in palette["libraries"] if item["library"] == "heat_exchangers")
        assert mine["count"] == 1
        # A closed library stays closed, a made-up id in a file is still a library of its own.
        assert read_file({**SMOOTH, "library": "plant_extras"}).library == "plant_extras"
        with pytest.raises(ValueError, match="library must be one of"):
            read_file({**SMOOTH, "library": "output"})
