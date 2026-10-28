#!/usr/bin/env bash
# Builds a signed PlantCraft app package (docs/app-package.md) from the app's app.toml
# (docs/app-standard.md, section 4) and its local image. An app's `make package` calls it.
#
#   deploy/package.sh --app app.toml --key /secure/publisher.key \
#                     [--sbom sbom.spdx.json] [--out dist/] [--no-gzip]
#
# --app       the app repository's app.toml (or the same sections as JSON); --manifest too
# --image     the image to package (default <runtime.image>:<app.version> from app.toml)
# --key       the publisher's Ed25519 private key (PEM), passed by path; never commit it
# --sbom      an SPDX JSON SBOM of the image; made with syft when omitted and syft is installed
# --out       folder for <id>-<version>.pcapp (default dist/)
#
# Usable from another repository: it needs only bash, docker, python3 with `cryptography`, and
# processcraft/apps/package.py next to this script (or PLANTCRAFT_PACKAGE_PY pointing at it).
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_PY="${PLANTCRAFT_PACKAGE_PY:-$HERE/../processcraft/apps/package.py}"
MANIFEST="" IMAGE="" KEY="" SBOM="" OUT="dist" GZIP="--gzip"

die() { printf 'package: ERROR: %s\n' "$*" >&2; exit 1; }
while [ $# -gt 0 ]; do
    case "$1" in
        --app | --manifest) MANIFEST="$2"; shift ;;
        --image) IMAGE="$2"; shift ;;
        --key) KEY="$2"; shift ;;
        --sbom) SBOM="$2"; shift ;;
        --out) OUT="$2"; shift ;;
        --no-gzip) GZIP="" ;;
        -h | --help) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown option $1 (see --help)" ;;
    esac
    shift
done
[ -n "$MANIFEST" ] && [ -n "$KEY" ] || die "--app and --key are required"
[ -f "$PACKAGE_PY" ] || die "package.py not found at $PACKAGE_PY (set PLANTCRAFT_PACKAGE_PY)"
[ -r "$MANIFEST" ] || die "cannot read $MANIFEST"
[ -r "$KEY" ] || die "cannot read the key $KEY"

read -r ID VERSION NAME < <(python3 - "$MANIFEST" <<'PY'
import json, sys, tomllib
path = sys.argv[1]
with open(path, "rb") as handle:
    doc = tomllib.load(handle) if path.endswith(".toml") else json.load(handle)
print(doc["app"]["id"], doc["app"]["version"], doc["runtime"]["image"])
PY
) || die "$MANIFEST has no [app] id/version or [runtime] image"
[ -n "$IMAGE" ] || IMAGE="$NAME:$VERSION"
[ "$IMAGE" = "$NAME:$VERSION" ] || die "the image must be tagged $NAME:$VERSION ([runtime] image and [app] version)"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "image $IMAGE not found: build it first"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "package: saving $IMAGE"
docker save -o "$WORK/image.tar" "$IMAGE"
if [ -z "$SBOM" ]; then
    command -v syft >/dev/null 2>&1 || die "no --sbom given and syft is not installed"
    echo "package: SBOM with syft"
    syft "docker-archive:$WORK/image.tar" -o "spdx-json=$WORK/sbom.spdx.json" -q
    SBOM="$WORK/sbom.spdx.json"
fi
mkdir -p "$OUT"
python3 "$PACKAGE_PY" build --manifest "$MANIFEST" --image-tar "$WORK/image.tar" --sbom "$SBOM" \
    --key "$KEY" --out "$OUT/$ID-$VERSION.pcapp" $GZIP
(cd "$OUT" && sha256sum "$ID-$VERSION.pcapp" | tee "$ID-$VERSION.pcapp.sha256")
