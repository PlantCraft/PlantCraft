"""The app package's compatibility, language and closed-source rules (docs/app-package.md §7-8):
``app.toml``'s new keys, ``plantcraft-app check``, ``compat`` reports and ``license`` files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from test_app_manifest import _manifest, _repo

from plantcraft_sdk import compat, licensing
from plantcraft_sdk.app_cli import check, main
from plantcraft_sdk.app_manifest import ManifestError, parse_manifest


def _set(root: Path, old: str, new: str) -> None:
    path = root / "app.toml"
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def test_new_keys_default_and_parse():
    manifest = parse_manifest(_manifest())
    assert manifest.app.source == "open" and manifest.app.languages == ["en"]
    assert manifest.requires.platform == ">=0.6,<0.8"
    assert manifest.tested.platform == [] and manifest.license.required is False


@pytest.mark.parametrize(
    "changes, needle",
    [
        ({"app__languages": ["pt-BR"]}, '"en"'),
        ({"app__languages": ["en", "Portuguese"]}, "app.languages"),
        ({"app__source": "secret"}, "app.source"),
        ({"requires__platform": "newest"}, "requires.platform"),
    ],
)
def test_bad_new_keys(changes, needle):
    with pytest.raises(ManifestError) as error:
        parse_manifest(_manifest(**changes))
    assert needle in str(error.value)


def test_each_language_needs_both_catalogs(tmp_path):
    root = _repo(tmp_path)
    _set(root, 'mark = "cpmcraft"', 'mark = "cpmcraft"\nlanguages = ["en", "pt-BR"]')
    errors = check(root).errors
    assert (
        "frontend/src/locales/pt-BR.json: missing for language pt-BR in [app] languages" in errors
    )
    assert (
        "src/cpmcraft/locales/pt-BR.json: missing for language pt-BR in [app] languages" in errors
    )
    for place in ("frontend/src/locales", "src/cpmcraft/locales"):
        (root / place).mkdir(parents=True)
        (root / place / "pt-BR.json").write_text(json.dumps({"Loops": "Malhas"}))
    assert check(root).ok
    (root / "src/cpmcraft/locales/pt-BR.json").write_text('{"Loops": ["Malhas"]}')
    assert any("flat table" in error for error in check(root).errors)


def test_a_closed_app_names_its_own_licence(tmp_path):
    root = _repo(tmp_path)
    _set(root, 'mark = "cpmcraft"', 'mark = "cpmcraft"\nsource = "closed"')
    assert any("is open source" in error for error in check(root).errors)
    _set(root, 'license = "Apache-2.0"', 'license = "LicenseRef-Acme-EULA"')
    assert check(root).ok


def test_an_app_without_a_platform_range_is_warned(tmp_path):
    root = _repo(tmp_path)
    _set(root, 'platform = ">=0.6,<0.8"\n', "")
    report = check(root)
    assert report.ok and any("[requires] platform" in warning for warning in report.warnings)


def _installation(**extra):
    return {
        "id": "inst-12345678",
        "version": "0.6.0",
        "api": "1.0",
        "features": ["llm", "widgets", "search", "queue"],
        "scopes": ["read.assets", "read.signals", "read.series", "read.results", "write.audit",
                   "write.results", "write.events", "write.runs", "write.schedules"],
        **extra,
    }  # fmt: skip


def test_compat_report_checks_range_features_and_scopes():
    manifest = parse_manifest(_manifest())
    report = compat.compat_report(manifest, _installation(), me_ok=True, tests=None)
    assert report["passed"] and report["platform"] == "0.6.0" and report["app"] == "cpmcraft"
    outside = compat.compat_report(manifest, _installation(version="0.8.0"), me_ok=True, tests=None)
    assert not outside["passed"]
    narrow = compat.compat_report(
        manifest, _installation(scopes=["read.assets"]), me_ok=True, tests=None
    )
    failed = {item["check"] for item in narrow["checks"] if not item["ok"]}
    assert failed == {"permissions"}
    old = compat.compat_report(manifest, _installation(version=""), me_ok=True, tests=None)
    assert not old["passed"]
    tests = {"passed": False, "detail": "tests/compat: failed"}
    assert not compat.compat_report(manifest, _installation(), me_ok=True, tests=tests)["passed"]


def test_tested_lists_passing_reports_of_this_version(tmp_path, capsys):
    root = _repo(tmp_path)
    (root / "compat").mkdir()
    for platform, version, passed in (("0.6.0", "0.1.0", True), ("0.7.0", "0.1.0", False),
                                      ("0.5.0", "0.0.1", True)):  # fmt: skip
        report = {"platform": platform, "app": "cpmcraft", "app_version": version, "passed": passed}
        (root / "compat" / f"{platform}.json").write_text(json.dumps(report))
    assert main(["tested", "--path", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"platform": ["0.6.0"]}


def test_license_issue_and_show_from_the_command_line(tmp_path, capsys):
    key = licensing.new_key()
    (tmp_path / "acme.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (tmp_path / "acme.pub").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    out = tmp_path / "north.pclicense"
    args = ["license", "issue", "--key", str(tmp_path / "acme.key"), "--app", "pidcraft",
            "--publisher", "Acme Tools", "--customer", "Refinery North",
            "--installation", "inst-12345678", "--expires", "2099-12-31",
            "--limit", "sheets=200", "--feature", "dexpi", "--out", str(out)]  # fmt: skip
    assert main(args) == 0
    show = ["license", "show", "--public-key", str(tmp_path / "acme.pub"), "--app", "pidcraft",
            "--installation", "inst-12345678", str(out)]  # fmt: skip
    capsys.readouterr()
    assert main(show) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["status"] == "valid" and state["limits"] == {"sheets": 200}
    assert main([*show[:-2], "inst-87654321", str(out)]) == 1


def test_guard_keeps_the_last_good_state_when_platform_is_away():
    key = licensing.new_key()
    body = {"id": "x", "app": "pidcraft", "publisher": "Acme Tools", "customer": "P",
            "installation": "*", "issued": "2026-01-01", "expires": "2099-01-01"}  # fmt: skip
    data = licensing.issue(key, body)

    class Client:
        fail = False

        def app_license(self):
            if self.fail:
                raise ConnectionError("down")
            return data

        def installation_id(self):
            return "inst-12345678"

    guard = licensing.LicenseGuard(app_id="pidcraft", public_key=key.public_key())
    client = Client()
    assert guard.refresh(client).usable
    client.fail = True
    assert guard.refresh(client).usable
