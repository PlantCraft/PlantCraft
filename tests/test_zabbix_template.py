"""deploy/monitoring/zabbix: PlantCraft's official Zabbix template reads metrics.json, so every
field it reads must be one the installer writes (plantcraft.apps.installer, host_usage), its
UUIDs must be unique, and the bundle must carry it (docs/operations.md, section 4)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "monitoring" / "zabbix" / "plantcraft_zabbix_agent.yaml"


def test_the_template_reads_only_fields_the_installer_writes():
    text = TEMPLATE.read_text()
    installer = (ROOT / "plantcraft" / "apps" / "installer.py").read_text()
    host = (ROOT / "plantcraft" / "apps" / "host_usage.py").read_text()
    assert 'vfs.file.contents["{$PLANTCRAFT.DIR}/data/installer/status/metrics.json"]' in text
    assert '"metrics.json"' in installer
    fields = re.findall(r"- \$\.(host|disk)\.(\w+)", text)
    assert {f for _, f in fields} >= {"cpu_pct", "mem_pct", "load_1m", "free_pct"}
    for part, field in fields:
        assert f'"{field}"' in (host if part == "host" else installer), field
    service = re.findall(
        r"\$\.services\[\?\(@\.service=='\{#SERVICE\}'\)\]\.(\w+)\.first\(\)", text
    )
    assert set(service) >= {"state", "health", "restarts", "cpu_load_pct", "mem_pct"}
    for field in service:
        assert f'"{field}"' in installer, field
    assert '"at": now()' in installer and "JSON.parse(value).at" in text


def test_the_template_is_a_zabbix_7_export_with_unique_uuids():
    text = TEMPLATE.read_text()
    assert "version: '7.0'" in text and "template: PlantCraft by Zabbix agent" in text
    uuids = re.findall(r"uuid: (\S+)", text)
    assert len(uuids) > 20 and len(set(uuids)) == len(uuids)
    assert all(re.fullmatch(r"[0-9a-f]{32}", u) for u in uuids)
    # Every trigger names an item of this template.
    for key in re.findall(r"\(/PlantCraft by Zabbix agent/([^,)]+)", text):
        assert f"key: {key}" in text or f"key: '{key}'" in text, key
    # The thresholds are PlantCraft's own load alerts (plantcraft.watch).
    for macro, value in (("CPU.WARN", "80"), ("CPU.CRIT", "95"), ("DISK.FREE.MIN", "10")):
        assert re.search(
            rf"macro: '\{{\$PLANTCRAFT\.{re.escape(macro)}\}}'\n\s+value: '{value}'", text
        )


def test_the_template_parses_as_yaml():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(TEMPLATE.read_text())
    (template,) = doc["zabbix_export"]["templates"]
    assert template["discovery_rules"][0]["lld_macro_paths"] == [
        {"lld_macro": "{#SERVICE}", "path": "$.service"}
    ]


def test_the_bundle_carries_the_template():
    bundle = (ROOT / "deploy" / "bundle.sh").read_text()
    assert "deploy/monitoring/zabbix/plantcraft_zabbix_agent.yaml" in bundle
