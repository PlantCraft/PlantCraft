#!/usr/bin/env bash
# Runs the suite's CI on this Mac mini (README.md): builds the runner image, registers the
# repository's runners (one per CI slot, up to three) and points its CI at them.
#
#   ./setup.sh            build, register what is missing, switch CI to the Mac mini
#   ./setup.sh --off      switch CI back to GitHub's runners (the runners stay, idle)
#
# Needs Docker Desktop and the GitHub CLI signed in as the repositories' owner
# (brew install gh && gh auth login). Safe to run again.
set -euo pipefail
cd "$(dirname "$0")"

OWNER="${OWNER:-PlantCraft}"
REPO="${REPO:-PlantCraft}"
# The repositories that had their own runner before every app moved into processcraft (apps/).
FORMER="linkcraft dashcraft plantcraft histcraft alarmcraft modelcraft"
# The installed suite: ~/PlantCraft, or ~/ProcessCraft where it was installed before the rename.
if [ -z "${SUITE_DIR:-}" ]; then
    SUITE_DIR="$HOME/PlantCraft"
    [ -f "$SUITE_DIR/compose.yaml" ] || [ ! -f "$HOME/ProcessCraft/compose.yaml" ] || SUITE_DIR="$HOME/ProcessCraft"
fi
export SUITE_DIR
compose() { docker compose -f compose.yaml "$@"; }

command -v docker >/dev/null || { echo "Docker Desktop is not running or not installed."; exit 1; }
command -v jq >/dev/null || { echo "Install jq first: brew install jq"; exit 1; }
command -v gh >/dev/null || { echo "Install the GitHub CLI first: brew install gh && gh auth login"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Sign in first: gh auth login"; exit 1; }

if [ "${1:-}" = "--off" ]; then
    gh variable delete CI_RUNNER -R "$OWNER/$REPO" 2>/dev/null || true
    gh variable delete TEST_RUNNER -R "$OWNER/$REPO" 2>/dev/null || true
    gh variable delete MACMINI_DEPLOY -R "$OWNER/$REPO" 2>/dev/null || true
    echo "$REPO: CI back on GitHub's runners"
    exit 0
fi

# The latest runner release and the SHA-256 GitHub publishes for its linux tarball (arm64 on
# Apple silicon, x64 elsewhere).
case "$(uname -m)" in arm64|aarch64) arch=arm64 ;; *) arch=x64 ;; esac
release="$(gh api repos/actions/runner/releases/latest)"
version="$(printf '%s' "$release" | jq -r .tag_name | sed 's/^v//')"
sha="$(printf '%s' "$release" | jq -r --arg n "actions-runner-linux-$arch-$version.tar.gz" \
    '.assets[] | select(.name == $n) | .digest // empty' | sed 's/^sha256://')"
if [ -z "$sha" ]; then
    sha="$(printf '%s' "$release" | jq -r .body | tr -d '\r' |
        sed -n "s/.*<!-- BEGIN SHA linux-$arch -->\([0-9a-f]\{64\}\)<!-- END SHA linux-$arch -->.*/\1/p" | head -1)"
fi
[ -n "$version" ] && [ -n "$sha" ] || { echo "Could not read the runner release from GitHub."; exit 1; }
echo "Building the runner image (actions/runner $version)..."
docker build -t processcraft-ci-runner:latest \
    --build-arg RUNNER_VERSION="$version" --build-arg RUNNER_SHA256="$sha" .

# How many jobs may build at once: about 3 GB each (the runners' mem_limit), after 4 GB for the
# suite itself, from the memory Docker Desktop has (Settings > Resources).
mem_gb=$(( $(docker info --format '{{.MemTotal}}') / 1024 / 1024 / 1024 ))
CI_SLOTS="${CI_SLOTS:-$(( (mem_gb - 4) / 3 ))}"
[ "$CI_SLOTS" -ge 1 ] || CI_SLOTS=1
[ "$CI_SLOTS" -le 3 ] || CI_SLOTS=3
export CI_SLOTS
echo "Docker Desktop has ${mem_gb} GB: up to $CI_SLOTS CI job(s) at a time."

# Runners started before the project was named "processcraft-ci" ran as "macmini" (the folder's
# name): stop those containers so they do not run twice (every service has a profile, so
# `down` needs --profile '*' to see them). Their volumes stay.
if [ -n "$(docker ps -aq --filter label=com.docker.compose.project=macmini)" ]; then
    echo "Moving the runners from the old \"macmini\" project to \"processcraft-ci\"..."
    docker compose -p macmini -f compose.yaml --profile '*' down >/dev/null
fi

[ -f "$SUITE_DIR/compose.yaml" ] ||
    echo "Note: no suite in $SUITE_DIR; deploys fail until it is installed (or set SUITE_DIR)."

# The former per-app runners: their repositories are archived, so they would only sit idle.
for name in $FORMER; do
    ids="$(docker ps -aq --filter label=com.docker.compose.project=processcraft-ci \
        --filter "label=com.docker.compose.service=$name")"
    if [ -n "$ids" ]; then
        # shellcheck disable=SC2086
        docker rm -f $ids >/dev/null
        echo "$name: its former runner removed (the app is in $REPO now)"
    fi
done

# On a public repository a stranger's pull request could ask for this machine: its workflow runs
# from the pull request's own files. The tests run on GitHub's runners (free for a public
# repository), each runner here refuses every job that is not main's (ci-slot-acquire.sh), and a
# first-time contributor's pull request waits for a maintainer before any workflow runs.
if [ "$(gh repo view "$OWNER/$REPO" --json isPrivate -q .isPrivate)" != "true" ]; then
    gh api -X PUT "repos/$OWNER/$REPO/actions/permissions/fork-pr-contributor-approval" \
        -f approval_policy=all_external_contributors >/dev/null
    echo "$REPO: public; every outside contributor's workflow run waits for approval"
fi
runners=(processcraft processcraft-2 processcraft-3)
for i in "${!runners[@]}"; do
    service="${runners[$i]}"
    if [ "$i" -ge "$CI_SLOTS" ]; then
        compose --profile "$service" stop "$service" >/dev/null 2>&1 || true
        continue
    fi
    token=""
    # Registered for another repository (the suite moved to $OWNER/$REPO): registered again here.
    # (.runner, or .runner_migrated once the runner has renamed it on its own.)
    if ! docker run --rm -v "processcraft-ci_$service:/runner" --entrypoint sh \
        processcraft-ci-runner:latest -c 'grep -qsi "$1" /runner/.runner /runner/.runner_migrated' \
        sh "github.com/$OWNER/$REPO\""; then
        compose --profile "$service" rm -sf "$service" >/dev/null 2>&1 || true
        docker run --rm -v "processcraft-ci_$service:/runner" --entrypoint rm \
            processcraft-ci-runner:latest -f /runner/.runner /runner/.runner_migrated /runner/.credentials \
            /runner/.credentials_migrated /runner/.credentials_rsaparams
        token="$(gh api -X POST "repos/$OWNER/$REPO/actions/runners/registration-token" -q .token)"
    fi
    RUNNER_TOKEN="$token" compose --profile "$service" up -d "$service" >/dev/null
    echo "$service: runner up"
done
# Tests run on GitHub's runners (README.md); the runners here take only main's deploy jobs.
gh variable set MACMINI_DEPLOY --body true -R "$OWNER/$REPO" >/dev/null
echo "$REPO: deploys now run on the Mac mini ($CI_SLOTS runner(s)); tests run on GitHub"
echo
echo "Runners: docker compose -f $(pwd)/compose.yaml ps    Logs: ... logs -f <repo>"
