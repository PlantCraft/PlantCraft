"""Reading Modelica text: classes and their spans, the policy, and the diagram's edits."""

from __future__ import annotations

import pytest

from modelcraft.modelica import edit
from modelcraft.modelica.source import find, flatten, outline, policy

PACKAGE = """within;
package Plant "A plant"
  model Pump "A pump"
    parameter Real k = 1 "Gain (with model in a string)";
    // model Fake in a comment
    Real y;
  equation
    y = k;
  end Pump;
  type Speed = Real(unit = "rpm") "A short class";
  partial block Base end Base;
  expandable connector Bus end Bus;
end Plant;
"""


def test_outline_finds_nested_short_and_partial_classes_but_not_strings_or_comments():
    classes = {item.name: item for item in flatten(outline(PACKAGE))}
    assert set(classes) == {"Plant", "Plant.Pump", "Plant.Speed", "Plant.Base", "Plant.Bus"}
    assert classes["Plant.Pump"].comment == "A pump" and classes["Plant.Pump"].line == 3
    assert classes["Plant.Speed"].short_class and classes["Plant.Speed"].restriction == "type"
    assert (
        classes["Plant.Base"].partial and classes["Plant.Bus"].restriction == "expandable connector"
    )
    assert PACKAGE[classes["Plant.Pump"].start : classes["Plant.Pump"].end].endswith("end Pump;")


def test_within_names_the_package():
    assert find("within A.B;\nmodel C end C;", "A.B.C") is not None


@pytest.mark.parametrize(
    "line",
    [
        'Modelica.Utilities.System.command("rm -rf /");',
        'Modelica.Utilities.Files.remove("x");',
        "import U = Modelica.Utilities;",
        "import Modelica.Utilities.*;",
        'import S = Modelica.Utilities.System; S.command("ls");',
        'import M = Modelica; M.Utilities.Files.list("/");',
        'Utilities.Internal.FileSystem.rmdir("x");',
        'function f external "C" g(); end f;',
    ],
)
def test_policy_refuses_shell_files_and_c_code(line):
    assert policy(f"model A\nalgorithm\n  {line}\nend A;\n")


def test_policy_lets_ordinary_models_and_strings_through():
    text = (
        PACKAGE
        + 'model B\n  String s = "Modelica.Utilities.System.command";\n  Real n = Modelica.Utilities.Strings.length(s);\nend B;\n'
    )
    assert policy(text) == []
    assert policy('function f external "C"; end f;', allow_external=True) == []


def test_add_connect_move_and_parameters_keep_the_class_valid_text():
    text = "model M\n  annotation(Diagram(coordinateSystem(extent={{-100,-100},{100,100}})));\nend M;\n"
    text = edit.add_component(
        text, "M", "Modelica.Blocks.Sources.Step", "step", [[-80, -10], [-60, 10]]
    )
    text = edit.add_component(
        text, "M", "Modelica.Blocks.Continuous.FirstOrder", "lag", [[0, -10], [20, 10]]
    )
    text = edit.connect(text, "M", "step.y", "lag.u", [[-59, 0], [-2, 0]])
    text = edit.move(text, "M", "lag", [[10, -10], [30, 10]], rotation=90)
    text = edit.set_modifiers(text, "M", "lag", {"T": "2", "k": "1.5"})
    assert text.index("Step step") < text.index("equation") < text.index("connect(step.y, lag.u)")
    assert text.index("connect(") < text.index("annotation(Diagram")
    assert (
        "FirstOrder lag(T=2, k=1.5) annotation(Placement(transformation(extent={{10,-10},{30,10}}, rotation=90)));"
        in text
    )
    with pytest.raises(edit.EditError):
        edit.add_component(text, "M", "Modelica.Blocks.Math.Gain", "lag", [[0, 0], [1, 1]])
    with pytest.raises(edit.EditError):
        edit.connect(text, "M", "step.y", "lag.u", [])
    text = edit.delete_connection(text, "M", "lag.u", "step.y")
    assert "connect" not in text
    text = edit.delete_component(text, "M", "step")
    assert "Step" not in text and text.rstrip().endswith("end M;")


def test_edits_never_write_what_they_were_not_given():
    text = "model M\n  Real x;\nend M;\n"
    for bad in ('2); os.system("x', "a;b"):
        with pytest.raises(edit.EditError):
            edit.set_modifiers(text, "M", "x", {"start": bad})
    with pytest.raises(edit.EditError):
        edit.add_component(text, "M", "Modelica.Blocks;Bad", "g", [[0, 0], [1, 1]])
    with pytest.raises(edit.EditError):
        edit.move(text, "M", "x", [[0, 0], [1, "a"]])
    with pytest.raises(edit.EditError):
        edit.add_component(text, "Other", "A.B", "g", [[0, 0], [1, 1]])


def test_iconTransformation_survives_a_move():
    text = "block B\n  Modelica.Blocks.Interfaces.RealInput u annotation(Placement(transformation(extent={{-1,-1},{1,1}}), iconTransformation(extent={{-2,-2},{2,2}})));\nend B;\n"
    moved = edit.move(text, "B", "u", [[5, 5], [7, 7]])
    assert "extent={{5,5},{7,7}}" in moved and "iconTransformation(extent={{-2,-2},{2,2}})" in moved


def test_unique_names_follow_the_class_name():
    text = "model M\n  Modelica.Blocks.Math.Gain gain;\nend M;\n"
    assert edit.unique_name(text, "M", "Gain") == "gain1"
    assert edit.unique_name(text, "M", "PID") == "pID"


SYSTEM = """model Plant "A system of connected components"
  annotation(experiment(StartTime = 0, StopTime = 10, Interval = 0.01, Tolerance = 1e-06),
    Diagram(coordinateSystem(extent = {{-100, -100}, {100, 100}})));
end Plant;
"""


def test_a_system_is_built_from_the_projects_own_components():
    """blocks of one's own, connected into a plant and run together. A
    project class goes into a system's diagram as a library class does, before the system's
    annotation, and its connectors connect."""

    text = edit.add_component(SYSTEM, "Plant", "Lag", "lag1", [[-10, -10], [10, 10]], 0)
    text = edit.add_component(
        text, "Plant", "Modelica.Blocks.Sources.Step", "step1", [[-60, -10], [-40, 10]], 0
    )
    text = edit.connect(text, "Plant", "step1.y", "lag1.u", [[-39, 0], [-12, 0]])
    (plant,) = outline(text)
    assert plant.name == "Plant" and policy(text) == []
    body = text[: text.index("annotation(experiment")]
    assert "Lag lag1 annotation(Placement" in body
    assert "connect(step1.y, lag1.u)" in body
    assert text.rstrip().endswith("end Plant;")
