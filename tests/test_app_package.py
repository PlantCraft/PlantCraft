"""Signed app packages (processcraft/apps/package.py) against hostile input.

Every refused package raises PackageError with a reason, never another exception, and nothing
is ever written outside the folder the caller gave (or anywhere, without one).
"""

from __future__ import annotations

import ast
import base64
import gzip
import json
import os
import tarfile
from pathlib import Path

import pytest

from processcraft.apps import package as pkg
from tests import app_packages as ap

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def keys(tmp_path):
    key, trusted = ap.publisher(tmp_path)
    return key, pkg.load_trusted(trusted)


@pytest.fixture()
def good(tmp_path, keys):
    return ap.build(tmp_path / "build", keys[0])


def _refused(path: Path, trusted, match: str, **kwargs) -> None:
    with pytest.raises(pkg.PackageError, match=match):
        pkg.verify_package(path, trusted, **kwargs)


def _tree(folder: Path) -> set[str]:
    return {str(path.relative_to(folder)) for path in folder.rglob("*")}


# The good path --------------------------------------------------------------------------------


@pytest.mark.parametrize("compress", [False, True])
def test_a_signed_package_verifies_and_extracts_only_its_payload(tmp_path, keys, compress):
    package = ap.build(tmp_path / "b", keys[0], compress=compress)
    out = tmp_path / "out"
    out.mkdir()
    verified = pkg.verify_package(package, keys[1], extract_to=out)
    summary = verified.summary()
    assert summary["id"] == "hello" and summary["version"] == "0.1.0"
    assert summary["publisher"]["id"] == "testpub" and len(summary["publisher"]["key_id"]) == 16
    assert [item["id"] for item in summary["permissions"]] == ["read.assets", "read.signals"]
    assert summary["summary"] == "A test app." and summary["uid"] == ap.template()["runtime"]["uid"]
    assert verified.sbom["packages"] == 2 and verified.sbom["format"] == "SPDX-2.3"
    assert verified.image_ids[0].startswith("sha256:")
    assert sorted(path.name for path in out.iterdir()) == ["image.tar", "sbom.spdx.json"]
    assert json.loads((out / "sbom.spdx.json").read_text()) == ap.SBOM


def test_the_command_line_builds_and_verifies(tmp_path, keys, capsys):
    package = ap.build(tmp_path / "b", keys[0])
    trusted = tmp_path / "trusted"
    assert pkg.main(["verify", "--trusted", str(trusted), str(package)]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "hello"
    other, _ = ap.publisher(tmp_path / "other", "otherpub")
    assert pkg.main(["verify", "--trusted", str(other.parent), str(package)]) == 1
    assert "unknown publisher" in capsys.readouterr().err


def test_keygen_never_overwrites_a_key_and_keeps_it_private(tmp_path):
    private, public = pkg.keygen("dev", tmp_path)
    assert oct(private.stat().st_mode & 0o777) == "0o600"
    assert b"PUBLIC KEY" in public.read_bytes()
    with pytest.raises(pkg.PackageError, match="refusing to overwrite"):
        pkg.keygen("dev", tmp_path)
    with pytest.raises(pkg.PackageError):
        pkg.keygen("../evil", tmp_path)


def test_the_module_imports_nothing_from_processcraft():
    """The installer image and other repositories run package.py on its own."""

    tree = ast.parse((ROOT / "processcraft" / "apps" / "package.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0 and not (node.module or "").startswith("processcraft")
        elif isinstance(node, ast.Import):
            assert not any(alias.name.startswith("processcraft") for alias in node.names)


# Signatures and publishers --------------------------------------------------------------------


def test_a_changed_manifest_breaks_the_signature(tmp_path, keys, good):
    members = ap.members_of(good)
    members["manifest.json"] = members["manifest.json"].replace(b"0.1.0", b"0.1.1")
    tampered = ap.raw(tmp_path / "t.pcapp", list(members.items()))
    _refused(tampered, keys[1], "signature does not match")


@pytest.mark.parametrize(
    "signature",
    [b"", b"not base64!", base64.b64encode(b"short"), base64.b64encode(bytes(64)), b"\xff" * 80],
)
def test_bad_signatures_are_refused(tmp_path, keys, good, signature):
    members = ap.members_of(good)
    members["manifest.sig"] = signature
    _refused(ap.raw(tmp_path / "s.pcapp", list(members.items())), keys[1], "signature")


def test_a_signature_by_another_key_is_refused(tmp_path, keys, good):
    other, _ = ap.publisher(tmp_path / "other")  # same publisher id, different key
    resigned = ap.resign(good, other, tmp_path / "r.pcapp", lambda manifest: None)
    _refused(resigned, keys[1], "signature does not match")


def test_an_unknown_publisher_is_refused(tmp_path, good):
    _, trusted = ap.publisher(tmp_path / "x", "someone-else")
    _refused(good, pkg.load_trusted(trusted), "unknown publisher 'testpub'")
    _refused(good, {}, "unknown publisher")


def test_trusted_keys_skip_bad_files(tmp_path):
    folder = tmp_path / "trusted"
    folder.mkdir()
    (folder / "broken.pub").write_text("not a key")
    (folder / "Bad Name.pub").write_text("x")
    assert pkg.load_trusted(folder) == {}
    assert pkg.load_trusted(tmp_path / "missing") == {} and pkg.load_trusted(None) == {}


# Hashes ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("member", ["image.tar", "sbom.spdx.json"])
def test_a_changed_payload_file_is_refused(tmp_path, keys, good, member):
    members = ap.members_of(good)
    members[member] = members[member][:-1] + bytes([members[member][-1] ^ 1])
    _refused(ap.raw(tmp_path / "h.pcapp", list(members.items())), keys[1], "SHA-256")


def test_a_lying_size_is_refused(tmp_path, keys, good):
    resigned = ap.resign(
        good,
        keys[0],
        tmp_path / "z.pcapp",
        lambda m: m["files"]["sbom.spdx.json"].update(
            size=m["files"]["sbom.spdx.json"]["size"] + 1
        ),
    )
    _refused(resigned, keys[1], "SHA-256")


# The tar itself -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["../manifest.json", "/etc/passwd", "a/../image.tar", "./manifest.json", "sub/image.tar",
     "..", "manifest.json/", "IMAGE.TAR"],
)  # fmt: skip
def test_paths_outside_the_package_are_refused_and_nothing_is_written(tmp_path, keys, good, name):
    members = ap.members_of(good)
    entries = [(name, b"evil")] + list(members.items())
    hostile = ap.raw(tmp_path / "p.pcapp", entries)
    out = tmp_path / "out"
    out.mkdir()
    before = _tree(tmp_path)
    _refused(hostile, keys[1], "unexpected entry|regular file|appears twice", extract_to=out)
    assert _tree(tmp_path) == before
    assert not (tmp_path.parent / "manifest.json").exists()


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_links_folders_and_devices_are_refused(tmp_path, keys, good, kind):
    members = ap.members_of(good)
    info = tarfile.TarInfo("image.tar")
    info.type = kind
    info.linkname = "/etc/passwd"
    entries = [(info, None)] + [
        (_info(name, data), data) for name, data in members.items() if name != "image.tar"
    ]
    out = tmp_path / "out"
    out.mkdir()
    _refused(ap.raw(tmp_path / "l.pcapp", entries), keys[1], "regular file", extract_to=out)
    assert list(out.iterdir()) == []
    assert not (out / "image.tar").is_symlink()


def _info(name: str, data: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info


def test_a_symlink_in_the_target_folder_is_never_followed(tmp_path, keys, good):
    out = tmp_path / "out"
    out.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep me")
    os.symlink(victim, out / "image.tar")
    _refused(good, keys[1], "not a readable package|exists", extract_to=out)
    assert victim.read_text() == "keep me"


def test_duplicate_extra_and_missing_members_are_refused(tmp_path, keys, good):
    members = ap.members_of(good)
    items = list(members.items())
    _refused(ap.raw(tmp_path / "d.pcapp", items + [items[0]]), keys[1], "more than|appears twice")
    _refused(ap.raw(tmp_path / "d2.pcapp", [items[0], items[0]]), keys[1], "appears twice")
    _refused(
        ap.raw(tmp_path / "e.pcapp", items + [("README", b"x")]), keys[1], "more than|unexpected"
    )
    _refused(ap.raw(tmp_path / "m.pcapp", items[:3]), keys[1], "missing")


def test_many_members_stop_reading_early(tmp_path, keys):
    bomb = ap.raw(tmp_path / "bomb.pcapp", [(f"f{i}", b"") for i in range(10_000)])
    _refused(bomb, keys[1], "unexpected entry")


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a tar at all",
        b"\x1f\x8b\x08\x00garbage",
        gzip.compress(b"x" * 1000),
        b"\x00" * 10240,
    ],
)
def test_files_that_are_not_packages_are_refused(tmp_path, keys, data):
    path = tmp_path / "junk.pcapp"
    path.write_bytes(data)
    _refused(path, keys[1], ".")


def test_a_truncated_package_is_refused(tmp_path, keys, good):
    data = good.read_bytes()
    with tarfile.open(good) as archive:
        image = archive.getmember("image.tar")
    # Inside the headers, inside the manifest, and inside the last member (the image).
    for cut in (100, 600, image.offset_data + image.size // 2, image.offset_data + image.size - 1):
        path = tmp_path / f"cut{cut}.pcapp"
        path.write_bytes(data[:cut])
        _refused(path, keys[1], ".")


def test_oversized_members_are_refused_before_reading(tmp_path, keys, good):
    members = ap.members_of(good)
    big = dict(members, **{"manifest.json": b" " * (pkg.LIMITS["manifest.json"] + 1)})
    _refused(ap.raw(tmp_path / "big.pcapp", list(big.items())), keys[1], "larger than")
    _refused(good, keys[1], "larger than", max_image_bytes=100)


def test_a_missing_file_is_refused(tmp_path, keys):
    _refused(tmp_path / "nope.pcapp", keys[1], "missing")


# The manifest ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [b"{", b"[]", b'"text"', b"\xff\xfe", b'{"a": 1, "a": 2}', b'{"port": NaN}', b"null",
     b"[" * 100_000],
)  # fmt: skip
def test_malformed_manifest_json_is_refused(tmp_path, keys, good, data):
    members = ap.members_of(good)
    members["manifest.json"] = data
    members["manifest.sig"] = pkg.sign(data, pkg.load_private_key(keys[0]))
    _refused(ap.raw(tmp_path / "j.pcapp", list(members.items())), keys[1], ".")


BAD_FIELDS = [
    ("app", "id", "Hello"), ("app", "id", "processcraft"), ("app", "id", "plantcraft"),
    ("app", "id", "ab"), ("app", "id", "x" * 32), ("app", "id", "../x"), ("app", "id", "my-app"),
    ("app", "version", "latest"), ("app", "version", "1"), ("app", "version", "1.0.0+evil"),
    ("app", "version", "1.0;rm"),
    ("app", "publisher", ""), ("app", "publisher", "../evil"), ("app", "publisher", {"id": "x"}),
    ("app", "name", ""), ("app", "name", "x" * 61), ("app", "name", "a\x00b"),
    ("app", "summary", ""), ("app", "summary", "x" * 201), ("app", "homepage", "http://plain"),
    ("app", "homepage", "javascript:alert(1)"), ("app", "mark", "Bad Mark"), ("app", "unknown", 1),
    ("runtime", "prefix", "/api/"), ("runtime", "prefix", "/assets/"), ("runtime", "prefix", "/"),
    ("runtime", "prefix", "cpm"), ("runtime", "prefix", "/a/b/"), ("runtime", "prefix", "/x y/"),
    ("runtime", "prefix", "/../"), ("runtime", "prefix", "/cpm/"), ("runtime", "prefix", "/quality/"),
    ("runtime", "port", 80), ("runtime", "port", 70000), ("runtime", "port", "8080"),
    ("runtime", "port", True),
    ("runtime", "uid", 0), ("runtime", "uid", 10001), ("runtime", "uid", 10005),
    ("runtime", "uid", 10002), ("runtime", "uid", 65534), ("runtime", "uid", "10100"),
    ("runtime", "image", "processcraft"), ("runtime", "image", "hello:latest"),
    ("runtime", "health", "healthz"), ("runtime", "health", "/a b"), ("runtime", "env", {}),
    ("permissions", "read", ["root"]), ("permissions", "read", "assets"),
    ("permissions", "read", ["assets", "assets"]), ("permissions", "write", ["plant"]),
    ("permissions", "plant_write", True), ("permissions", "plant_write", "no"),
    ("permissions", "outbound", ["example.com"]), ("permissions", "docker", True),
    ("requires", "processcraft_api", "$(rm)"), ("requires", "roles", {"loop": "pv"}),
    ("publishes", "results", [{"kind": "x"}]), ("publishes", "events", ["Bad Event"]),
    ("suggests", "asset_types", "loop"),
]  # fmt: skip


@pytest.mark.parametrize(("section", "key", "value"), BAD_FIELDS)
def test_invalid_manifest_fields_are_refused(section, key, value):
    manifest = {**ap.template(), "format": 1}
    manifest[section] = {**manifest.get(section, {}), key: value}
    with pytest.raises(pkg.PackageError):
        pkg.validate_manifest(manifest, with_files=False)


@pytest.mark.parametrize("section", ["app", "runtime", "permissions"])
def test_the_required_sections_are_required(section):
    manifest = {**ap.template(), "format": 1}
    manifest.pop(section)
    with pytest.raises(pkg.PackageError, match=section):
        pkg.validate_manifest(manifest, with_files=False)


def test_unknown_sections_are_refused():
    with pytest.raises(pkg.PackageError, match="unknown sections"):
        pkg.validate_manifest({**ap.template(), "format": 1, "environment": {}}, with_files=False)


def test_an_app_of_the_suite_table_must_use_its_row():
    row = {"prefix": "/cpm/", "port": 8070, "uid": 10002, "image": "cpmcraft"}
    good = {**ap.template("cpmcraft", runtime=row), "format": 1}
    assert pkg.flat(pkg.validate_manifest(good, with_files=False))["uid"] == 10002
    for change in ({"prefix": "/cpm2/"}, {"port": 8071}, {"uid": 10100}):
        manifest = {**ap.template("cpmcraft", runtime={**row, **change}), "format": 1}
        with pytest.raises(pkg.PackageError, match="suite table"):
            pkg.validate_manifest(manifest, with_files=False)


def test_the_whole_app_toml_of_the_standard_validates(tmp_path):
    text = """
[app]
id = "cpmcraft"
name = "CPMCraft"
version = "0.1.0"
category = "Control loop performance"
summary = "Finds control loops that oscillate, stick or sit in manual, and says why."
description = \"\"\"One paragraph for the Apps page.\"\"\"
publisher = "PlantCraft"
license = "Apache-2.0"
homepage = ""
mark = "cpmcraft"

[runtime]
prefix = "/cpm/"
port = 8070
uid = 10002
health = "/healthz"
image = "cpmcraft"

[requires]
processcraft_api = ">=1.0"
sdk = "0.2.0"
asset_types = ["loop"]
roles = { loop = ["pv", "op"] }

[permissions]
read = ["assets", "signals", "series", "results"]
write = ["audit", "results", "events", "runs", "schedules"]
plant_write = false
outbound = []

[publishes]
results = [{ kind = "loop_health", subject = "asset:loop" }]
events = ["finding.opened", "finding.closed"]

[consumes]
results = [{ kind = "datacraft.signal_quality", subject = "signal" }]

[suggests]
asset_types = ["loop"]
"""
    manifest = pkg.validate_manifest(pkg.from_app_toml(text.encode()), with_files=False)
    view = pkg.flat(manifest)
    assert view["publisher"] == {"id": "processcraft", "name": "PlantCraft"}
    assert view["image"] == "cpmcraft:0.1.0" and view["uid"] == 10002
    assert "read.series" in view["permissions"] and "write.schedules" in view["permissions"]
    assert manifest["publishes"]["events"] == ["finding.opened", "finding.closed"]
    assert manifest["requires"]["roles"] == {"loop": ["pv", "op"]}
    with pytest.raises(pkg.PackageError, match="TOML"):
        pkg.from_app_toml(b"[app\n")
    with pytest.raises(pkg.PackageError, match="unknown sections"):
        pkg.from_app_toml(b"[docker]\nsock = true\n")


def test_every_app_of_the_suite_packs_with_its_backup_and_what_it_adds():
    """The manifests of the monorepo build a package: [backup], [contributes] and series too."""

    root = Path(__file__).resolve().parents[1]
    for path in [*sorted(root.glob("apps/*/app.toml")), root / "templates/app/app.toml"]:
        manifest = pkg.validate_manifest(pkg.from_app_toml(path.read_bytes()), with_files=False)
        assert manifest["backup"]["skip"] == ["logs/"], path
    template = pkg.from_app_toml((root / "templates/app/app.toml").read_bytes())

    def changed(**sections):
        data = json.loads(json.dumps(template))
        for name, value in sections.items():
            data[name] = {**data.get(name, {}), **value}
        return data

    adds = changed(
        contributes={"widgets": [{"id": "notes", "title": "Notes"}], "search": {"types": ["Note"]}},
        publishes={"series": [{"name": "{asset}.notes", "title": "Notes", "type": "integer"}]},
    )
    manifest = pkg.validate_manifest(adds, with_files=False)
    # The template's own (calendar, to-do, model use, reference kind) and the two added here.
    assert pkg.flat(manifest)["adds"] == {
        "widgets": 1,
        "search": 1,
        "series": 1,
        "calendar": 1,
        "todo": 1,
        "llm": 1,
        "refs": 1,
    }
    for bad, message in (
        ({"contributes": {"queue": "yes"}}, "true or false"),
        ({"contributes": {"widgets": ["notes"]}}, "each item is a table"),
        ({"contributes": {"hologram": []}}, "unknown keys"),
        ({"backup": {"files": ["../etc"]}}, "inside the data folder"),
        ({"contributes": {"llm": [{"id": "x" * 70_000}]}}, "at most 64000 bytes"),
    ):
        with pytest.raises(pkg.PackageError, match=message):
            pkg.validate_manifest(changed(**bad), with_files=False)


def test_a_signed_but_invalid_manifest_is_still_refused(tmp_path, keys, good):
    """A trusted publisher's signature does not make /api/, plant writes or another image fine."""

    for change in (
        lambda m: m["runtime"].update(prefix="/api/"),
        lambda m: m["runtime"].update(image="processcraft"),
        lambda m: m["permissions"].update(read=["docker"]),
        lambda m: m["permissions"].update(plant_write=True),
        lambda m: m["permissions"].update(outbound=["example.com"]),
        lambda m: m["files"].pop("sbom.spdx.json"),
    ):
        resigned = ap.resign(good, keys[0], tmp_path / "x.pcapp", change)
        _refused(resigned, keys[1], ".")


# The image archive ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "image_kwargs",
    [
        {"tags": ["hello:0.1.0", "processcraft:0.1.0"]},
        {"tags": ["processcraft:0.1.0"]},
        {"tags": []},
        {"index_names": ["docker.io/library/processcraft-proxy:0.1.0"]},
        {"repositories": {"processcraft": {"0.1.0": "abc"}}},
        {"images": 2},
    ],
)
def test_an_image_archive_that_would_tag_other_images_is_refused(tmp_path, keys, image_kwargs):
    with pytest.raises(pkg.PackageError, match="image"):
        ap.build(tmp_path / "b", keys[0], image_kwargs=image_kwargs)
    # And a package built around the check (signed by a trusted key) is refused when verified.
    image = tmp_path / "evil-image.tar"
    ap.image_tar(image, "hello:0.1.0", **image_kwargs)
    sbom = tmp_path / "sbom.json"
    sbom.write_text(json.dumps(ap.SBOM))
    manifest = {**ap.template(), "format": 1, "files": {}}
    for name, source in (("image.tar", image), ("sbom.spdx.json", sbom)):
        manifest["files"][name] = {
            "sha256": pkg._file_digest(source)[0],
            "size": source.stat().st_size,
        }
    data = pkg.manifest_bytes(manifest)
    hostile = ap.raw(
        tmp_path / "evil.pcapp",
        [
            ("manifest.json", data),
            ("manifest.sig", pkg.sign(data, pkg.load_private_key(keys[0]))),
            ("sbom.spdx.json", sbom.read_bytes()),
            ("image.tar", image.read_bytes()),
        ],
    )
    _refused(hostile, keys[1], "image")


def test_an_image_that_is_not_a_docker_archive_is_refused(tmp_path, keys):
    image = tmp_path / "image.tar"
    image.write_bytes(b"plain bytes")
    sbom = tmp_path / "sbom.json"
    sbom.write_text(json.dumps(ap.SBOM))
    with pytest.raises(pkg.PackageError, match="image"):
        pkg.build_package({**ap.template()}, image, sbom, keys[0], tmp_path / "x.pcapp")


@pytest.mark.parametrize("sbom", [b"{}", b"[]", b'{"spdxVersion": "CycloneDX"}', b"nope"])
def test_an_sbom_that_is_not_spdx_is_refused(tmp_path, keys, sbom):
    image = tmp_path / "image.tar"
    ap.image_tar(image, "hello:0.1.0")
    path = tmp_path / "sbom.json"
    path.write_bytes(sbom)
    with pytest.raises(pkg.PackageError, match="sbom|JSON"):
        pkg.build_package(ap.template(), image, path, keys[0], tmp_path / "x.pcapp")


# Prefixes and the catalog index ---------------------------------------------------------------


def test_prefixes_of_the_proxy_and_of_other_apps_are_taken():
    assert pkg.prefix_owner("evil", "/cpm/", {}) == "cpmcraft"
    assert pkg.prefix_owner("cpmcraft", "/cpm/", {}) is None
    assert pkg.prefix_owner("b", "/a/", {"/a/": "a"}) == "a"
    assert pkg.prefix_owner("a", "/a/", {"/a/": "a"}) is None


def test_a_signed_index_verifies_and_a_changed_one_does_not(tmp_path, keys, good):
    index = pkg.build_index([good], keys[0], "testpub", tmp_path / "catalog")
    raw, sig = index.read_bytes(), (tmp_path / "catalog" / "index.json.sig").read_bytes()
    apps = pkg.verify_index(raw, sig, keys[1])
    assert apps[0]["id"] == "hello" and apps[0]["package"] == good.name
    with pytest.raises(pkg.PackageError, match="signature"):
        pkg.verify_index(raw.replace(b"hello", b"hellp"), sig, keys[1])
    with pytest.raises(pkg.PackageError, match="unknown publisher"):
        pkg.verify_index(raw, sig, {})


@pytest.mark.parametrize(
    "change",
    [
        {"package": "../../etc/passwd"},
        {"package": "https://elsewhere.example/x.pcapp"},
        {"sha256": "nothex"},
        {"size": -1},
        {"id": "Bad"},
        {"version": "x"},
    ],
)
def test_index_entries_are_checked(tmp_path, keys, good, change):
    index = pkg.build_index([good], keys[0], "testpub", tmp_path / "c")
    document = json.loads(index.read_text())
    document["apps"][0].update(change)
    raw = pkg.manifest_bytes(document)
    with pytest.raises(pkg.PackageError):
        pkg.verify_index(raw, pkg.sign(raw, pkg.load_private_key(keys[0])), keys[1])


def test_reading_a_member_never_uses_tar_extraction(monkeypatch, tmp_path, keys, good):
    """The package is read as a stream: extract and extractall are never called."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("tarfile extraction must not be used")

    monkeypatch.setattr(tarfile.TarFile, "extract", forbidden)
    monkeypatch.setattr(tarfile.TarFile, "extractall", forbidden)
    out = tmp_path / "o"
    out.mkdir()
    pkg.verify_package(good, keys[1], extract_to=out)
