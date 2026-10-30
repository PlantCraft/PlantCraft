"""Releases: release.json, release notes, the bundle's signature and the update checks."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from plantcraft.apps import package, release
from plantcraft.apps.release import ReleaseError

CHANGELOG = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-10-21

### Added

- Backups.

## [0.1.0] - 2026-10-01

- First.
"""


def _bundle(tmp_path, version="0.2.0", upgrade_from="0.1.0", *, signed_by=None, key=None,
            name="bundle"):  # fmt: skip
    folder = tmp_path / name
    folder.mkdir()
    (folder / "bundle.env").write_text(
        "# Written by deploy/bundle.sh\n"
        f"PLANTCRAFT_VERSION={version}\nLINKCRAFT_VERSION=0.3.1\nDASHCRAFT_VERSION=\n"
        "SIMCRAFT_VERSION=0.4.1\nUPGRADE_FROM=0.1.0\nCREATED=2026-10-21T12:00:00Z\n"
        f"# processcraft:{version} sha256:{'a' * 64}\n# linkcraft:0.3.1 sha256:{'b' * 64}\n"
    )
    (folder / "images.tar").write_bytes(b"images")
    changelog = tmp_path / f"{name}-CHANGELOG.md"
    changelog.write_text(CHANGELOG)
    release.make(folder, upgrade_from=upgrade_from, changelogs={"processcraft": changelog})
    _sums(folder)
    if signed_by:
        release.sign(folder, key, signed_by)
    return folder


def _sums(folder):
    lines = []
    for path in sorted(
        p for p in folder.iterdir() if p.name not in {"SHA256SUMS", "SHA256SUMS.sig"}
    ):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n")


@pytest.fixture()
def keys(tmp_path):
    private, public = package.keygen("processcraft", tmp_path / "keys")
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    (trusted / "processcraft.pub").write_bytes(public.read_bytes())
    return private, trusted


def test_versions_order_like_semver():
    assert release.version_key("0.10.0") > release.version_key("0.9.9")
    assert release.version_key("0.2.0-rc.1") < release.version_key("0.2.0")
    with pytest.raises(ReleaseError):
        release.version_key("latest")


def _install_sh_version_ge(newer: str, older: str) -> bool:
    """install.sh's own ``version_ge``, run by bash on its own."""

    script = Path(__file__).resolve().parents[1] / "deploy" / "install.sh"
    text = script.read_text(encoding="utf-8")
    start = text.index("version_ge() {")
    body = text[start : text.index("\n}\n", start) + 3]
    done = subprocess.run(
        ["bash", "-c", f'{body}\nversion_ge "$1" "$2"', "-", newer, older], check=False
    )
    return done.returncode == 0


@pytest.mark.parametrize(
    "a,b",
    [
        ("0.5.1", "0.5.1-rc3"),
        ("0.5.1-rc3", "0.5.1-rc2"),
        ("0.5.1-rc.10", "0.5.1-rc.9"),
        ("0.6.0-rc1", "0.5.1"),
        ("0.10.0", "0.9.9"),
        ("29.9.2", "24.0"),
    ],
)
def test_install_sh_orders_versions_as_the_release_check_does(a, b):
    assert _install_sh_version_ge(a, b) and not _install_sh_version_ge(b, a)
    assert _install_sh_version_ge(a, a)
    if a in ("0.5.1", "0.6.0-rc1", "0.10.0"):  # the suite's own versions
        assert release.version_key(a) > release.version_key(b)


def test_the_changelog_entry_of_a_version():
    assert release.changelog_entry(CHANGELOG, "0.2.0") == "### Added\n\n- Backups."
    assert release.changelog_entry(CHANGELOG, "0.1.0") == "- First."
    assert release.changelog_entry(CHANGELOG, "0.3.0") is None


def test_make_writes_the_release_and_its_notes(tmp_path):
    folder = _bundle(tmp_path)
    written = json.loads((folder / "release.json").read_text())
    assert written["version"] == "0.2.0" and written["upgrade_from"] == "0.1.0"
    assert written["components"]["linkcraft"] == {"name": "PlantCraft Analytics", "version": "0.3.1",
                                                  "notes": False}  # fmt: skip
    assert "dashcraft" not in written["components"]  # not in this bundle
    assert written["images"][0] == {"ref": "processcraft:0.2.0", "id": "sha256:" + "a" * 64}
    notes = (folder / "RELEASE-NOTES.md").read_text()
    assert "## PlantCraft 0.2.0\n\n### Added\n\n- Backups." in notes
    assert "## PlantCraft Analytics 0.3.1\n\n_No notes for this version._" in notes


def test_a_signed_bundle_passes_and_says_who_signed(tmp_path, keys):
    private, trusted = keys
    folder = _bundle(tmp_path, signed_by="processcraft", key=private)
    outcome = release.check(folder, installed="0.1.0", trusted=trusted)
    assert outcome["state"] == "ok", outcome
    assert outcome["signed_by"] == "processcraft"
    assert outcome["key_id"] == package.key_id(package.load_private_key(private).public_key())


def test_a_changed_bundle_or_an_unknown_publisher_is_refused(tmp_path, keys):
    private, trusted = keys
    folder = _bundle(tmp_path, signed_by="processcraft", key=private)
    sums = (folder / "SHA256SUMS").read_text()
    (folder / "SHA256SUMS").write_text(sums.replace("a", "b", 1))
    outcome = release.check(folder, installed="0.1.0", trusted=trusted)
    assert outcome["state"] == "refused"
    assert any("signature does not match" in p for p in outcome["problems"])
    (folder / "SHA256SUMS").write_text(sums)
    (folder / "release.json").write_text((folder / "release.json").read_text() + " ")
    outcome = release.check(folder, installed="0.1.0", trusted=trusted)
    assert "release.json does not match SHA256SUMS: the bundle was modified" in outcome["problems"]
    other, _ = package.keygen("someone", tmp_path / "other")
    stranger = _bundle(tmp_path, signed_by="someone", key=other, name="stranger")
    outcome = release.check(stranger, installed="0.1.0", trusted=trusted)
    assert any("does not trust" in p for p in outcome["problems"])


def test_an_unsigned_bundle_needs_allow_unsigned_where_publishers_are_trusted(tmp_path, keys):
    _, trusted = keys
    folder = _bundle(tmp_path)
    assert "not signed" in release.check(folder, installed="0.1.0", trusted=trusted)["problems"][0]
    allowed = release.check(folder, installed="0.1.0", trusted=trusted, allow_unsigned=True)
    assert allowed["state"] == "ok" and "--allow-unsigned" in allowed["notes"][0]
    untrusting = release.check(folder, installed="0.1.0", trusted=tmp_path / "none")
    assert untrusting["state"] == "ok" and "not checked" in untrusting["notes"][0]


def test_versions_going_back_or_skipping_too_far_are_refused(tmp_path):
    folder = _bundle(tmp_path, version="0.5.0", upgrade_from="0.4.0")
    older = release.check(folder, installed="0.6.0", trusted=None)
    assert "older than the installed version" in older["problems"][0]
    assert "install.sh --rollback" in older["problems"][0]
    skipped = release.check(folder, installed="0.3.2", trusted=None)
    assert "update to 0.4.0 first" in skipped["problems"][0]
    assert release.check(folder, installed="0.4.0", trusted=None)["state"] == "ok"


def test_a_bundle_without_release_is_refused(tmp_path):
    folder = tmp_path / "old"
    folder.mkdir()
    outcome = release.check(folder, installed="0.1.0", trusted=None)
    assert outcome["state"] == "refused" and "release.json is missing" in outcome["problems"][0]


def test_the_command_line(tmp_path, keys, capsys):
    private, trusted = keys
    folder = _bundle(tmp_path)
    assert (
        release.main(["sign", str(folder), "--key", str(private), "--publisher", "processcraft"])
        == 0
    )
    assert "signed by processcraft" in capsys.readouterr().out
    assert (
        release.main(["check", str(folder), "--installed", "0.1.0", "--trusted", str(trusted)]) == 0
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out)["signed_by"] == "processcraft"
    assert "signature checked" in captured.err
    assert release.main(["check", str(folder), "--installed", "0.3.0"]) == 1
    assert "refused: this bundle (0.2.0) is older" in capsys.readouterr().err


def test_the_architecture_comes_from_bundle_env(tmp_path):
    folder = _bundle(tmp_path)
    assert "architecture" not in json.loads((folder / "release.json").read_text())
    other = tmp_path / "arm"
    other.mkdir()
    (other / "bundle.env").write_text("PLANTCRAFT_VERSION=0.3.0\nARCH=arm64\n")
    written, _ = release.make(other, upgrade_from="0.1.0", changelogs={})
    assert written["architecture"] == "arm64"
    (other / "bundle.env").write_text("PLANTCRAFT_VERSION=0.3.0\nARCH=s390x\n")
    with pytest.raises(ReleaseError, match="architecture"):
        release.make(other, upgrade_from="0.1.0", changelogs={})


def test_the_committed_release_key_is_published_consistently():
    # The public key the bundles carry and the allowed_signers line printed in the guide.
    folder = Path(__file__).resolve().parents[1] / "deploy" / "trusted-publishers"
    printed = release.fingerprint(folder / "processcraft.pub", "processcraft")
    assert (folder / "processcraft.allowed_signers").read_text().strip() == printed[
        "allowed_signers"
    ]
    guide = (folder.parents[1] / "docs" / "install-offline.md").read_text()
    assert printed["key_id"] in guide and printed["ssh_fingerprint"] in guide
    assert printed["allowed_signers"] in guide


def test_the_archive_hash_is_signed_for_ssh_keygen(tmp_path, keys):
    private, trusted = keys
    sums = tmp_path / "plantcraft-0.3.0-linux-arm64-bundle.tar.gz.sha256"
    sums.write_text(f"{'c' * 64}  plantcraft-0.3.0-linux-arm64-bundle.tar.gz\n")
    signature = release.sign_file(sums, private)
    assert signature.name == sums.name + ".sig"
    text = signature.read_text()
    assert text.startswith("-----BEGIN SSH SIGNATURE-----\n")
    assert text.endswith("-----END SSH SIGNATURE-----\n")
    printed = release.fingerprint(trusted / "processcraft.pub", "processcraft")
    assert printed["ssh_fingerprint"].startswith("SHA256:")
    assert printed["allowed_signers"].startswith(
        'release@plantcraft namespaces="file" ssh-ed25519 '
    )
    if not shutil.which("ssh-keygen"):
        pytest.skip("ssh-keygen is not installed: the format is checked against it where it is")
    signers = tmp_path / "allowed_signers"
    signers.write_text(printed["allowed_signers"] + "\n")

    def verify(data: bytes) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", "release@plantcraft",
             "-n", "file", "-s", str(signature)],
            input=data, capture_output=True, check=False,
        )  # fmt: skip

    good = verify(sums.read_bytes())
    assert good.returncode == 0, good.stderr
    assert printed["ssh_fingerprint"].encode() in good.stdout + good.stderr
    assert verify(sums.read_bytes() + b"x").returncode != 0


def test_make_pins_each_apps_permissions_from_its_app_toml(tmp_path):
    folder = _bundle(tmp_path)
    manifest = tmp_path / "linkcraft.toml"
    manifest.write_text(
        '[app]\nid = "linkcraft"\n[permissions]\nread = ["signals", "assets"]\nwrite = ["audit"]\n'
    )
    release.make(folder, upgrade_from="0.1.0", changelogs={}, manifests={"linkcraft": manifest})
    written = json.loads((folder / "release.json").read_text())
    assert written["permissions"] == {"linkcraft": ["read.assets", "read.signals", "write.audit"]}
    manifest.write_text('[permissions]\nread = "signals"\n')
    with pytest.raises(ReleaseError):
        release.make(folder, upgrade_from="0.1.0", changelogs={}, manifests={"linkcraft": manifest})
