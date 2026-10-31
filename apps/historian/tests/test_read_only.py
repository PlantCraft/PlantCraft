"""Historian never writes to a plant server (AGENTS.md, "Read-only on plant systems").

The OPC UA client may only Read, Browse and look up namespaces. These names are
the asyncua calls (and OPC UA services) that change a server; none may appear in
the code, comments aside.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITES = re.compile(
    r"\b(write_value|write_attribute|write_values|set_value|set_attribute|write_params|"
    r"call_method|call_methods|history_update|HistoryUpdate|add_nodes|delete_nodes|"
    r"add_references|delete_references|add_variable|add_object|add_method|add_folder|"
    r"WriteRequest|CallRequest|create_subscription|register_nodes)\b"
)


def _code_without_comments(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            node.value.value = ""  # docstrings
    return ast.unparse(tree)


def test_no_write_service_in_histcraft():
    offenders = []
    for path in (ROOT / "src" / "histcraft").rglob("*.py"):
        for match in WRITES.finditer(_code_without_comments(path)):
            offenders.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
    assert not offenders, "\n".join(offenders)


def test_the_check_finds_a_write():
    assert WRITES.search("await node.write_value(1.0)")


def test_the_gateway_runs_only_inputs_that_read():
    """The gateway's configuration (collector/gateway.py) names only reading inputs and one
    output, to the collector: no Telegraf plugin that writes to a plant system."""

    source = (ROOT / "src" / "histcraft" / "collector" / "gateway.py").read_text(encoding="utf-8")
    plugins = set(re.findall(r"\[\[(inputs|outputs)\.([a-z0-9_]+)\]\]", source))
    plugins |= {("inputs", name) for name in re.findall(r'"(?:mqtt|modbus|sql)": "(\w+)"', source)}
    assert {name for kind, name in plugins if kind == "outputs"} == {"influxdb_v2"}
    assert {name for kind, name in plugins if kind == "inputs"} <= {
        "internal",
        "mqtt_consumer",
        "modbus",
        "sql",
    }
