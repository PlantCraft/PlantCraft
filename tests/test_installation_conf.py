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
        "ASSISTANT_ACCESS=off\nNOTEBOOKS=on\nHTTPS_PORT=8443\nNETWORK_BASE=10.99\nTIMEZONE=America/Sao_Paulo\nLOCK_TIMEZONE=yes\n",
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
    assert env["PLANTCRAFT_MCP"] == "false" and env["PLANTCRAFT_NOTEBOOKS"] == "true"
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


def test_preflight_ignore_turns_that_failure_into_a_warning(tmp_path):
    import json

    def run(*extra):
        done = subprocess.run(
            [
                str(ROOT / "deploy" / "preflight.sh"),
                "--json",
                "--prefix",
                str(tmp_path),
                "--config",
                str(tmp_path / "none.conf"),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return json.loads(done.stdout)

    plain = run()
    failing = [check["id"] for check in plain["checks"] if check["state"] == "FAIL"]
    assert all(check["id"] for check in plain["checks"])
    if not failing:
        pytest.skip("nothing fails on this machine")
    ignored = run("--ignore", ",".join(failing))
    assert ignored["fails"] == 0
    assert all("Ignored on purpose" in c["fix"] for c in ignored["checks"] if c["id"] in failing)


def test_max_parallel_runs_caps_every_executor(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PLANTCRAFT_MAX_PARALLEL_RUNS=2\nLINKCRAFT_EXECUTOR_SLOTS=8\nMODELCRAFT_RUN_WORKERS=1\n"
    )
    script = "\n".join(
        [
            "log() { :; }",
            _function("env_get"),
            _function("env_set"),
            _function("cap_parallel_runs"),
            'cap_parallel_runs "$1"',
        ]
    )
    subprocess.run(["bash", "-c", script, "-", str(env_file)], check=True)
    values = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    # 8 and the default 4... capped at 2; the default 2 of Models' executor stays; 1 stays.
    assert values["LINKCRAFT_EXECUTOR_SLOTS"] == "2"
    assert values["MODELCRAFT_RUN_WORKERS"] == "1"
    assert "MODELCRAFT_EXECUTOR_SLOTS" not in values


def _wizard_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "wizard", ROOT / "deploy" / "wizard" / "wizard.py"
    )
    wizard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wizard)
    return wizard


def test_the_wizard_says_first_when_its_folder_is_not_a_release_bundle(tmp_path):
    wizard = _wizard_module()
    (tmp_path / "install.sh").write_text("#!/bin/sh\n")
    preflight = tmp_path / "preflight.sh"
    preflight.write_text('#!/bin/sh\necho \'{"checks": [], "fails": 0, "warnings": 0}\'\n')
    preflight.chmod(0o755)
    assert "SHA256SUMS" in wizard.bundle_problem(tmp_path)

    # --apply: install.sh would refuse this folder, so the requirements stop here, not at the end.
    applying = wizard.Wizard(True, tmp_path / "installation.conf", bundle=tmp_path)
    report = applying.check("analytics")
    assert report["checks"][0]["id"] == "release-bundle"
    assert report["checks"][0]["state"] == "FAIL" and report["fails"] == 1
    # Without --apply the wizard only writes the file: a warning.
    writing = wizard.Wizard(False, tmp_path / "installation.conf", bundle=tmp_path)
    assert writing.check("analytics")["checks"][0]["state"] == "WARN"

    (tmp_path / "SHA256SUMS").write_text("")
    assert wizard.bundle_problem(tmp_path) == ""
    complete = wizard.Wizard(True, tmp_path / "installation.conf", bundle=tmp_path)
    assert complete.check("analytics")["checks"][0]["state"] == "PASS"


def test_the_wizard_starts_from_the_file_already_there(tmp_path):
    wizard = _wizard_module()
    conf = tmp_path / "installation.conf"
    conf.write_text("APPS=analytics, historian  # two\nMACHINE=small\nLLM=maybe\nOTHER=1\n")
    # Unknown keys and values outside the wizard's own rules are left out.
    assert wizard.read_conf(conf) == {"APPS": "analytics,historian", "MACHINE": "small"}
    assert wizard.read_conf(tmp_path / "none.conf") == {}


def test_check_json_reports_the_apps_this_run_would_install(tmp_path):
    import json

    conf = tmp_path / "installation.conf"
    conf.write_text("APPS=analytics,historian\n")
    conf.chmod(0o644)
    common = ["--check", "--json", "--dev", "--prefix", str(tmp_path / "p")]
    done = subprocess.run(
        [str(ROOT / "deploy" / "install.sh"), *common, "--config", str(conf)],
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(done.stdout)
    assert report["apps"].split() == ["linkcraft", "histcraft"]
    # Without a file: Analytics (on by default) and the --with-<app> ones, not every app.
    if Path("/etc/plantcraft/installation.conf").exists():
        pytest.skip("this host has an installation file")
    done = subprocess.run(
        [str(ROOT / "deploy" / "install.sh"), *common, "--with-alarmcraft"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(done.stdout)["apps"].split() == ["linkcraft", "alarmcraft"]


def test_purge_keeps_the_images_another_installation_uses(tmp_path):
    """Two installations on one Docker (a test and a production one): purging one leaves the
    images the other's containers were created from (F2, 2026-10-31)."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    removed = tmp_path / "removed"
    fake = bin_dir / "docker"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = ps ]; then\n'
        "  printf 'test|processcraft:0.5.1\\ntest|histcraft:0.5.1\\nprod|processcraft:0.5.1\\n"
        "prod|postgres:17.11-trixie\\n|simcraft:0.5.1\\n'\n"
        f'elif [ "$1" = image ]; then echo "$3" >> {removed}; fi\n'
    )
    fake.chmod(0o755)
    script = "\n".join([_function("purge_images"), 'purge_images "$1"'])
    done = subprocess.run(
        ["bash", "-c", script, "-", "test"],
        input="histcraft:0.5.1\npostgres:17.11-trixie\nprocesscraft:0.5.1\nsimcraft:0.5.1\n",
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    # prod's containers use processcraft and postgres; a lone container (no project) uses simcraft.
    assert done.stdout.split() == ["postgres:17.11-trixie", "processcraft:0.5.1", "simcraft:0.5.1"]
    assert removed.read_text().split() == ["histcraft:0.5.1"]


def test_show_config_exits_1_when_env_differs_from_the_file(tmp_path):
    import hashlib

    conf = tmp_path / "installation.conf"
    conf.write_text("LLM=off\n")
    digest = hashlib.sha256(conf.read_bytes()).hexdigest()
    script = "\n".join(
        [
            'log() { :; }; warn() { :; }; die() { echo "$*" >&2; exit 9; }',
            _function("env_get"),
            _function("do_show_config"),
            'INSTALLATION_CONF="$1"; PREFIX="$2"; CONF_ENV=("PLANTCRAFT_LLM=off"); CONF_APPS=""',
            "do_show_config",
        ]
    )

    def run(env: str) -> int:
        (tmp_path / ".env").write_text(env)
        return subprocess.run(
            ["bash", "-c", script, "-", str(conf), str(tmp_path)], capture_output=True, check=False
        ).returncode

    applied = f"PLANTCRAFT_INSTALLATION_CONF_SHA256={digest}\n"
    assert run(applied + "PLANTCRAFT_LLM=off\n") == 0
    assert run(applied + "PLANTCRAFT_LLM=\n") == 1  # edited by hand
    assert run("PLANTCRAFT_LLM=off\n") == 1  # never applied


def test_preflight_in_wsl_refuses_only_docker_desktops_docker():
    """P9: Rancher Desktop's Linux docker reaches WSL through Windows' PATH (/mnt/c/...) and works
    with its WSL integration; Docker Desktop's, found the same way, is refused."""

    text = (ROOT / "deploy" / "preflight.sh").read_text()
    start = text.index('if [ "$wsl" = 1 ] && [[ "$(command -v docker')
    condition = text[start : text.index("; then", start)].removeprefix("if ")
    script = (
        "wsl=1\n"
        'docker_path="$1"\n'
        'command() { echo "$docker_path"; }\n'
        f"if {condition}; then echo refused; else echo accepted; fi\n"
    )

    def verdict(path: str) -> str:
        done = subprocess.run(["bash", "-c", script, "x", path], capture_output=True, text=True)
        return done.stdout.strip()

    assert verdict("/mnt/c/Program Files/Docker/Docker/resources/bin/docker") == "refused"
    assert verdict("/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe") == "refused"
    rancher = "/mnt/c/Users/me/AppData/Local/Programs/Rancher Desktop/resources/resources/linux/bin/docker"
    assert verdict(rancher) == "accepted"
    assert verdict("/usr/bin/docker") == "accepted"
