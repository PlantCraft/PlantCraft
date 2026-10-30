# syntax=docker/dockerfile:1.7
#
# PlantCraft Simulator image: built online once, then shipped offline in the PlantCraft suite bundle.
# Two stages:
#   1. wheels:  downloads every Python dependency as a wheel, checked against the hashes in
#               deploy/requirements.lock (binary wheels only: no compiler anywhere), plus the
#               PlantCraft Simulator wheel.
#   2. runtime: Python slim, installs from that wheelhouse with --no-index (no network), runs
#               as an unprivileged user (uid 10004) and holds no build tools, not even pip.
#
# Runs under the suite's deploy/compose.yaml (service `simcraft`, profile `demo`): read-only
# root filesystem, state only in /data, scratch in the /tmp tmpfs, OPC UA on port 4840.
# The default command serves the 50-loop portfolio the PlantCraft demo reads; run
# `simcraft serve --profile smoke ...` instead for the 500-signal benchmark.
#
# The base image is pinned by version and digest (the same one PlantCraft uses). Override it
# with --build-arg PYTHON_IMAGE=... (for example a registry mirror holding the same digest).
# Behind a TLS-inspecting proxy pass its CA as a build secret:
#   docker build --secret id=build_ca,src=/path/to/ca.pem ...   (make image BUILD_CA=...)

ARG PYTHON_IMAGE=python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

FROM ${PYTHON_IMAGE} AS wheels
WORKDIR /build
COPY deploy/requirements.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip wheel --no-cache-dir --require-hashes --only-binary=:all: \
        --wheel-dir /wheelhouse -r requirements.lock
COPY pyproject.toml README.md LICENSE MANIFEST.in CHANGELOG.md CITATION.cff SECURITY.md ./
COPY src ./src
# The PlantCraft Simulator wheel (--no-deps: the index only provides its build backend, setuptools).
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip wheel --no-cache-dir --no-deps --wheel-dir /wheelhouse . \
    && rm -rf build

FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=0.4.0
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="simcraft" \
      org.opencontainers.image.description="PlantCraft Simulator: OPC UA process plant simulator for the PlantCraft suite" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/PlantCraft/PlantCraft" \
      org.opencontainers.image.base.name="python:3.13.16-slim-trixie"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    SIMCRAFT_ENDPOINT=opc.tcp://0.0.0.0:4840/plantcraft/ \
    SIMCRAFT_HEALTH_ENDPOINT=opc.tcp://127.0.0.1:4840/plantcraft/ \
    SIMCRAFT_HISTORY_DB=/data/opcua-history.sqlite3 \
    SIMCRAFT_STATE_DB=/data/opcua-state.sqlite3

WORKDIR /app
COPY LICENSE ATTRIBUTION.md CHANGELOG.md /app/

# Dependencies from the hash-checked wheelhouse, without network; then PlantCraft Simulator.
RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    --mount=type=bind,source=deploy/requirements.lock,target=/tmp/requirements.lock \
    python -m pip install --no-cache-dir --root-user-action=ignore --no-index --find-links /wheelhouse \
        --require-hashes -r /tmp/requirements.lock \
    && python -m pip install --no-cache-dir --root-user-action=ignore --no-index --no-deps \
        /wheelhouse/simcraft-*.whl \
    && python -m pip check \
    && python -m compileall -q "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && python -m pip uninstall -y --root-user-action=ignore pip \
    && rm -rf /root/.cache \
    && groupadd --gid 10004 simcraft \
    && useradd --no-create-home --uid 10004 --gid 10004 --home-dir /tmp --shell /usr/sbin/nologin simcraft \
    && mkdir -p /data \
    && chown 10004:10004 /data \
    && chmod 0750 /data

USER 10004:10004
VOLUME ["/data"]
EXPOSE 4840

# The first start backfills 48 hours of history before the port opens: allow two minutes.
HEALTHCHECK --interval=15s --timeout=10s --start-period=120s --retries=8 \
    CMD ["python", "-m", "simcraft.healthcheck"]

CMD ["simcraft", "loops", "serve"]
