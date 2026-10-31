"""A third-party multivariable controller, read only: health (A16) and constraint costs (A17)."""

from __future__ import annotations

import pandas as pd
import pytest

from linkcraft.engine.apc import Controller, Variable, assess, controllers, grid, step_for
from tests.apc_plant import CONTROLLER, add_apc
from tests.conftest import client_for

START = pd.Timestamp("2026-10-31 00:00")


def _frame(columns: dict[str, list[float]]) -> pd.DataFrame:
    index = pd.date_range(START, periods=len(next(iter(columns.values()))), freq="60s")
    return pd.DataFrame(columns, index=index)


def _controller(*variables: Variable) -> Controller:
    return Controller(
        id="c",
        name="C",
        parent_id=None,
        vendor="",
        cost_unit="$/h",
        signals={"on": "on"},
        variables=list(variables),
    )


def test_the_tree_groups_mvs_and_cvs_under_their_controller_by_type_path():
    assets = [
        {"id": "c", "name": "C", "kind": "apc", "type_path": ["apc"], "parent_id": "a"},
        {"id": "cv", "name": "b cv", "kind": "x", "type_path": ["apc_variable", "apc_cv"],
         "parent_id": "c", "attributes": {"limit_band": "0.5"}},
        {"id": "mv", "name": "z mv", "kind": "apc_mv", "parent_id": "c"},
        {"id": "stray", "name": "MV elsewhere", "kind": "apc_mv", "parent_id": "nowhere"},
        {"id": "loop", "name": "Loop", "kind": "loop", "type_path": ["loop"], "parent_id": "c"},
    ]  # fmt: skip
    (found,) = controllers(assets)
    assert [(item.id, item.kind) for item in found.variables] == [("mv", "mv"), ("cv", "cv")]
    assert found.variables[1].limit_band == 0.5 and found.variables[0].limit_band is None


def test_the_grid_holds_each_signal_at_its_last_sample():
    values = pd.Series(
        [1.0, 3.0], index=[START - pd.Timedelta(hours=1), START + pd.Timedelta(minutes=2)]
    )
    frame = grid(
        {"x": values, "empty": pd.Series(dtype=float)}, START, START + pd.Timedelta(minutes=4), 60
    )
    assert frame["x"].tolist() == [1.0, 1.0, 3.0, 3.0]
    assert frame["empty"].isna().all()
    assert step_for(3600) == 60 and step_for(31 * 86400) == 720  # fmt: skip


def test_on_in_service_and_at_a_limit_count_only_the_time_that_matters():
    mv = Variable("mv", "MV", "mv", {"value": "v", "lo": "lo", "hi": "hi", "status": "s"})
    cv = Variable("cv", "CV", "cv", {"value": "cv", "lo": "clo"}, limit_band=0.5)
    frame = _frame(
        {
            "on": [0, 1, 1, 1, 1, float("nan")],
            # At its high limit (within 1 % of the range) at points 1 and 2, out of service at 4.
            "v": [100, 99.5, 99.2, 50, 99.9, 99.9],
            "lo": [0] * 6,
            "hi": [100] * 6,
            "s": [1, 1, 1, 1, 0, 1],
            # Only a low limit: within its own band 0.5 at points 3 and 4.
            "cv": [5, 9, 9, 5.4, 5.2, 5.2],
            "clo": [5] * 6,
        }
    )
    row = assess(_controller(mv, cv), frame, 60)
    summary = row["summary"]
    # Known 5 points, on at 4 of them.
    assert summary["on_pct"] == 80.0 and summary["on_now"] is False
    variables = {item["id"]: item for item in row["variables"]}
    assert variables["mv"]["in_service_pct"] == 75.0
    # In service and on at points 1, 2, 3: at its high limit at 1 and 2.
    assert variables["mv"]["at_limit_pct"] == pytest.approx(66.7)
    assert variables["mv"]["at_hi_pct"] == pytest.approx(66.7) and variables["mv"]["at_lo_pct"] == 0
    assert variables["cv"]["at_limit_pct"] == 50.0 and variables["cv"]["at"] == "lo"
    assert summary["mv_in_service_pct"] == 75.0 and summary["state"] == "warning"
    # No shadow price: the constraints are ranked by their time, then by name.
    sides = [(item["variable_id"], item["side"], item["hours"]) for item in row["constraints"]]
    assert sides == [("cv", "lo", round(2 / 60, 2)), ("mv", "hi", round(2 / 60, 2))]
    assert all(item["shadow_price"] is None for item in row["constraints"])


def test_the_target_decides_the_limit_and_the_shadow_price_prices_it():
    cv = Variable(
        "cv", "CV", "cv", {"value": "v", "target": "t", "lo": "lo", "hi": "hi", "shadow_price": "p"}
    )
    frame = _frame(
        {
            "on": [1, 1, 1, 1],
            # The value is far from the limit; the target sits on it.
            "v": [15, 15, 15, 15],
            "t": [20, 20, 15, 20],
            "lo": [10] * 4,
            "hi": [20] * 4,
            "p": [-4, -6, 0, -5],
        }
    )
    (constraint,) = assess(_controller(cv), frame, 60)["constraints"]
    assert constraint["side"] == "hi" and constraint["active_now"] is True
    assert constraint["shadow_price"] == 5.0
    assert constraint["worth_1pct"] == pytest.approx(5.0 * 0.01 * 10)
    assert constraint["share_pct"] == 75.0


def test_a_controller_with_no_on_signal_reads_as_unknown():
    row = assess(_controller(), _frame({"x": [1, 2]}), 60)
    assert row["summary"]["on_pct"] is None and row["summary"]["state"] is None


@pytest.fixture
def apc_client(runtime, fake):
    add_apc(fake)
    with client_for(runtime, fake) as test_client:
        yield test_client


def test_the_api_lists_the_controller_with_its_health(apc_client):
    answer = apc_client.get("/link/api/apc", params={"days": 0.25})
    assert answer.status_code == 200, answer.text
    (row,) = answer.json()["controllers"]
    summary = row["summary"]
    assert row["id"] == CONTROLLER and row["cost_unit"] == "$/h" and "variables" not in row
    assert summary["on_pct"] == pytest.approx(75.0, abs=0.5)
    assert (summary["mvs"], summary["mvs_in_service"], summary["cvs"]) == (2, 1, 2)
    assert summary["mv_in_service_pct"] == pytest.approx(75.0, abs=0.5)
    assert summary["cvs_at_limit"] == 1 and summary["state"] == "warning"
    # The constraint worth most first: MV-1 at its high limit, then CV-1.
    assert [(item["name"], item["side"]) for item in row["constraints"]] == [
        ("Furnace duty", "hi"),
        ("Column dP", "hi"),
    ]
    assert row["constraints"][0]["worth_1pct"] == pytest.approx(2.0)
    assert row["constraints"][1]["worth_1pct"] == pytest.approx(0.5)


def test_one_controller_carries_its_variables(apc_client):
    answer = apc_client.get(f"/link/api/apc/{CONTROLLER}", params={"days": 0.25})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    variables = {item["name"]: item for item in body["variables"]}
    assert variables["Feed rate"]["in_service"] is False
    assert variables["Furnace duty"]["at"] == "hi" and variables["Furnace duty"]["hi"] == 100.0
    assert variables["Outlet temperature"]["at"] is None
    assert apc_client.get("/link/api/apc/nothing").status_code == 404


def test_no_controller_is_an_empty_list(client):
    assert client.get("/link/api/apc").json() == {"since": None, "until": None, "controllers": []}


def test_the_widget_names_each_controller_and_its_costliest_limit(apc_client):
    answer = apc_client.get("/link/api/widgets/apc-health")
    assert answer.status_code == 200, answer.text
    (item,) = answer.json()["items"]
    assert item["label"] == "Crude preheat APC" and item["state"] == "warning"
    assert "MVs in service 1/2" in item["detail"] and "CVs at a limit 1/2" in item["detail"]
    assert "Furnace duty at its high limit: 2 $/h for 1% more" in item["detail"]
    assert item["href"].endswith(f"/apc/{CONTROLLER}")


def test_the_weekly_report_has_the_controllers_and_their_costliest_limits(apc_client):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    from linkcraft.report.weekly import _apc_section, _styles

    rows = apc_client.get(f"/link/api/apc/{CONTROLLER}", params={"days": 0.25}).json()
    texts = []
    for flowable in _apc_section([rows], A4[0] - 32 * mm, _styles()):
        cells = [cell for line in flowable._cellvalues for cell in line] if isinstance(flowable, Table) else [flowable]  # fmt: skip
        texts += [cell.text for cell in cells if isinstance(cell, Paragraph)]
    joined = "\n".join(texts)
    assert (
        "Multivariable controllers" in joined and "The active limits that cost the most" in joined
    )
    assert "75% of the time (1/2 now)" in joined
    assert joined.index("Furnace duty") < joined.index("Column dP")
    assert "<b>2 $/h</b>" in joined and "5 $/h per unit" in joined
    pdf = apc_client.get("/link/api/reports/weekly.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
