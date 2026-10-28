#!/usr/bin/env bash
# Copies this repository's main to a cloud VM and runs deploy/cloud/vm.sh there:
#
#   deploy/cloud/push-to-vm.sh ubuntu@203.0.113.10 [-i ~/.ssh/key] [vm.sh command, default all]
#   REF=v0.5.0 deploy/cloud/push-to-vm.sh ...    a release tag (or any ref) instead of origin/main
#
# From any machine with a clone (the Mac mini's ~/processcraft-ci, a laptop). Only the
# repository's files travel (git archive of origin/main, ~15 MB): no key, no token, no
# secret. The VM builds the bundle itself, natively for its processor, with internet.
# Then once on the VM: sudo /opt/plantcraft-src/deploy/cloud/vm.sh tunnel (and chat-key).
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ $# -ge 1 ] || { sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; }
HOST="$1"
shift
SSH=(ssh -o StrictHostKeyChecking=accept-new)
if [ "${1:-}" = "-i" ]; then
    SSH+=(-i "$2")
    shift 2
fi
COMMAND="${1:-all}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

REF="${REF:-origin/main}"
git -C "$ROOT" fetch -q --tags origin main
git -C "$ROOT" rev-parse -q --verify "$REF^{commit}" >/dev/null || { echo "[push] no $REF here" >&2; exit 1; }
printf '[push] %s: %s %s\n' "$HOST" "$REF" "$(git -C "$ROOT" log -1 --format='%h %s' "$REF")"
git -C "$ROOT" archive --format=tar.gz -o "$WORK/src.tgz" "$REF"
"${SSH[@]}" "$HOST" 'sudo rm -rf /opt/plantcraft-src.new && sudo mkdir -p /opt/plantcraft-src.new'
"${SSH[@]}" "$HOST" 'sudo tar -xzf - -C /opt/plantcraft-src.new' <"$WORK/src.tgz"
# The previous copy's dist/ (built images' bundle, logs) is not kept: a new bundle is built.
"${SSH[@]}" "$HOST" 'sudo rm -rf /opt/plantcraft-src.old; [ -d /opt/plantcraft-src ] && sudo mv /opt/plantcraft-src /opt/plantcraft-src.old; sudo mv /opt/plantcraft-src.new /opt/plantcraft-src && sudo rm -rf /opt/plantcraft-src.old'
"${SSH[@]}" -t "$HOST" "sudo /opt/plantcraft-src/deploy/cloud/vm.sh $COMMAND"
