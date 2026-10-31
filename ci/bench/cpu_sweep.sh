#!/usr/bin/env bash
# CPU, processes and priority of the suite's containers against the same load (plan B, 2026-10-31;
# never in GitHub CI). Each step sets some .env keys of an installation (and, for settings the
# compose file does not read from .env, a compose.override.yaml), recreates what changed, waits
# for every container to be healthy and runs ci/bench/extreme.py with a label naming the step.
#
#   ci/bench/cpu_sweep.sh --prefix P --plan per-app       # B2: each app at 1, 2 and 4 CPUs
#   ci/bench/cpu_sweep.sh --prefix P --plan executor      # B8: executor slots 1, 2, 4, 8
#   ci/bench/cpu_sweep.sh --prefix P --plan shares        # B4: priority on / off on 2 cores
#   ci/bench/cpu_sweep.sh --prefix P --plan one KEY=V ... # one step with these keys
#
# Options: --scenario C2 (extreme.py's), --people 10, --runs 1 (repeats of each step).
# The keys it set are put back as they were at the end (the .env is copied to .env.sweep-backup).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="dist/e2e-bundle/install"
PLAN="one"
SCENARIO="C2"
PEOPLE=3
RUNS=1
EXTRA=()
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift ;;
        --plan) PLAN="$2"; shift ;;
        --scenario) SCENARIO="$2"; shift ;;
        --people) PEOPLE="$2"; shift ;;
        --runs) RUNS="$2"; shift ;;
        *=*) EXTRA+=("$1") ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
    shift
done
PREFIX="$(cd "$PREFIX" && pwd)"
ENV="$PREFIX/.env"
OVERRIDE="$PREFIX/compose.override.yaml"
cp "$ENV" "$ENV.sweep-backup"
[ -f "$OVERRIDE" ] && cp "$OVERRIDE" "$OVERRIDE.sweep-backup"
HOST_CPUS="$(docker info --format '{{.NCPU}}')"

log() { printf '[cpu-sweep %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

env_set() { # KEY VALUE
    if grep -q "^$1=" "$ENV"; then
        sed -i.bak "s|^$1=.*|$1=$2|" "$ENV" && rm -f "$ENV.bak"
    else
        printf '%s=%s\n' "$1" "$2" >>"$ENV"
    fi
}

# Settings compose.yaml does not take from .env yet: Analytics' executions at once and slots,
# and cpu_shares. Written from the .env keys SWEEP_* so one mechanism sets everything.
write_override() {
    local workers slots shares_hi shares_lo
    workers="$(sed -n 's/^SWEEP_LINKCRAFT_WORKERS=//p' "$ENV" | tail -n1)"
    slots="$(sed -n 's/^SWEEP_LINKCRAFT_COMPUTE_SLOTS=//p' "$ENV" | tail -n1)"
    shares_hi="$(sed -n 's/^SWEEP_SHARES_PEOPLE=//p' "$ENV" | tail -n1)"
    shares_lo="$(sed -n 's/^SWEEP_SHARES_BACKGROUND=//p' "$ENV" | tail -n1)"
    hist_workers="$(sed -n 's/^SWEEP_HISTCRAFT_WORKERS=//p' "$ENV" | tail -n1)"
    {
        echo "# written by ci/bench/cpu_sweep.sh"
        echo "services:"
        echo "  linkcraft:"
        echo "    environment:"
        echo "      LINKCRAFT_WORKERS: \"${workers:-}\""
        echo "      LINKCRAFT_COMPUTE_SLOTS: \"${slots:-}\""
        if [ -n "$hist_workers" ] && [ "$hist_workers" != 1 ]; then
            # The Historian's API in several processes (0.6 load-test thread's override).
            echo "  histcraft:"
            echo "    command: [\"python\", \"-m\", \"uvicorn\", \"histcraft.api.app:create_app\", \"--factory\", \"--host\", \"0.0.0.0\", \"--port\", \"8100\", \"--workers\", \"$hist_workers\", \"--proxy-headers\", \"--no-access-log\"]"
        fi
        if [ -n "$shares_hi" ]; then
            echo "    cpu_shares: ${shares_lo:-256}"
            for svc in proxy processcraft dashcraft histcraft; do
                echo "  $svc:"
                echo "    cpu_shares: $shares_hi"
            done
            for svc in linkcraft-executor modelcraft-executor histcraft-collector; do
                echo "  $svc:"
                echo "    cpu_shares: ${shares_lo:-256}"
            done
        fi
    } >"$OVERRIDE"
}

compose() { docker compose --project-directory "$PREFIX" "$@"; }

wait_healthy() {
    local waited=0 bad
    while :; do
        bad="$(docker ps --filter "label=com.docker.compose.project.working_dir=$PREFIX" \
            --format '{{.Names}} {{.Status}}' | grep -v -E 'healthy\)|Up [0-9]+ (seconds|minutes|hours)$' || true)"
        bad="$(printf '%s' "$bad" | grep -E 'starting|unhealthy|Restarting|Exited' || true)"
        [ -z "$bad" ] && return 0
        waited=$((waited + 5))
        [ "$waited" -lt 300 ] || { log "not healthy after 300 s: $bad"; return 1; }
        sleep 5
    done
}

restore() {
    cp "$ENV.sweep-backup" "$ENV"
    if [ -f "$OVERRIDE.sweep-backup" ]; then cp "$OVERRIDE.sweep-backup" "$OVERRIDE"; else rm -f "$OVERRIDE"; fi
    compose up -d --remove-orphans >/dev/null 2>&1 || true
}
trap restore EXIT

step() { # LABEL KEY=VALUE...
    local label="$1" pair run
    shift
    cp "$ENV.sweep-backup" "$ENV"
    for pair in "$@"; do env_set "${pair%%=*}" "${pair#*=}"; done
    write_override
    log "step $label: $*"
    compose up -d --remove-orphans >/dev/null 2>&1
    wait_healthy
    # A smaller machine: every container of the suite on the first N cores (cpuset), which is
    # what a VM of N CPUs gives, without its memory.
    local cpuset
    cpuset="$(sed -n 's/^SWEEP_CPUSET=//p' "$ENV" | tail -n1)"
    docker ps -q --filter "label=com.docker.compose.project.working_dir=$PREFIX" |
        xargs -r docker update --cpuset-cpus "${cpuset:-0-$((HOST_CPUS - 1))}" >/dev/null
    sleep 20 # the first round after a restart and the caches settle
    for run in $(seq 1 "$RUNS"); do
        python3 "$HERE/extreme.py" --prefix "$PREFIX" --scenario "$SCENARIO" --people "$PEOPLE" \
            --label "$label${RUNS:+-r$run}" >/dev/null || log "step $label run $run failed"
    done
}

cap() { # the smaller of $1 and the host's CPUs
    awk -v a="$1" -v b="$HOST_CPUS" 'BEGIN { print (a + 0 > b + 0) ? b : a }'
}

case "$PLAN" in
    per-app)
        # Everything else at the host's CPUs; one container (group) at 1, 2, 4.
        all=(PLANTCRAFT_CPUS LINKCRAFT_CPUS LINKCRAFT_EXECUTOR_CPUS HISTCRAFT_CPUS DASHCRAFT_CPUS)
        base=()
        for key in "${all[@]}"; do base+=("$key=$HOST_CPUS"); done
        step "B2-base-all-$HOST_CPUS" "${base[@]}"
        for key in "${all[@]}"; do
            for n in 1 2 4; do
                n="$(cap "$n")"
                step "B2-${key%_CPUS}-$n" "${base[@]}" "$key=$n"
            done
        done
        ;;
    executor)
        for n in 1 2 4 8; do
            step "B8-slots-$n" "LINKCRAFT_EXECUTOR_SLOTS=$n" "SWEEP_LINKCRAFT_COMPUTE_SLOTS=$n"
        done
        ;;
    machine)
        # B2 whole machine: 1, 2, 4 cores, the Historian in 1 and 2 processes.
        for n in 1 2 4; do
            n="$(cap "$n")"
            for w in 1 2; do
                step "B2-machine-${n}c-hist${w}" "SWEEP_CPUSET=0-$((n - 1))" "SWEEP_HISTCRAFT_WORKERS=$w"
            done
        done
        ;;
    shares)
        # Two cores for everything (cpuset is not in compose's .env, so the CPU limits squeeze
        # instead): the round's executor and Analytics compete with the people's containers.
        step "B4-two-cores-no-priority" SWEEP_CPUSET=0-1
        step "B4-two-cores-priority" SWEEP_CPUSET=0-1 SWEEP_SHARES_PEOPLE=4096 SWEEP_SHARES_BACKGROUND=256
        ;;
    one)
        step "${SWEEP_LABEL:-one}" "${EXTRA[@]}"
        ;;
    *) echo "unknown plan $PLAN" >&2; exit 2 ;;
esac
log "done"
