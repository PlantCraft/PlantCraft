"""Algorithms: block diagrams with typed ports, checked before they run (``linkcraft.blocks``).

A diagram joins signal quality and loop performance: the PV's data quality checks and the valve
methods are combined, a rule says what counts, and the outcome is published on the loop's asset,
recorded in the historian and raised as a message. The algorithms Link ships, and the protocols
of 0.2 converted to diagrams, all pass the same checks.
"""

from __future__ import annotations

import copy

import pytest
from plantcraft_sdk.blocks import Context, check_algorithm, check_catalog, execute

from linkcraft.blocks import CATALOG, compile_algorithm
from linkcraft.blocks.algorithms import BY_ID, SYSTEM
from linkcraft.blocks.convert import diagram_of, from_flow, from_methods, methods_in
from linkcraft.blocks.outputs import collected, output_key
from linkcraft.blocks.stored import converted
from linkcraft.catalog.registry import METHOD_SPECS
from tests.conftest import client_for, make_runtime
from tests.plant import make_fake


def _edge(source, source_port, target, target_port):
    return {
        "source": source,
        "source_port": source_port,
        "target": target,
        "target_port": target_port,
    }


# PV quality and the valve, combined by a rule, published three ways.
PV_AND_VALVE = {
    "version": 2,
    "nodes": [
        {"id": "pv", "block": "input.signal", "parameters": {"role": "pv"}},
        {"id": "op", "block": "input.signal", "parameters": {"role": "op"}},
        {"id": "frozen", "block": "dq.frozen"},
        {"id": "spikes", "block": "dq.spikes"},
        {"id": "pv_quality", "block": "logic.worst", "label": "PV quality"},
        {"id": "stiction", "block": "cpm.stiction_screening", "record": ["stiction_score"]},
        {"id": "saturation", "block": "cpm.op_saturation_fraction"},
        {"id": "valve", "block": "logic.worst"},
        {
            "id": "rule",
            "block": "logic.rule",
            "parameters": {"when": "bad", "then": "bad", "message": "PV data not usable."},
            "record": ["result"],
        },
        {"id": "out", "block": "output.result", "parameters": {"name": "Valve and PV"}},
        {"id": "msg", "block": "output.message", "parameters": {"when": "bad"}},
    ],
    "edges": [
        _edge("pv", "recorded", "frozen", "x"),
        _edge("pv", "recorded", "spikes", "x"),
        _edge("frozen", "result", "pv_quality", "in"),
        _edge("spikes", "result", "pv_quality", "in"),
        _edge("pv", "value", "stiction", "pv"),
        _edge("op", "value", "stiction", "op"),
        _edge("op", "value", "saturation", "op"),
        _edge("stiction", "result", "valve", "in"),
        _edge("saturation", "result", "valve", "in"),
        _edge("pv_quality", "result", "rule", "test"),
        _edge("valve", "result", "rule", "value"),
        _edge("rule", "result", "out", "in"),
        _edge("rule", "result", "msg", "in"),
    ],
}


def _copy(diagram=PV_AND_VALVE):
    return copy.deepcopy(diagram)


# The catalog and the shipped algorithms ------------------------------------------------------


def test_every_block_is_documented_in_the_same_format():
    assert check_catalog(CATALOG) == []
    assert len(CATALOG) >= 40
    # Every loop method is a block, and so is every data quality check.
    for method_id in METHOD_SPECS:
        if not method_id.startswith("dq_"):
            assert f"cpm.{method_id}" in CATALOG, method_id


@pytest.mark.parametrize("item", SYSTEM, ids=lambda item: item["algorithm_id"])
def test_every_shipped_algorithm_is_valid_and_documented(item):
    plan = compile_algorithm(item["diagram"])
    assert plan.errors == [], plan.errors
    assert check_algorithm(item["name"], item["docs"]) == []
    assert len(SYSTEM) == 7 and BY_ID[item["algorithm_id"]] is item


def test_a_protocol_of_0_2_becomes_a_diagram_with_its_gate_drawn():
    diagram = from_methods(["error_metrics_basic", "stiction_screening", "manual_mode_fraction"])
    plan = compile_algorithm(diagram)
    assert plan.errors == [], plan.errors
    blocks = {node["id"]: node["block"] for node in diagram["nodes"]}
    assert blocks["data"] == "dq.loop_data" and blocks["health"] == "output.loop_health"
    wired = {(edge["source"], edge["target"], edge["target_port"]) for edge in diagram["edges"]}
    # The methods read the signals through the loop data check; the score leaves stiction out
    # (a diagnostic) and manual mode is context.
    assert ("data", "error_metrics_basic", "pv") in wired
    assert ("stiction_screening", "health", "diagnostics") in wired
    assert ("stiction_screening", "health", "methods") not in wired
    assert ("manual_mode_fraction", "health", "context") in wired
    assert methods_in(diagram)[-3:] == [
        "error_metrics_basic",
        "stiction_screening",
        "manual_mode_fraction",
    ]


def test_a_version_1_diagram_is_converted_with_its_series_recorded():
    old = {
        "nodes": [
            {"id": "sig_pv", "kind": "signal", "signal": "pv"},
            {"id": "sig_op", "kind": "signal", "signal": "op"},
            {"id": "chk", "kind": "check", "check": "sq_frozen"},
            {"id": "m", "kind": "method", "method_id": "op_saturation_fraction"},
            {"id": "w", "kind": "combine", "combine": "worst"},
            {"id": "score", "kind": "score"},
            {"id": "res", "kind": "result", "parameters": {"name": "Valve"}},
            {"id": "ser", "kind": "series", "parameters": {"name": "Valve"}},
        ],
        "edges": [
            {"source": "sig_pv", "target": "chk", "target_port": "x"},
            {"source": "sig_op", "target": "m", "target_port": "op"},
            {"source": "chk", "target": "w", "target_port": "a"},
            {"source": "m", "target": "w", "target_port": "b"},
            {"source": "m", "target": "score"},
            {"source": "w", "target": "res"},
            {"source": "w", "target": "ser"},
        ],
    }
    diagram = from_flow(old)
    plan = compile_algorithm(diagram)
    assert plan.errors == [], plan.errors
    assert {node: ports for node, ports in plan.recorded.items() if ports} == {"w": ["result"]}
    assert plan.nodes["m"]["block"] == "cpm.op_saturation_fraction"
    # The saved configuration of 0.2 converts as a whole, with its documentation.
    config = converted({"flow": old, "docs": {"summary": "Valve check. More text."}})
    assert config["docs"] == {"purpose": "Valve check."} and config["diagram"]["nodes"]
    assert converted(config) is None
    assert diagram_of({"flow": old}) == diagram


def _without(diagram, source, target):
    diagram["edges"] = [
        edge
        for edge in diagram["edges"]
        if not (edge["source"] == source and edge["target"] == target)
    ]
    return diagram


def _node(diagram, node_id):
    return next(node for node in diagram["nodes"] if node["id"] == node_id)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        # A verdict into a signal input.
        (
            lambda d: d["edges"].append(_edge("frozen", "result", "saturation", "op")),
            "gives result; input OP of Output saturation takes series",
        ),
        (
            lambda d: _without(d, "pv_quality", "rule"),
            "Input Test of Rule (if … then) is not wired.",
        ),
        (lambda d: _node(d, "out")["parameters"].update(name=""), "give it a name"),
        (
            lambda d: (
                d["nodes"].append(
                    {"id": "dup", "block": "output.result", "parameters": {"name": "valve and pv!"}}
                )
                or d["edges"].append(_edge("valve", "result", "dup", "in"))
            ),
            "Two outputs are called",
        ),
        (lambda d: d["nodes"].append({"id": "x", "block": "dq.nope"}), "dq.nope"),
        (lambda d: _node(d, "rule")["parameters"].update(when="sometimes"), "when"),
        (
            lambda d: d["edges"].append(_edge("rule", "result", "pv_quality", "in")),
            "loop",
        ),
    ],
)
def test_the_check_explains_wrong_wiring(change, message):
    diagram = _copy()
    change(diagram)
    errors = compile_algorithm(diagram).errors
    assert any(message in error for error in errors), errors


def test_a_diagram_without_outputs_runs_for_nothing_and_says_so():
    diagram = {
        "nodes": [
            {"id": "pv", "block": "input.signal", "parameters": {"role": "pv"}},
            {"id": "c", "block": "dq.frozen"},
        ],
        "edges": [_edge("pv", "recorded", "c", "x")],
    }
    assert compile_algorithm(diagram).errors
    # Recording a port is an output of its own.
    diagram["nodes"][1]["record"] = ["result"]
    assert compile_algorithm(diagram).errors == []


def test_one_loop_health_per_algorithm():
    diagram = from_methods(["error_metrics_basic"])
    diagram["nodes"].append({"id": "health_2", "block": "output.loop_health"})
    diagram["edges"].append(_edge("error_metrics_basic", "result", "health_2", "methods"))
    plan = compile_algorithm(diagram)
    assert "An algorithm has one Loop health block." in plan.errors


def test_output_keys_are_plain():
    assert output_key("Válvula e PV") == "valvula_e_pv"
    assert output_key("  ") == ""
    assert len(output_key("x" * 200)) == 40


# Combining -----------------------------------------------------------------------------------


def _verdicts(logic: dict, ports: list[str]) -> dict:
    roles = ["pv", "sp", "op"][: len(ports)]
    return {
        "nodes": [
            *(
                {"id": role, "block": "input.verdict", "parameters": {"role": role}}
                for role in roles
            ),
            {"id": "c", **logic},
            {"id": "out", "block": "output.result", "parameters": {"name": "Out"}},
            {"id": "msg", "block": "output.message", "parameters": {"text": "Call I&C."}},
        ],
        "edges": [
            *(_edge(role, "result", "c", port) for role, port in zip(roles, ports, strict=True)),
            _edge("c", "result", "out", "in"),
            _edge("c", "result", "msg", "in"),
        ],
    }


def _run(diagram, verdicts):
    plan = compile_algorithm(diagram)
    assert plan.errors == [], plan.errors
    context = Context(extra={"verdicts": verdicts})
    values = execute(plan, CATALOG, context)
    outputs = collected(context).get("outputs") or []
    return values.get("c", "result"), outputs


GOOD = {"status": "good", "quality": 96.0, "message": "Good."}
SUSPECT = {"status": "suspect", "quality": 62.0, "message": "Some spikes."}
BAD = {"status": "bad", "quality": 10.0, "message": "Frozen."}


def test_worst_of_takes_the_most_severe_input():
    diagram = _verdicts({"block": "logic.worst"}, ["in", "in", "in"])
    result, _ = _run(diagram, {"pv": GOOD, "sp": BAD, "op": SUSPECT})
    assert (result.status, result.value) == ("bad", 10.0)
    assert "Frozen." in result.message
    # Inputs that cannot judge do not count; none judging is unknown, never ok.
    assert _run(diagram, {"pv": GOOD})[0].status == "ok"
    assert _run(diagram, {})[1][0]["status"] == "unknown"


def test_average_scores_and_bands():
    diagram = _verdicts({"block": "logic.average"}, ["in", "in"])
    result, _ = _run(diagram, {"pv": GOOD, "sp": SUSPECT})
    assert (result.value, result.status) == (79.0, "warning")
    strict = _verdicts(
        {"block": "logic.average", "parameters": {"warning_below": 95, "bad_below": 80}},
        ["in", "in"],
    )
    assert _run(strict, {"pv": GOOD, "sp": SUSPECT})[0].status == "bad"


def test_a_rule_overrides_only_when_triggered():
    rule = {
        "block": "logic.rule",
        "parameters": {"when": "warning_or_bad", "then": "unknown", "message": "PV not usable."},
    }
    diagram = _verdicts(rule, ["test", "value"])
    triggered, _ = _run(diagram, {"pv": SUSPECT, "sp": GOOD})
    assert (triggered.status, triggered.value, triggered.message) == (
        "unknown",
        None,
        "PV not usable.",
    )
    passed, _ = _run(diagram, {"pv": GOOD, "sp": BAD})
    assert (passed.status, passed.value) == ("bad", 10.0)


def test_message_outputs_say_when_they_fire():
    diagram = _verdicts({"block": "logic.worst"}, ["in"])
    fired = _run(diagram, {"pv": BAD})[1][1]
    assert (fired["kind"], fired["triggered"], fired["text"]) == ("message", True, "Call I&C.")
    assert _run(diagram, {"pv": SUSPECT})[1][1]["triggered"] is False


# On the plant: test, save, schedule and publish ------------------------------------------------


@pytest.fixture
def suite_fake():
    return make_fake(catalog=True)


@pytest.fixture
def rt(tmp_path, suite_fake):
    runtime = make_runtime(tmp_path, suite_fake)
    runtime.run_round()
    yield runtime
    runtime.shutdown()


@pytest.fixture
def api(rt, suite_fake):
    with client_for(rt, suite_fake) as test_client:
        yield test_client


def _save(api, diagram=PV_AND_VALVE, algorithm_id="pv_and_valve"):
    answer = api.put(
        f"/link/api/algorithms/{algorithm_id}",
        json={"algorithm_id": algorithm_id, "name": "PV and valve", "diagram": diagram},
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_editor_gets_the_palette(api):
    palette = api.get("/link/api/blocks").json()
    assert [item["library"] for item in palette["libraries"]] == [
        "input",
        "dq",
        "transform",
        "estimator",
        "stats",
        "cpm",
        "equipment",
        "model",
        "logic",
        "custom",
        "output",
    ]
    blocks = {item["block_id"]: item for item in palette["blocks"]}
    rule = blocks["logic.rule"]
    assert [port["port"] for port in rule["inputs"]] == ["test", "value"]
    assert {item["name"] for item in rule["parameters"]} == {"when", "then", "message"}
    one = api.get("/link/api/blocks/dq.frozen").json()
    assert "### Inputs" in one["markdown"]
    assert api.get("/link/api/blocks/dq.nope").status_code == 404


def test_shipped_algorithms_are_listed_and_read_only(api):
    listed = {item["algorithm_id"]: item for item in api.get("/link/api/algorithms").json()}
    assert set(BY_ID) <= set(listed)
    health = listed["flow_loop"]
    assert health["system"] and health["check"]["valid"] and health["docs"]["purpose"]
    # An id of 0.2 opens the algorithm that replaced it.
    assert api.get("/link/api/algorithms/valve").json()["algorithm_id"] == "flow_loop"
    body = {"algorithm_id": "flow_loop", "name": "Mine", "diagram": health["diagram"]}
    assert api.put("/link/api/algorithms/flow_loop", json=body).status_code == 409
    assert api.delete("/link/api/algorithms/flow_loop").status_code == 409
    markdown = api.get("/link/api/algorithms/level_loop/markdown").json()
    assert markdown["ref"] == "algorithm:linkcraft/level_loop"
    assert "## Blocks, in the order they run" in markdown["markdown"]


def test_the_check_and_an_invalid_save_say_what_is_wrong(api):
    broken = _without(_copy(), "pv_quality", "rule")
    report = api.post("/link/api/algorithms/check", json={"diagram": broken}).json()
    assert report["valid"] is False and report["node_errors"]["rule"]
    answer = api.put(
        "/link/api/algorithms/broken",
        json={"algorithm_id": "broken", "name": "Broken", "diagram": broken},
    )
    assert answer.status_code == 422
    tested = api.post("/link/api/algorithms/test", json={"diagram": broken}).json()
    assert tested == {"check": report}


def test_a_test_run_judges_a_frozen_pv_and_shows_every_wire(api):
    frozen = api.post(
        "/link/api/algorithms/test", json={"diagram": PV_AND_VALVE, "loop_id": "tic-104"}
    ).json()
    assert frozen["check"]["valid"] is True
    blocks = frozen["summary"]["blocks"]
    assert blocks["frozen"]["status"] == "bad"
    assert blocks["rule"]["status"] == "bad"
    assert blocks["rule"]["message"] == "PV data not usable."
    by_kind = {item["kind"]: item for item in frozen["summary"]["outputs"]}
    assert by_kind["message"]["triggered"] is True
    assert by_kind["result"]["key"] == "valve_and_pv"
    # What each wire carried, for the editor.
    trace = frozen["trace"]
    assert trace["rule"]["result"]["status"] == "bad"
    assert trace["pv"]["recorded"]["type"] == "series"

    healthy = api.post(
        "/link/api/algorithms/test", json={"diagram": PV_AND_VALVE, "loop_id": "fic-101"}
    ).json()
    assert healthy["summary"]["blocks"]["frozen"]["status"] == "ok"
    assert healthy["summary"]["blocks"]["rule"]["status"] in {"ok", "warning"}


def test_a_scheduled_algorithm_publishes_its_outputs(api, rt, suite_fake):
    saved = _save(api)
    assert saved["method_ids"] == ["stiction_screening", "op_saturation_fraction"]
    created = api.post(
        "/link/api/schedules",
        json={
            "name": "PV and valve",
            "profile_id": "pv_and_valve",
            "selector": {"mode": "list", "ids": ["tic-104", "fic-101"]},
            "cadence": "interval",
            "interval_minutes": 30,
            "lookback_minutes": 360,
        },
    )
    assert created.status_code == 201, created.text
    schedule = created.json()
    assert schedule["method_config"]["diagram"] == saved["diagram"]
    ran = rt.jobs.run_schedule_now(schedule["schedule_id"], ["tic-104", "fic-101"])
    for job_id in ran:
        done = rt.monitor.execute_job(job_id)
        assert done["status"] == "completed", done.get("error")
        assert done["summary"]["outputs"]
    results = suite_fake.links.results
    frozen = results[("linkcraft", "asset:tic-104", "out_valve_and_pv")]
    assert frozen["status"] == "alarm" and frozen["summary"] == "Valve and PV: PV data not usable."
    assert results[("linkcraft", "asset:fic-101", "out_valve_and_pv")]["status"] in {
        "ok",
        "warning",
    }
    # Recorded ports go to the historian under the asset, the algorithm and the output's name:
    # one series each, a verdict's status stays in the result.
    base = "app-linkcraft:tic-104.pv_and_valve"
    mine = sorted(item for item in suite_fake.derived if item.startswith(base))
    assert mine == [f"{base}.rule-if-then", f"{base}.stiction-screening"]
    assert "app-linkcraft:algorithm.pv_and_valve.version" in suite_fake.derived
    named = {item["id"]: item["name"] for item in suite_fake.signals}
    assert named[f"{base}.stiction-screening"] == "TIC-104 · PV and valve · Stiction screening"
    # In use: it cannot be deleted until its schedule goes.
    assert api.delete("/link/api/algorithms/pv_and_valve").status_code == 409
    api.delete(f"/link/api/schedules/{schedule['schedule_id']}")
    assert api.delete("/link/api/algorithms/pv_and_valve").status_code == 204
    assert api.get("/link/api/algorithms/pv_and_valve").status_code == 404


def test_link_retires_once_the_series_it_wrote_before_0_4(api, rt, suite_fake):
    from linkcraft.loops.suite import OLD_SERIES_MARK, retire_old_series

    _save(api)
    at = ["2026-10-20T00:00:00Z"]
    old = "app-linkcraft:tic-104.pv_and_valve"
    written = [
        "app-linkcraft:tic-104.health",
        "app-linkcraft:tic-104.status",  # a loop's status text
        f"{old}.rule.result",  # a port under its block id
        f"{old}.rule.result_status",  # a verdict's status code
        f"{old}.stiction.stiction_score",
        f"{old}.rule-if-then",  # already the new key: kept
        "app-linkcraft:sig.quality",
    ]
    rt.suite.put_series([{"signal": item, "t": at, "v": [1.0]} for item in written])
    assert retire_old_series(rt.suite, rt.presets, {"tic-104"}) == 5
    kept = {item["id"] for item in suite_fake.signals if item.get("app") == "linkcraft"}
    assert kept & set(written) == {f"{old}.rule-if-then", "app-linkcraft:sig.quality"}
    assert rt.presets.marked(OLD_SERIES_MARK) == "5"
    rt.suite.put_series([{"signal": "app-linkcraft:tic-104.status", "t": at, "v": [1.0]}])
    assert retire_old_series(rt.suite, rt.presets, {"tic-104"}) == 0  # once only


def test_a_protocol_saved_in_0_2_is_converted_at_start(tmp_path, suite_fake):
    first = make_runtime(tmp_path, suite_fake)
    first.presets.save_profile(
        profile_id="old_one",
        name="Old one",
        description="",
        method_config={"method_ids": ["error_metrics_basic", "op_saturation_fraction"]},
    )
    first.shutdown()
    again = make_runtime(tmp_path, suite_fake)
    try:
        config = again.presets.get_profile("old_one")["method_config"]
        assert config["diagram"]["version"] == 2
        assert compile_algorithm(config["diagram"]).errors == []
        assert config["method_ids"][-2:] == ["error_metrics_basic", "op_saturation_fraction"]
    finally:
        again.shutdown()


def test_an_algorithm_has_its_author_tags_version_and_group(rt, suite_fake):
    suite_fake.users["carla"] = {
        "name": "Carla Lima",
        "level": "editor",
        "apps": {"linkcraft": "editor"},
    }
    with client_for(rt, suite_fake, "engineer") as api:
        saved = _save(api)
        assert (saved["author"], saved["owner"], saved["version"]) == (
            "Process Engineer",
            "engineer",
            1,
        )
        assert saved["editable"] is True and saved["tags"] == [] and saved["group"] is None
        assert _save(api)["version"] == 2
        patched = api.patch(
            "/link/api/algorithms/pv_and_valve",
            json={
                "tags": ["fouling", " Fouling ", "control loop"],
                "group_id": "process-engineering",
            },
        ).json()
        assert patched["tags"] == ["fouling", "control loop"] and patched["version"] == 2
        assert patched["group"] == {"id": "process-engineering", "name": "Process engineering"}
        listed = {item["algorithm_id"]: item for item in api.get("/link/api/algorithms").json()}
        shipped = listed["flow_loop"]
        assert shipped["author"] == "PlantCraft" and shipped["tags"] == ["control loop"]
        assert shipped["editable"] is False and shipped["used_by"] >= 1
        assert listed["signal_quality"]["tags"] == ["data quality"]
        assert listed["unit_twin"]["tags"] == ["digital twin"]
        groups = api.get("/link/api/user-groups").json()
        assert {"id": "process-engineering", "name": "Process engineering"} in groups
        bad = api.patch("/link/api/algorithms/pv_and_valve", json={"group_id": "nobody"})
        assert bad.status_code == 422
    with client_for(rt, suite_fake, "carla") as other:
        assert other.get("/link/api/algorithms/pv_and_valve").json()["editable"] is False
        body = {"algorithm_id": "pv_and_valve", "name": "Mine", "diagram": PV_AND_VALVE}
        refused = other.put("/link/api/algorithms/pv_and_valve", json=body)
        assert refused.status_code == 403 and "Process engineering" in refused.json()["detail"]
        assert (
            other.patch("/link/api/algorithms/pv_and_valve", json={"tags": []}).status_code == 403
        )
        assert other.delete("/link/api/algorithms/pv_and_valve").status_code == 403
    with client_for(rt, suite_fake, "admin") as admin:
        freed = admin.patch("/link/api/algorithms/pv_and_valve", json={"group_id": ""}).json()
        assert freed["group"] is None
    rt._algorithm_groups = None
    with client_for(rt, suite_fake, "carla") as other:
        assert other.get("/link/api/algorithms/pv_and_valve").json()["editable"] is True


def test_twins_that_repeat_an_example_are_listed_and_removed_with_their_schedules(
    api, rt, suite_fake
):
    """An installation that ran Twin and the demo's examples had each model twice:
    Algorithms lists the copies from Twin and an admin removes them."""

    _save(api)
    _save(api, algorithm_id="twin_pv_and_valve")
    _save(api, algorithm_id="twin_alone")  # also named "PV and valve"
    created = api.post(
        "/link/api/schedules",
        json={
            "name": "Twin copy",
            "profile_id": "twin_pv_and_valve",
            "selector": {"mode": "list", "ids": ["tic-104"]},
            "cadence": "interval",
            "interval_minutes": 30,
            "lookback_minutes": 360,
        },
    )
    assert created.status_code == 201, created.text
    found = {item["algorithm_id"]: item for item in api.get("/link/api/algorithms/repeated").json()}
    assert set(found) == {"twin_pv_and_valve", "twin_alone"}
    assert found["twin_pv_and_valve"]["same_as"]["algorithm_id"] == "pv_and_valve"
    assert [item["name"] for item in found["twin_pv_and_valve"]["schedules"]] == ["Twin copy"]
    # Editors see the list; only an admin removes, and only what is still repeated.
    body = {"algorithm_ids": ["twin_pv_and_valve", "pv_and_valve"]}
    assert api.post("/link/api/algorithms/repeated/remove", json=body).status_code == 403
    with client_for(rt, suite_fake, "admin") as admin:
        answer = admin.post("/link/api/algorithms/repeated/remove", json=body)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"removed": ["twin_pv_and_valve"]}
    assert api.get("/link/api/algorithms/twin_pv_and_valve").status_code == 404
    assert api.get("/link/api/algorithms/pv_and_valve").status_code == 200
    assert not [s for s in rt.jobs.list_schedules() if s.get("profile_id") == "twin_pv_and_valve"]
    assert [item["algorithm_id"] for item in api.get("/link/api/algorithms/repeated").json()] == [
        "twin_alone"
    ]


def test_an_algorithm_says_where_it_runs(api):
    first = _save(api)
    assert first["compute"] == {"environment": "standard", "size": "small"}
    body = {
        "algorithm_id": "pv_and_valve",
        "name": "PV and valve",
        "diagram": PV_AND_VALVE,
        "compute": {"environment": "ml", "size": "large"},
    }
    saved = api.put("/link/api/algorithms/pv_and_valve", json=body).json()
    assert saved["compute"] == {"environment": "ml", "size": "large"}
    assert saved["version"] == first["version"] + 1
    assert api.get("/link/api/algorithms/pv_and_valve").json()["compute"]["size"] == "large"
    bad = {**body, "compute": {"environment": "ml", "size": "huge"}}
    assert api.put("/link/api/algorithms/pv_and_valve", json=bad).status_code == 422
    offer = api.get("/link/api/compute/offer").json()
    assert set(offer) >= {"suite", "environments", "sizes", "workers"}
