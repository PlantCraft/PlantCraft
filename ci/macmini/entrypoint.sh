#!/usr/bin/env bash
# Registers the runner once (RUNNER_TOKEN, valid for an hour, from setup.sh), then runs it. The
# registration lives in the /runner volume, so restarts and reboots need no new token.
set -euo pipefail
: "${REPO:?REPO=owner/name is required}"

[ -x /runner/run.sh ] || cp -a /opt/runner/. /runner/
cd /runner
# Newer runners rename their .runner to .runner_migrated on their own: either one means registered.
if [ ! -f .runner ] && [ ! -f .runner_migrated ]; then
    : "${RUNNER_TOKEN:?first start: RUNNER_TOKEN is required (run setup.sh)}"
    ./config.sh --unattended --replace --url "https://github.com/$REPO" --token "$RUNNER_TOKEN" \
        --name "${RUNNER_NAME:-macmini-${REPO##*/}}" --labels macmini --work /runner/_work
fi
exec ./run.sh
