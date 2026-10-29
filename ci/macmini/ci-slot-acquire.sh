#!/bin/sh
# The runner's job-started hook. The repository is public, so its pull requests (a stranger's
# fork can edit a workflow to ask for this machine) never run here: only main's own jobs (a push,
# the schedule, a run by hand) of this repository. Anything else fails before its first step.
event="${GITHUB_EVENT_NAME:-}" ref="${GITHUB_REF:-}"
repo="$(printf '%s' "${GITHUB_REPOSITORY:-}" | tr '[:upper:]' '[:lower:]')"
want="$(printf '%s' "${REPO:-}" | tr '[:upper:]' '[:lower:]')"
case "$event" in push | schedule | workflow_dispatch) ;; *) event="" ;; esac
if [ -z "$event" ] || [ "$ref" != refs/heads/main ] || [ -z "$want" ] || [ "$repo" != "$want" ]; then
    echo "This runner takes only main's jobs of $REPO (got ${GITHUB_EVENT_NAME:-no event} on ${GITHUB_REF:-no ref} of ${GITHUB_REPOSITORY:-no repository})." >&2
    exit 1
fi
exec /usr/local/bin/ci-slot acquire
