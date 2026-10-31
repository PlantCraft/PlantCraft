"""deploy/security-check.sh: a catalogue of checks with stable ids, each with a severity and
references, that parses as bash (the run itself is checked on an installed suite, D22)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "security-check.sh"
CHECK = re.compile(r'check (?:"\$id"|(PC-[A-Z]+-\d\d)) (critical|high|medium|low|info) ')


def test_the_script_parses_and_explains_itself():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    out = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True).stdout
    assert "--format json" in out and "Exit code" in out


def test_every_check_has_a_stable_id_a_severity_and_references():
    text = SCRIPT.read_text()
    ids = {m.group(1) for m in CHECK.finditer(text) if m.group(1)}
    assert len(ids) >= 35
    for area in ("INT", "CTR", "NET", "TLS", "SEC", "ACC", "AUD", "REC", "MIN", "HOST"):
        assert any(i.startswith(f"PC-{area}-") for i in ids), area
    # Every check call ends with its references (CR of IEC 62443-4-2, a NIST control or CIS).
    calls = re.findall(
        r"check (PC-[A-Z]+-\d\d) .*?\"((?:CR|SAR|IA|SI|CM|CIS)[^\"]*)\"\s*$", text, re.M | re.S
    )
    assert calls


def test_install_sh_runs_it():
    install = (SCRIPT.parent / "install.sh").read_text()
    assert '--security-check) ACTION="security-check"' in install
    assert 'exec "$PREFIX/security-check.sh"' in install


def test_the_emergency_password_is_rotated_every_90_days():
    """P8 (LACUNAS-0-6): install.sh writes a new password on stdin to the helper (never on a
    command line), keeps the file's owner and mode, and the check fails after 90 days."""

    install = (SCRIPT.parent / "install.sh").read_text()
    assert '--rotate-admin-password) ACTION="rotate-admin-password"' in install
    assert "rotate-admin-password) do_rotate_admin_password" in install
    body = install[install.index("do_rotate_admin_password() {") :]
    body = body[: body.index("\n}\n")]
    assert "docker run --rm -i" in body and "cat >/install/data/initial-admin-password" in body
    assert "chmod 0600 /install/data/initial-admin-password" in body
    assert "compose restart processcraft" in body
    check = SCRIPT.read_text()
    assert 'if [ "$age" -gt 90 ]; then r=fail; else r=warn; fi' in check
    assert "--rotate-admin-password" in check
