"""Which PlantCraft versions an app works on: ``plantcraft-app compat``, ``tested`` and ``license``.

``plantcraft-app compat --url <PlantCraft> [--key-file <app key>]`` checks the app in this folder
against a running PlantCraft of some version (docs/app-package.md, section 7):

1. the version is inside ``[requires] platform`` and the API inside ``[requires] processcraft_api``;
2. every table of ``[contributes]`` the app fills is one this PlantCraft draws (``features``);
3. every permission in ``[permissions]`` is one this PlantCraft knows (``scopes``);
4. the key is accepted (``GET /api/v1/me``);
5. the app's own contract tests, ``tests/compat`` when it has them, pass against it
   (``PLANTCRAFT_URL`` and ``PLANTCRAFT_COMPAT_KEY_FILE`` point them at it).

It writes ``compat/<version>.json``. The package build (``package.py build --compat-dir compat``)
stamps every version whose report passed for this app version into the manifest's ``[tested]``,
which the Apps page shows and the installer compares with the installation's version.

``plantcraft-app tested`` lists those versions; ``plantcraft-app license issue`` signs a
``.pclicense`` for a customer (``plantcraft_sdk.licensing``) and ``license show`` checks one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COMMANDS = {"compat", "tested", "license"}
_CLAUSE = re.compile(r"^\s*(==|>=|<=|>|<|!=|~=)?\s*([0-9]{1,6}(?:\.[0-9]{1,6}){0,3})(\.\*)?\s*$")


def _key(version: str) -> tuple[int, ...]:
    core = version.strip().split("-")[0].split("+")[0]
    numbers = tuple(int(part) for part in core.split(".") if part.isdigit())
    return numbers + (0,) * (4 - len(numbers))


def version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    pre = version.strip().partition("-")[2]
    return _key(version), 0 if pre else 1, pre


def satisfies(version: str, spec: str) -> bool:
    """``version`` inside ``spec`` (">=0.6,<0.8", "==0.6.*", "~=0.6"); the same rule as
    PlantCraft's installer (plantcraft/apps/package.py). A pre-release counts as its release."""

    have = _key(version)
    for clause in spec.split(","):
        match = _CLAUSE.match(clause)
        if not match:
            raise ValueError(f"cannot read the range {spec!r}")
        op, text, star = match.group(1) or "==", match.group(2), bool(match.group(3))
        parts = tuple(int(part) for part in text.split("."))
        want = parts + (0,) * (4 - len(parts))
        if star or op == "~=":
            if op not in ("==", "!=", "~="):
                raise ValueError(f"cannot read the range {spec!r}")
            size = len(parts) if star else max(1, len(parts) - 1)
            inside = have[:size] == parts[:size] and (star or have >= want)
            if (op == "!=") == inside:
                return False
            continue
        ok = {
            "==": have == want,
            "!=": have != want,
            ">=": have >= want,
            "<=": have <= want,
            ">": have > want,
            "<": have < want,
        }[op]
        if not ok:
            return False
    return True


def tested_versions(root: Path, app_id: str, app_version: str) -> list[str]:
    """The PlantCraft versions whose ``compat/<version>.json`` passed for this app version."""

    found = []
    for path in sorted((root / "compat").glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(report, dict)
            and report.get("passed") is True
            and report.get("app") == app_id
            and report.get("app_version") == app_version
            and isinstance(report.get("platform"), str)
        ):
            found.append(report["platform"])
    return sorted(set(found), key=version_key)


def compat_report(
    manifest: Any, installation: dict[str, Any], *, me_ok: bool, tests: dict[str, Any] | None
) -> dict[str, Any]:
    """The checks of section 7 for one PlantCraft, from its ``GET /api/v1/installation``."""

    platform = str(installation.get("version") or "")
    api = str(installation.get("api") or "1.0")
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    requires = manifest.requires
    if not platform:
        add("platform", False, "this PlantCraft does not say its version (before 0.6)")
    elif requires.platform:
        inside = satisfies(platform, requires.platform)
        add(
            "platform",
            inside,
            f"{platform} {'inside' if inside else 'outside'} {requires.platform}",
        )
    else:
        add("platform", True, f"{platform} ([requires] platform not set)")
    inside_api = satisfies(api, requires.processcraft_api)
    add("api", inside_api, f"API {api} for {requires.processcraft_api}")
    features = set(installation.get("features") or [])
    filled = [
        name
        for name, value in manifest.contributes.model_dump().items()
        if value not in (None, False, [], {}, "")
    ]
    missing = sorted(set(filled) - features)
    add(
        "contributes",
        not missing,
        "all drawn" if not missing else f"not drawn by this PlantCraft: {', '.join(missing)}",
    )
    scopes = installation.get("scopes")
    asked = [f"read.{name}" for name in manifest.permissions.read] + [
        f"write.{name}" for name in manifest.permissions.write
    ]
    if isinstance(scopes, list):
        unknown = sorted(set(asked) - set(scopes))
        add(
            "permissions",
            not unknown,
            "all known" if not unknown else f"unknown here: {', '.join(unknown)}",
        )
    else:
        add("permissions", True, "this PlantCraft does not list its scopes (before 0.6)")
    add("key", me_ok, "the app key is accepted" if me_ok else "GET /api/v1/me refused the key")
    if tests is not None:
        add("tests", tests["passed"], tests["detail"])
    return {
        "app": manifest.app.id,
        "app_version": manifest.app.version,
        "sdk": manifest.requires.sdk,
        "platform": platform,
        "api": api,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "checks": checks,
        "passed": bool(platform) and all(item["ok"] for item in checks),
    }


def _run_compat(args: argparse.Namespace) -> int:
    import httpx

    from plantcraft_sdk.app_manifest import ManifestError, load_manifest

    root = Path(args.path)
    try:
        manifest = load_manifest(root / "app.toml")
    except ManifestError as exc:
        print("\n".join(f"error: app.toml: {problem}" for problem in exc.problems), file=sys.stderr)
        return 1
    key_file = args.key_file or os.environ.get("PLANTCRAFT_APP_KEY_FILE")
    headers = {}
    if key_file:
        headers["Authorization"] = f"Bearer {Path(key_file).read_text(encoding='utf-8').strip()}"
    base = args.url.rstrip("/")
    with httpx.Client(timeout=20, headers=headers, verify=not args.insecure) as client:
        response = client.get(f"{base}/api/v1/installation")
        if response.is_error:
            print(f"error: GET /api/v1/installation: HTTP {response.status_code}", file=sys.stderr)
            return 1
        installation = response.json()
        me_ok = client.get(f"{base}/api/v1/me").is_success
    tests = None
    folder = root / args.tests
    if folder.is_dir():
        env = {**os.environ, "PLANTCRAFT_URL": base}
        if key_file:
            env["PLANTCRAFT_COMPAT_KEY_FILE"] = str(Path(key_file).resolve())
        done = subprocess.run(  # noqa: S603 - the app's own tests, in its own folder
            [sys.executable, "-m", "pytest", "-q", str(folder)], cwd=root, env=env, check=False
        )
        tests = {
            "passed": done.returncode == 0,
            "detail": f"{args.tests}: {'passed' if done.returncode == 0 else 'failed'}",
        }
    report = compat_report(manifest, installation, me_ok=me_ok, tests=tests)
    for item in report["checks"]:
        print(f"{'ok  ' if item['ok'] else 'FAIL'} {item['check']}: {item['detail']}")
    if report["platform"]:
        out = root / args.out
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{report['platform']}.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"{path}: {'passed' if report['passed'] else 'failed'}")
    return 0 if report["passed"] else 1


def _run_tested(args: argparse.Namespace) -> int:
    from plantcraft_sdk.app_manifest import load_manifest

    root = Path(args.path)
    manifest = load_manifest(root / "app.toml")
    versions = tested_versions(root, manifest.app.id, manifest.app.version)
    print(json.dumps({"platform": versions}))
    return 0


def _parse_limits(items: list[str]) -> dict[str, int]:
    limits = {}
    for item in items:
        name, _, value = item.partition("=")
        if not value.isdigit():
            raise ValueError(f"--limit {item!r}: name=number")
        limits[name.strip()] = int(value)
    return limits


def _run_license(args: argparse.Namespace) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from plantcraft_sdk import licensing

    try:
        if args.license_command == "issue":
            key = serialization.load_pem_private_key(Path(args.key).read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise licensing.LicenseError("the key must be an Ed25519 private key")
            issued = datetime.now(UTC).date().isoformat()
            body = {
                "id": args.id or f"{args.app}-{datetime.now(UTC):%Y%m%d%H%M%S}",
                "app": args.app,
                "publisher": args.publisher,
                "customer": args.customer,
                "installation": args.installation,
                "issued": issued,
                "expires": args.expires,
                "limits": _parse_limits(args.limit or []),
                "features": list(args.feature or []),
            }
            data = licensing.issue(key, body)
            Path(args.out).write_bytes(data)
            print(f"{args.out}: {body['app']} for {body['customer']} until {body['expires']}")
            return 0
        key = licensing.load_public_key(Path(args.public_key).read_bytes())
        found = licensing.state(
            Path(args.file).read_bytes(),
            key,
            app_id=args.app,
            installation=args.installation,
            grace_days=args.grace_days,
        )
        print(json.dumps(found.to_json(), indent=2))
        return 0 if found.usable else 1
    except (licensing.LicenseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def add_commands(commands: Any) -> None:
    compat = commands.add_parser("compat", help="check the app against a running PlantCraft")
    compat.add_argument("--url", required=True, help="the PlantCraft to check against")
    compat.add_argument("--key-file", help="an app key for it (default PLANTCRAFT_APP_KEY_FILE)")
    compat.add_argument("--path", default=".", help="the app repository (default: .)")
    compat.add_argument("--tests", default="tests/compat", help="the app's contract tests")
    compat.add_argument("--out", default="compat", help="where the report goes")
    compat.add_argument("--insecure", action="store_true", help="accept a self-signed certificate")
    tested = commands.add_parser("tested", help="the PlantCraft versions the app passed on")
    tested.add_argument("--path", default=".")
    license_ = commands.add_parser("license", help="sign or check a .pclicense")
    sub = license_.add_subparsers(dest="license_command", required=True)
    issue = sub.add_parser("issue", help="sign a licence for a customer (publisher only)")
    issue.add_argument("--key", required=True, help="the publisher's private key")
    issue.add_argument("--app", required=True)
    issue.add_argument("--publisher", required=True, help='as in app.toml, e.g. "Acme Tools"')
    issue.add_argument("--customer", required=True)
    issue.add_argument("--installation", required=True, help='installation id, or "*" for any')
    issue.add_argument("--expires", required=True, help="last day, like 2027-12-31")
    issue.add_argument("--limit", action="append", help="name=number, repeatable")
    issue.add_argument("--feature", action="append", help="a feature name, repeatable")
    issue.add_argument("--id", help="the licence's id (default: app and time)")
    issue.add_argument("--out", required=True)
    show = sub.add_parser("show", help="check a licence with the publisher's public key")
    show.add_argument("--public-key", required=True)
    show.add_argument("--app", required=True)
    show.add_argument("--installation")
    show.add_argument("--grace-days", type=int, default=14)
    show.add_argument("file")


def run(args: argparse.Namespace) -> int:
    if args.command == "compat":
        return _run_compat(args)
    if args.command == "tested":
        return _run_tested(args)
    return _run_license(args)
