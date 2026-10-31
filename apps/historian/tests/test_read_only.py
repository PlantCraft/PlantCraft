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
    r"WriteRequest|CallRequest|register_nodes|create_monitored_items|modify_monitored_items|"
    r"set_monitoring_mode|set_publishing_mode|subscribe_events)\b"
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


def test_only_an_opted_in_source_subscribes_and_only_to_values():
    """Subscriptions (H4, the maintainer's decision of 2026-11-01): only the collector's OPC UA
    reader creates one, monitors the Value attribute only, and the collector asks for it only
    for a source whose ``subscribe`` option is on (off by default)."""

    found = {}
    for path in (ROOT / "src" / "histcraft").rglob("*.py"):
        code = _code_without_comments(path)
        for name in ("create_subscription", "subscribe_data_change"):
            if name in code:
                found.setdefault(name, set()).add(path.relative_to(ROOT).as_posix())
    assert found == {
        "create_subscription": {"src/histcraft/collector/opcua.py"},
        "subscribe_data_change": {"src/histcraft/collector/opcua.py"},
    }
    reader = _code_without_comments(ROOT / "src" / "histcraft" / "collector" / "opcua.py")
    assert reader.count("create_subscription(") == 1 and "attr=" not in reader
    service = (ROOT / "src" / "histcraft" / "collector" / "service.py").read_text(encoding="utf-8")
    assert 'options.get("subscribe") and hasattr(reader, "subscribe")' in service
    from histcraft.catalog.models import SourceIn

    source = SourceIn(id="plant", name="Plant", endpoint="opc.tcp://plant:4840")
    assert source.options["subscribe"] is False


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
