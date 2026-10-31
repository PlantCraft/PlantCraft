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


# --- P5: the catalogue as signed data, exceptions that expire, the evidence report -------------

CATALOG = SCRIPT.parent / "security-checks.tsv"
FAKE_DOCKER = """#!/bin/sh
case "$1" in
  ps) echo t-processcraft-1 ;;
  inspect) echo '/t-processcraft-1|1000|true|false|no-new-privileges:true ||ALL|200|1073741824|t_apps|healthy||' ;;
  version) echo 27.0.1 ;;
  info) echo false ;;
esac
exit 0
"""


def _catalog() -> dict[str, tuple[str, str, str]]:
    rows = {}
    for line in CATALOG.read_text().splitlines():
        if line and not line.startswith("#"):
            cid, sev, title, refs = line.split("\t")
            rows[cid] = (sev, title, refs)
    return rows


def test_the_catalogue_lists_every_check_the_script_runs_with_the_same_severity_and_title():
    text = SCRIPT.read_text()
    catalog = _catalog()
    seen = {}
    for m in re.finditer(
        r'check (PC-[A-Z]+-\d\d) (critical|high|medium|low|info) (?:pass|warn|fail|info|na|"\$\w+") "([^"]+)"',
        text,
    ):
        seen.setdefault(m.group(1), (m.group(2), m.group(3)))
    for m in re.finditer(
        r'check (PC-[A-Z]+-\d\d) (critical|high|medium|low|info) "\$\(.*?\)" "([^"]+)"', text
    ):
        seen.setdefault(m.group(1), (m.group(2), m.group(3)))
    assert set(seen) == set(catalog)
    for cid, (sev, title) in seen.items():
        assert catalog[cid][:2] == (sev, title), cid
        assert catalog[cid][2], cid


def test_the_bundle_and_the_installer_carry_the_catalogue_and_the_signed_hashes():
    bundle = (SCRIPT.parent / "bundle.sh").read_text()
    install = (SCRIPT.parent / "install.sh").read_text()
    assert '"$ROOT/deploy/security-checks.tsv"' in bundle
    assert 'cp "$BUNDLE_DIR/security-checks.tsv" "$PREFIX/"' in install
    assert 'cp "$BUNDLE_DIR/SHA256SUMS" "$PREFIX/release-SHA256SUMS"' in install
    assert 'cp "$BUNDLE_DIR/SHA256SUMS.sig" "$PREFIX/release-SHA256SUMS.sig"' in install


def _install(tmp_path: Path, env: str = "", exceptions: str | None = None) -> Path:
    import shutil

    folder = tmp_path / "inst"
    folder.mkdir()
    shutil.copy(SCRIPT, folder)
    shutil.copy(CATALOG, folder)
    (folder / ".env").write_text("COMPOSE_PROJECT_NAME=t\nPLANTCRAFT_VERSION=0.6.0\n" + env)
    (folder / ".env").chmod(0o640)
    if exceptions is not None:
        (folder / "security-exceptions.conf").write_text(exceptions)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    return folder


def _run(folder: Path, *args: str) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ, PATH=f"{folder.parent / 'bin'}:{os.environ['PATH']}")
    return subprocess.run(
        ["bash", str(folder / "security-check.sh"), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def _checks(folder: Path, *args: str) -> tuple[dict, dict]:
    import json

    out = _run(folder, "--format", "json", *args)
    document = json.loads(out.stdout)
    return document, {c["id"]: c for c in document["checks"]}


def test_an_exception_holds_until_its_day_and_then_the_check_fails_again(tmp_path):
    folder = _install(
        tmp_path,
        exceptions="# accepted risks\n"
        "PC-REC-01 2999-12-31 backups go to the plant NAS (ticket 42)\n"
        "PC-REC-02 2000-01-01 drill planned for next month\n"
        "PC-NOPE-01 2999-12-31 not a check\n"
        "PC-MIN-02 soon no date\n",
    )
    doc, checks = _checks(folder)
    assert checks["PC-REC-01"]["result"] == "excepted"
    assert checks["PC-REC-01"]["exception"]["state"] == "active"
    assert "it was fail" in checks["PC-REC-01"]["evidence"]
    assert checks["PC-REC-02"]["result"] == "warn"
    assert checks["PC-REC-02"]["exception"]["state"] == "expired"
    assert "expired on 2000-01-01" in checks["PC-REC-02"]["evidence"]
    assert doc["summary"]["excepted"] == 1
    # Without the exception the same install fails (exit 1); with it, it does not.
    assert _run(folder).returncode == 0
    (folder / "security-exceptions.conf").write_text("PC-REC-01 2000-01-01 too old\n")
    assert _run(folder).returncode == 1
    err = _run(folder, "--exceptions", str(tmp_path / "missing.conf"))
    assert err.returncode == 2


def test_bad_exception_lines_are_reported_and_ignored(tmp_path):
    folder = _install(tmp_path, exceptions="PC-NOPE-01 2999-12-31 x\nPC-MIN-02 soon y\n")
    out = _run(folder)
    assert "PC-NOPE-01 is not a check of this release" in out.stderr
    assert 'not "ID YYYY-MM-DD reason"' in out.stderr


def test_the_catalogue_sets_severity_and_title(tmp_path):
    folder = _install(tmp_path)
    catalog = (folder / "security-checks.tsv").read_text()
    (folder / "security-checks.tsv").write_text(
        catalog.replace("PC-REC-01\thigh\t", "PC-REC-01\tcritical\t")
    )
    _, checks = _checks(folder)
    assert checks["PC-REC-01"]["severity"] == "critical"
    # The checks with no HTTPS answer take their real titles from it.
    assert checks["PC-TLS-04"]["title"] == "Only TLS 1.2 and 1.3 are accepted"


def test_the_evidence_report_maps_results_to_requirements_and_hides_secrets(tmp_path):
    import json

    folder = _install(
        tmp_path,
        env="PLANTCRAFT_PUBLIC_DEMO=false\nOPENAI_API_KEY=sk-not-real\nPLANTCRAFT_DB_PASSWORD=pw\n",
        exceptions="PC-REC-01 2999-12-31 backups go to the plant NAS\n",
    )
    out = _run(folder, "--format", "evidence")
    doc = json.loads(out.stdout)
    assert doc["report"] == "plantcraft-security-evidence"
    assert any("CR 7.6 RE 1" in s for s in doc["standard"])
    assert doc["scope"]["version"] == "0.6.0"
    assert doc["settings"]["PLANTCRAFT_PUBLIC_DEMO"] == "false"
    assert "sk-not-real" not in out.stdout and "OPENAI_API_KEY" not in doc["settings"]
    assert "PLANTCRAFT_DB_PASSWORD" not in doc["settings"]
    assert (
        len(doc["check_set"]["script_sha256"]) == 64
        and len(doc["check_set"]["catalog_sha256"]) == 64
    )
    reqs = {r["requirement"]: r for r in doc["requirements"]}
    assert reqs["CR 7.3"]["result"] == "excepted" and "PC-REC-01" in reqs["CR 7.3"]["checks"]
    assert reqs["CR 7.1"]["checks"] == ["PC-CTR-04"] and reqs["CR 7.2"]["checks"] == ["PC-CTR-04"]
    assert reqs["CR 1.1"]["result"] == "na"  # no HTTPS answer: not checked, not passed
    assert doc["exceptions"] == [
        {
            "id": "PC-REC-01",
            "until": "2999-12-31",
            "reason": "backups go to the plant NAS",
            "state": "active",
        }
    ]


def _openssl_rawin() -> bool:
    out = subprocess.run(["openssl", "pkeyutl", "-help"], capture_output=True, text=True)
    return "-rawin" in out.stdout + out.stderr


def test_the_check_verifies_itself_against_the_signed_release(tmp_path):
    import base64
    import hashlib
    import json

    import pytest

    if not _openssl_rawin():
        pytest.skip("needs OpenSSL 1.1.1 or later")
    folder = _install(tmp_path)
    _, checks = _checks(folder)
    assert checks["PC-INT-01"]["result"] == "warn"  # no signed hashes beside it

    sums = "".join(
        f"{hashlib.sha256((folder / f).read_bytes()).hexdigest()}  {f}\n"
        for f in ("security-check.sh", "security-checks.tsv")
    )
    (folder / "SHA256SUMS").write_text(sums)
    # Signed the way release.sign does (Ed25519 over the bytes of SHA256SUMS, base64 in JSON).
    key, sig = tmp_path / "test.key", tmp_path / "sig.bin"
    (folder / "trusted-publishers").mkdir()
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(key)], check=True)
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(key),
            "-pubout",
            "-out",
            str(folder / "trusted-publishers" / "test-publisher.pub"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(key),
            "-rawin",
            "-in",
            str(folder / "SHA256SUMS"),
            "-out",
            str(sig),
        ],
        check=True,
    )
    document = {
        "format": 1,
        "publisher": "test-publisher",
        "signed": "SHA256SUMS",
        "signature": base64.b64encode(sig.read_bytes()).decode(),
    }
    (folder / "release-SHA256SUMS.sig").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    (folder / "SHA256SUMS").rename(folder / "release-SHA256SUMS")
    _, checks = _checks(folder)
    assert checks["PC-INT-01"]["result"] == "pass", checks["PC-INT-01"]
    assert "signed by test-publisher" in checks["PC-INT-01"]["evidence"]

    # A severity lowered by hand in the catalogue no longer matches the signed hashes.
    catalog = folder / "security-checks.tsv"
    catalog.write_text(catalog.read_text().replace("PC-NET-01\tcritical", "PC-NET-01\tlow"))
    _, checks = _checks(folder)
    assert checks["PC-INT-01"]["result"] == "fail"
    assert "security-checks.tsv" in checks["PC-INT-01"]["evidence"]
    assert _run(folder).returncode == 1


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
