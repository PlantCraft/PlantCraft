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
