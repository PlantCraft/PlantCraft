"""deploy/compose.yaml follows the suite table of docs/app-standard.md (section 7).

The table assigns each app's id, prefix, port and uid once; the compose file, the SDK's
``app_manifest.SUITE`` (what ``plantcraft-app check`` enforces) and this repository's
configuration must not drift from it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from plantcraft_sdk.app_manifest import SERVICES, SUITE

# uvicorn[standard] (the server extra) brings PyYAML; test_isolation.py reads it the same way.
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]


def _table() -> dict[str, dict]:
    """``{service name: {"id", "prefix", "port", "uid"}}`` from the suite table."""

    text = (ROOT / "docs" / "app-standard.md").read_text(encoding="utf-8")
    section = text.split("**The suite table**", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5 or not cells[4].isdigit():
            continue
        name, app_id, prefix, port, uid = cells
        app_id = app_id.strip("`")
        key = app_id or name.lower()
        rows[key] = {
            "name": re.sub(r"\s*\(.*\)$", "", name),
            "prefix": prefix.strip("`") if prefix.startswith("`") else None,
            "port": int(port) if port.isdigit() else None,
            "uid": int(uid),
        }
    return rows


def _compose() -> dict:
    return yaml.safe_load((ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8"))


def _ports(service: dict) -> set[int]:
    """Ports a service listens on inside its container: published targets and healthchecks."""

    found = set()
    for item in service.get("ports") or []:
        found.add(int(str(item).rsplit(":", 1)[-1].split("/")[0]))
    probe = " ".join(str(part) for part in (service.get("healthcheck") or {}).get("test") or [])
    found.update(int(port) for port in re.findall(r"127\.0\.0\.1:(\d+)", probe))
    for part in service.get("command") or []:
        found.update(int(port) for port in re.findall(r"opc\.tcp://[^:/]+:(\d+)", str(part)))
    return found


def test_the_table_is_complete_and_unique():
    table = _table()
    assert {"processcraft", "linkcraft", "proxy", "simcraft", "installer"} <= set(table)
    uids = [row["uid"] for row in table.values()]
    ports = [row["port"] for row in table.values() if row["port"]]
    prefixes = [row["prefix"] for row in table.values() if row["prefix"]]
    assert len(set(uids)) == len(uids) and len(set(ports)) == len(ports)
    assert len(set(prefixes)) == len(prefixes)


def test_compose_users_and_ports_match_the_table():
    table = _table()
    services = _compose()["services"]
    checked = []
    for name, service in services.items():
        # An app's own database (`histcraft-db`), collector (`histcraft-collector`), gateway
        # (`histcraft-gateway`) or job runner runs as that app's user,
        # with no port of the table.
        owner = re.sub(r"-(db|runner|collector|gateway)$", "", name)
        # An app's executor on the local compute worker shares the compute gateway's user.
        owner = "compute" if name.endswith("-executor") else owner
        row = table.get(name) or (table.get(owner) if owner != name else None)
        assert row is not None, f"compose service {name} is not in the suite table"
        assert service.get("user") == f"{row['uid']}:{row['uid']}", name
        if row["port"] is not None and owner == name:
            assert row["port"] in _ports(service), (name, row["port"], _ports(service))
        checked.append(name)
    assert {"processcraft", "proxy"} <= set(checked)


def test_the_sdk_enforces_the_same_table():
    table = _table()
    for app_id, row in SUITE.items():
        assert table[app_id]["name"] == row.name, app_id
        assert table[app_id]["prefix"] == row.prefix, app_id
        assert (table[app_id]["port"], table[app_id]["uid"]) == (row.port, row.uid), app_id
    for name, (port, uid) in SERVICES.items():
        assert (table[name]["port"], table[name]["uid"]) == (port, uid), name
    assert set(table) == set(SUITE) | set(SERVICES)


def test_the_installer_uses_the_same_table():
    from plantcraft.apps.package import SUITE as PACKAGE_SUITE

    table = _table()
    for app_id, (prefix, port, uid) in PACKAGE_SUITE.items():
        assert (table[app_id]["prefix"], table[app_id]["port"], table[app_id]["uid"]) == (
            prefix,
            port,
            uid,
        ), app_id
