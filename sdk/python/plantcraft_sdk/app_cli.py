"""``plantcraft-app check [path]``: does an app repository follow the suite standard?

(``plantcraft-app sbom <image>`` writes an image's SPDX SBOM: ``plantcraft_sdk.sbom``.)

Checks ``app.toml`` (``plantcraft_sdk.app_manifest``, sections 4 and 7 of
``docs/app-standard.md``) and the repository layout of section 5: the required
files, the ``pyproject.toml`` version equal to the ``app.toml`` version, the
``Makefile`` targets and the SHA-256 line of the vendored SDK in
``vendor/README.md``; and the operations rules (``docs/operations.md``): a
``CHANGELOG.md`` entry for the version, every SQLite file in ``[backup]``, logs
through ``configure_logging``. Prints every problem and exits 1 when there is one;
warnings alone exit 0. Each app's ``make ci`` runs it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from plantcraft_sdk.app_manifest import AppManifest, ManifestError, load_manifest

# Section 5: files and folders every app repository has ("{id}" is the app id).
REQUIRED_FILES = (
    "app.toml",
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "SPEC.md",
    "ROADMAP.md",
    "SECURITY.md",
    "LICENSE",
    "ATTRIBUTION.md",
    "CHANGELOG.md",
    "Makefile",
    "Dockerfile",
    "pyproject.toml",
    "deploy/requirements.in",
    "deploy/requirements.lock",
    "vendor/README.md",
    "src/{id}/cli.py",
    "tests/floors.toml",
    "docs/STATUS.md",
    "docs/gaps.md",
    "docs/devlog.md",
)
REQUIRED_DIRS = ("src/{id}/api", "frontend", "tests", "docs/help")
MAKE_TARGETS = (
    "ci",
    "deps",
    "standard",
    "lint",
    "format",
    "test",
    "test-fast",
    "frontend",
    "e2e",
    "image",
    "package",
)
# What ``make ci`` runs in every app, as GitHub CI does (scale review A7, SDK 0.44.0).
CI_STEPS = ("deps", "standard", "lint", "frontend", "test")
SHA256_LINE = re.compile(
    # "SHA-256: <hex>" in prose, or a ``sha256sum -c`` line "<hex>  plantcraft_sdk-...whl"
    # (or "<hex>  plantcraft-ui-...tgz").
    r"sha-?256\W.*\b([0-9a-f]{64})\b|^\s*([0-9a-f]{64})\s+\*?plantcraft[_-](?:sdk|ui)-",
    re.IGNORECASE | re.MULTILINE,
)
# A database file named in the code: "linkcraft.sqlite3".
SQLITE_NAME = re.compile(r"""["']([A-Za-z0-9._-]+\.sqlite3)["']""")
# "## [0.4.1] - 2026-10-21" (Keep a Changelog).
CHANGELOG_ENTRY = r"^##\s*\[{version}\]"
ASSETS_DIR = re.compile(r"""assetsDir\s*:\s*["']static["']""")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _make_targets(text: str) -> set[str]:
    targets = set()
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z0-9_.\- ]+):(?!=)", line)
        if match and not line.startswith("\t"):
            targets.update(name for name in match.group(1).split() if not name.startswith("."))
    return targets


def _layout(root: Path, manifest: AppManifest, report: Report) -> None:
    app_id = manifest.app.id
    for name in REQUIRED_FILES:
        path = root / name.format(id=app_id)
        if not path.is_file():
            report.errors.append(f"{path.relative_to(root)}: missing (section 5)")
    for name in REQUIRED_DIRS:
        path = root / name.format(id=app_id)
        if not path.is_dir():
            report.errors.append(f"{path.relative_to(root)}/: missing folder (section 5)")


def _pyproject(root: Path, manifest: AppManifest, report: Report) -> None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        report.errors.append(f"pyproject.toml: not valid TOML ({exc})")
        return
    version = (data.get("project") or {}).get("version")
    if version != manifest.app.version:
        report.errors.append(
            f"pyproject.toml: version {version!r} differs from app.toml's {manifest.app.version!r}"
        )
    length = ((data.get("tool") or {}).get("ruff") or {}).get("line-length")
    if length != 100:
        report.warnings.append("pyproject.toml: [tool.ruff] line-length is 100 in every app")


def _makefile(root: Path, report: Report) -> None:
    path = root / "Makefile"
    if not path.is_file():
        return
    text = path.read_text()
    missing = [name for name in MAKE_TARGETS if name not in _make_targets(text)]
    if missing:
        report.errors.append(f"Makefile: missing targets {', '.join(missing)} (section 5)")
    ci = re.search(r"^ci:([^=\n]*)$", text, re.MULTILINE)
    steps = ci.group(1).split() if ci else []
    if "ci" not in missing and [step for step in CI_STEPS if step in steps] != list(CI_STEPS):
        report.errors.append(
            f"Makefile: ci runs {' '.join(steps) or 'nothing'}; every app runs "
            f"{' '.join(CI_STEPS)} (section 5)"
        )


def _vendor(root: Path, manifest: AppManifest, report: Report) -> None:
    readme = root / "vendor" / "README.md"
    if not readme.is_file():
        return
    text = readme.read_text()
    sums = {(match.group(1) or match.group(2)).lower() for match in SHA256_LINE.finditer(text)}
    if not sums:
        report.errors.append("vendor/README.md: no SHA-256 line for the plantcraft-sdk wheel")
    wheels = sorted((root / "vendor").glob("plantcraft_sdk-*.whl"))
    for wheel in wheels:
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if sums and digest not in sums:
            report.errors.append(f"vendor/README.md: no SHA-256 line matches {wheel.name}")
        if not wheel.name.startswith(f"plantcraft_sdk-{manifest.requires.sdk}-"):
            report.errors.append(
                f"vendor/{wheel.name}: app.toml requires sdk {manifest.requires.sdk}"
            )


def _frontend(root: Path, report: Report) -> None:
    configs = sorted((root / "frontend").glob("vite.config.*"))
    if not configs:
        return
    if not any(ASSETS_DIR.search(path.read_text(encoding="utf-8")) for path in configs):
        report.warnings.append(
            f"frontend/{configs[0].name}: set build.assetsDir to 'static' "
            "(assets/ is the asset deep link, section 7)"
        )


UI_PACKAGE = "@plantcraft/ui"
UI_TGZ = re.compile(r"^file:\.\./vendor/(plantcraft-ui-[0-9][0-9A-Za-z.+-]*\.tgz)$")


def _frame(root: Path, report: Report) -> None:
    """The web interface draws the suite frame from the vendored package (section 10, D6)."""

    package = root / "frontend" / "package.json"
    if not package.is_file():
        return
    try:
        spec = (json.loads(package.read_text(encoding="utf-8")).get("dependencies") or {}).get(
            UI_PACKAGE
        )
    except (ValueError, AttributeError):
        report.errors.append("frontend/package.json: not valid JSON")
        return
    match = UI_TGZ.match(spec or "")
    if not match:
        report.errors.append(
            f"frontend/package.json: depend on {UI_PACKAGE} as "
            '"file:../vendor/plantcraft-ui-<version>.tgz" (section 10)'
        )
        return
    tgz = root / "vendor" / match.group(1)
    if not tgz.is_file():
        report.errors.append(f"vendor/{tgz.name}: missing (section 10)")
        return
    readme = root / "vendor" / "README.md"
    text = readme.read_text() if readme.is_file() else ""
    sums = {(m.group(1) or m.group(2)).lower() for m in SHA256_LINE.finditer(text)}
    if hashlib.sha256(tgz.read_bytes()).hexdigest() not in sums:
        report.errors.append(f"vendor/README.md: no SHA-256 line matches {tgz.name}")
    sources = (root / "frontend" / "src").rglob("*.tsx")
    if not any("SuiteShell" in path.read_text(encoding="utf-8") for path in sources):
        report.errors.append("frontend/src: draw the suite frame with SuiteShell (section 10)")


def _operations(root: Path, manifest: AppManifest, report: Report) -> None:
    """Release notes, backup and logs (``docs/operations.md``)."""

    changelog = root / "CHANGELOG.md"
    version = manifest.app.version
    if changelog.is_file() and not re.search(
        CHANGELOG_ENTRY.format(version=re.escape(version)),
        changelog.read_text(encoding="utf-8"),
        re.MULTILINE,
    ):
        report.errors.append(f"CHANGELOG.md: no entry for {version} (## [{version}] - <date>)")
    package = root / "src" / manifest.app.id
    sources = (
        {path: path.read_text(encoding="utf-8") for path in sorted(package.rglob("*.py"))}
        if package.is_dir()
        else {}
    )
    named = {name for text in sources.values() for name in SQLITE_NAME.findall(text)}
    declared = {Path(name).name for name in manifest.backup.sqlite}
    for name in sorted(named - declared):
        report.errors.append(f"app.toml: [backup] sqlite does not name {name} (it is in the code)")
    code = "\n".join(sources.values())
    if sources and "configure_logging(" not in code:
        report.errors.append(
            "src: logs do not go through plantcraft_sdk.server.logs.configure_logging"
        )
    if "uvicorn.run(" in code and "log_config=None" not in code:
        report.errors.append("src: uvicorn.run needs log_config=None (the suite's JSON logs)")


def check(path: str | Path = ".") -> Report:
    """Every problem of the app repository at ``path``."""

    root = Path(path)
    report = Report()
    if not root.is_dir():
        report.errors.append(f"{root}: not a folder")
        return report
    if not (root / "app.toml").is_file():
        report.errors.append("app.toml: missing (section 4)")
        return report
    try:
        manifest = load_manifest(root / "app.toml")
    except ManifestError as exc:
        report.errors.extend(f"app.toml: {problem}" for problem in exc.problems)
        return report
    _layout(root, manifest, report)
    _pyproject(root, manifest, report)
    _makefile(root, report)
    _vendor(root, manifest, report)
    _frontend(root, report)
    _frame(root, report)
    _operations(root, manifest, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plantcraft-app",
        description="Check that an app repository follows the PlantCraft app standard.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    checker = commands.add_parser("check", help="validate app.toml and the repository layout")
    checker.add_argument("path", nargs="?", default=".", help="the app repository (default: .)")
    sbom = commands.add_parser("sbom", help="write the SPDX SBOM of an app's image to stdout")
    sbom.add_argument("image", help="name:version of the built image")
    sbom.add_argument("--here", action="store_true", help="read this Python (inside the image)")
    args = parser.parse_args(argv)
    if args.command == "sbom":
        from plantcraft_sdk.sbom import main as write_sbom

        return write_sbom(args.image, here=args.here)
    report = check(args.path)
    for warning in report.warnings:
        print(f"warning: {warning}")
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)
    if report.ok:
        print(f"plantcraft-app check: {args.path} follows the standard.")
        return 0
    print(f"plantcraft-app check: {len(report.errors)} problem(s) in {args.path}.", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
