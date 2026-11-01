"""The public demo visitor's password lives in data/public-demo-password (mode 600), never in .env
(security check PC-SEC-02): install.sh moves an older installation's value there or writes a
random one, Compose hands it to PlantCraft as a secret, and PlantCraft and the demo seed read it."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

from plantcraft import demo_seed
from plantcraft.auth.public_demo import visitor_password

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
SCRIPT = (DEPLOY / "install.sh").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = SCRIPT.index(f"{name}() {{")
    end = SCRIPT.index("\n}\n", start) + 3
    return SCRIPT[start:end]


HARNESS = "\n".join(
    [
        'die() { echo "ERROR: $*" >&2; exit 1; }',
        SCRIPT[SCRIPT.index("random_secret() {") :].split("\n", 1)[0],
        _function("env_get"),
        _function("env_drop"),
        _function("keep_demo_password"),
        'keep_demo_password "$1" "$2"',
    ]
)


def _keep(tmp_path: Path, env: str) -> tuple[Path, str]:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    env_file = tmp_path / ".env"
    env_file.write_text(env, encoding="utf-8")
    subprocess.run(["bash", "-c", HARNESS, "-", str(data), str(env_file)], check=True)
    return data / "public-demo-password", env_file.read_text(encoding="utf-8")


def test_an_older_installations_password_moves_out_of_env(tmp_path):
    secret, env = _keep(
        tmp_path, "PLANTCRAFT_PUBLIC_DEMO=true\nPLANTCRAFT_PUBLIC_DEMO_PASSWORD=plantcraft-demo\n"
    )
    assert secret.read_text().strip() == "plantcraft-demo"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    assert "PASSWORD" not in env and "PLANTCRAFT_PUBLIC_DEMO=true" in env


def test_a_new_installation_gets_a_random_password_that_stays(tmp_path):
    secret, env = _keep(tmp_path, "PLANTCRAFT_PUBLIC_DEMO=true\n")
    first = secret.read_text().strip()
    assert len(first) >= 20 and first != "plantcraft-demo"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    # Installing again keeps it.
    secret, _ = _keep(tmp_path, env)
    assert secret.read_text().strip() == first


def test_a_password_set_by_hand_in_env_replaces_the_file(tmp_path):
    _keep(tmp_path, "")
    secret, env = _keep(tmp_path, "PLANTCRAFT_PUBLIC_DEMO_PASSWORD=chosen-by-hand\n")
    assert secret.read_text().strip() == "chosen-by-hand" and "PASSWORD" not in env


def test_install_sh_compose_and_the_examples_keep_it_out_of_env():
    assert 'keep_demo_password "$data" "$PREFIX/.env"' in SCRIPT
    assert "env_set PLANTCRAFT_PUBLIC_DEMO_PASSWORD" not in SCRIPT
    assert "-e PLANTCRAFT_PUBLIC_DEMO_PASSWORD" not in SCRIPT
    assert "data/public-demo-password" in SCRIPT.split("chmod 0600 data/initial-admin-password")[1]
    compose = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    assert "PLANTCRAFT_PUBLIC_DEMO_PASSWORD_FILE: /run/secrets/public_demo_password" in compose
    assert "public_demo_password:\n    file: ./data/public-demo-password" in compose
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    assert "PLANTCRAFT_PUBLIC_DEMO_PASSWORD=" not in example
    check = (DEPLOY / "security-check.sh").read_text(encoding="utf-8")
    assert "data/public-demo-password" in check


def test_plantcraft_and_the_seed_read_the_secret_file(tmp_path, monkeypatch):
    secret = tmp_path / "public_demo_password"
    secret.write_text("from-the-file\n")
    monkeypatch.delenv("PLANTCRAFT_PUBLIC_DEMO_PASSWORD", raising=False)
    monkeypatch.setenv("PLANTCRAFT_PUBLIC_DEMO_PASSWORD_FILE", str(secret))
    assert visitor_password() == "from-the-file"
    assert demo_seed._visitor_password() == "from-the-file"
    # The variable still wins, for an installation that sets it by hand.
    monkeypatch.setenv("PLANTCRAFT_PUBLIC_DEMO_PASSWORD", "from-env")
    assert visitor_password() == "from-env" and demo_seed._visitor_password() == "from-env"
    monkeypatch.delenv("PLANTCRAFT_PUBLIC_DEMO_PASSWORD")
    monkeypatch.setenv("PLANTCRAFT_PUBLIC_DEMO_PASSWORD_FILE", str(tmp_path / "missing"))
    assert visitor_password() == "" and demo_seed._visitor_password() == ""
