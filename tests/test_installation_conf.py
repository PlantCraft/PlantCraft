"""install.sh's installation file (deploy/installation.conf.example, docs/installation-file.md):
what it sets in .env, what it switches off, and that a file others may write is refused.

The functions are run by bash on their own, with install.sh's .env helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = SCRIPT.index(f"{name}() {{")
    end = SCRIPT.index("\n}\n", start) + 3
    return SCRIPT[start:end]


def _block() -> str:
    start = SCRIPT.index("# The installation file ---")
    end = SCRIPT.index("\n}\n", SCRIPT.index("apply_installation_conf() {")) + 3
    return SCRIPT[start:end]


HARNESS = "\n".join(
    [
        'log() { :; }; warn() { echo "WARNING: $*" >&2; }; die() { echo "ERROR: $*" >&2; exit 1; }',
        'SUITE_APPS=("linkcraft:A:/link/:1:key" "dashcraft:V:/dash/:2:key" "histcraft:H:/hist/:3:"'
        ' "alarmcraft:Al:/alarm/:4:key" "modelcraft:M:/model/:5:key" "doccraft:D:/doc/:6:key")',
        _function("env_get"),
        _function("env_set"),
        _function("app_field"),
        'app_ids() { local entry; for entry in "${SUITE_APPS[@]}"; do printf \'%s\\n\' "${entry%%:*}"; done; }',
        _function("version_key"),
        _function("suite_apps_setting"),
        _block(),
        'WITH_APPS=" "; ALL_APPS=0; WITH_DEMO=0; PUBLIC_DEMO=0; CONF_ENV=(); CONF_APPS=""; CONF_LOCKED=""',
        'INSTALLATION_CONF="$1"; DEV="$2"; ENV="$3"',
        "load_installation_conf",
        'apply_installation_conf "$ENV"',
        'echo "WITH_APPS=$WITH_APPS"; echo "DEMO=$WITH_DEMO/$PUBLIC_DEMO"',
    ]
)


def _run(tmp_path: Path, conf: str, *, dev: str = "1", env: str = "", mode: int = 0o644):
    conf_file = tmp_path / "installation.conf"
    conf_file.write_text(conf, encoding="utf-8")
    conf_file.chmod(mode)
    env_file = tmp_path / ".env"
    env_file.write_text(env, encoding="utf-8")
    done = subprocess.run(
        ["bash", "-c", HARNESS, "-", str(conf_file), dev, str(env_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    values = dict(line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line)
    return done, values


def test_the_file_decides_apps_policies_and_network(tmp_path):
    done, env = _run(
        tmp_path,
        "APPS=analytics, historian  # two apps\nWEB_APP_INSTALL=off\nLLM=off\nMACHINE=medium\n"
        "HTTPS_PORT=8443\nNETWORK_BASE=10.99\nTIMEZONE=America/Sao_Paulo\nLOCK_TIMEZONE=yes\n",
        env="COMPOSE_PROFILES=linkcraft,histcraft,modelcraft\nLINKCRAFT_VERSION=0.5.1\n",
    )
    assert done.returncode == 0, done.stderr
    assert "WITH_APPS= linkcraft histcraft " in done.stdout
    # Models was on in .env and is not in APPS: switched off.
    assert env["COMPOSE_PROFILES"] == "linkcraft,histcraft"
    assert "modelcraft is not in APPS" in done.stderr
    assert env["PLANTCRAFT_APPS"].startswith("linkcraft=/link/@0.5.1,histcraft=/hist/")
    assert env["PLANTCRAFT_APP_INSTALL"] == "off"
    assert env["PLANTCRAFT_LLM"] == "off"
    assert env["PLANTCRAFT_MACHINE"] == "medium"
    assert env["PLANTCRAFT_HTTPS_PORT"] == "8443"
    assert env["PLANTCRAFT_PLANT_SUBNET"] == "10.99.10.0/24"
    assert env["PLANTCRAFT_EGRESS_SUBNET"] == "10.99.16.0/24"
    assert env["PLANTCRAFT_PROXY_ADDRESS"] == "10.99.11.250"
    assert env["PLANTCRAFT_TIMEZONE_LOCKED"] == "true"
    locked = env["PLANTCRAFT_INSTALLATION_LOCKED"].split(",")
    assert {"COMPOSE_PROFILES", "PLANTCRAFT_LLM", "PLANTCRAFT_APP_INSTALL"} <= set(locked)
    assert len(env["PLANTCRAFT_INSTALLATION_CONF_SHA256"]) == 64


def test_llm_on_leaves_the_choice_to_the_administrator(tmp_path):
    done, env = _run(tmp_path, "LLM=on\nDEMO=public\n", env="PLANTCRAFT_LLM=off\n")
    assert done.returncode == 0, done.stderr
    assert env["PLANTCRAFT_LLM"] == ""
    assert "DEMO=1/1" in done.stdout


@pytest.mark.parametrize(
    "conf,message",
    [
        ("APPS=analytics,spreadsheet\n", "unknown app 'spreadsheet'"),
        ("LLM=maybe\n", "LLM is off or on"),
        ("NETWORK_BASE=10.1.2\n", "NETWORK_BASE is like 172.30"),
    ],
)
def test_a_wrong_value_stops_before_anything_changes(tmp_path, conf, message):
    done, env = _run(tmp_path, conf, env="A=1\n")
    assert done.returncode != 0 and message in done.stderr
    assert env == {"A": "1"}


def test_a_file_others_may_write_is_refused(tmp_path):
    done, _ = _run(tmp_path, "LLM=off\n", dev="0", mode=0o666)
    assert done.returncode != 0
    assert "must be owned by root and writable by root only" in done.stderr


@pytest.mark.skipif(os.geteuid() != 0, reason="needs a file owned by root")
def test_a_root_file_is_accepted(tmp_path):
    done, env = _run(tmp_path, "LLM=off\n", dev="0", mode=0o644)
    assert done.returncode == 0, done.stderr
    assert env["PLANTCRAFT_LLM"] == "off"


def test_preflight_reports_json_and_changes_nothing(tmp_path):
    done = subprocess.run(
        [
            str(ROOT / "deploy" / "preflight.sh"),
            "--json",
            "--prefix",
            str(tmp_path / "x"),
            "--apps",
            "analytics,historian",
            "--config",
            str(tmp_path / "none.conf"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    import json

    report = json.loads(done.stdout)
    names = {check["name"] for check in report["checks"]}
    assert {"Operating system", "CPUs", "Memory", "Disk free", "Docker Engine"} <= names
    assert report["apps"].split() == ["linkcraft", "histcraft"]
    assert done.returncode == (1 if report["fails"] else 0)
    assert not (tmp_path / "x").exists()


def test_the_wizard_writes_only_known_keys_and_values():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "wizard", ROOT / "deploy" / "wizard" / "wizard.py"
    )
    wizard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wizard)
    text = wizard.conf_text(
        {
            "APPS": "analytics,view",
            "WEB_APP_INSTALL": "off",
            "DEMO": "off",
            "MACHINE": "auto",
            "HTTPS_PORT": "443",
            "BIND_ADDRESS": "0.0.0.0",
            "NETWORK_BASE": "172.30",
            "LLM": "off",
            "LOCK_TIMEZONE": "no",
            "EXTRA": "ignored",
        }
    )
    assert "APPS=analytics,view\n" in text and "EXTRA" not in text
    with pytest.raises(ValueError):
        wizard.conf_text({"APPS": "analytics", "HTTPS_PORT": "443\nLLM=on"})
    with pytest.raises(ValueError):
        wizard.conf_text({"APPS": "spreadsheet"})
