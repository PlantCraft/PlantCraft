# syntax=docker/dockerfile:1.7
#
# PlantCraft Alarms image: built online once, then shipped offline in the PlantCraft suite bundle.
# Three stages:
#   1. frontend: builds the web interface with Node (never shipped), with @plantcraft/ui
#                from the repository's ui/.
#   2. wheels:   downloads every Python dependency as a wheel, checked against the hashes in
#                deploy/requirements.lock (binary wheels only: no compiler anywhere), plus the
#                PlantCraft Alarms wheel. plantcraft-sdk is built from the repository's
#                sdk/python, never fetched from an index.
#   3. runtime:  Python slim, installs from that wheelhouse with --no-index (no network), runs
#                as an unprivileged user and holds no build tools, not even pip.
#
# Runs under the suite's deploy/compose.yaml: read-only root filesystem, state only in /data,
# scratch in the /tmp tmpfs, app key from the file PLANTCRAFT_APP_KEY_FILE names.
#
# Base images are pinned by version and digest (the same ones PlantCraft uses). Override them
# with --build-arg NODE_IMAGE=... / PYTHON_IMAGE=... (for example a registry mirror holding the
# same digests). Behind a TLS-inspecting proxy pass its CA as a build secret:
#   docker build --secret id=build_ca,src=/path/to/ca.pem ...   (make image BUILD_CA=...)

ARG NODE_IMAGE=node:22.23.3-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
ARG PYTHON_IMAGE=python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

# On the build machine's own processor: the web interface is the same for amd64 and arm64.
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS frontend
# The repository's layout, so frontend/package.json's file:../../../ui is /build/ui.
WORKDIR /build/apps/app/frontend
# @plantcraft/ui comes from this repository's ui/ (the build context named ui: make image passes
# --build-context ui=../../ui), built first with its own locked dependencies.
COPY --from=ui package.json package-lock.json tsconfig.json vite.mjs vite.d.mts /build/ui/
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    cd /build/ui && npm ci --no-audit --no-fund
COPY --from=ui src /build/ui/src
RUN cd /build/ui && npm run build
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS wheels
WORKDIR /build
COPY deploy/requirements.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip wheel --no-cache-dir --require-hashes --no-deps --only-binary=:all: \
        --wheel-dir /wheelhouse -r requirements.lock
# plantcraft-sdk comes from this repository's sdk/python (the build context named sdk), without
# its tests or any local bytecode.
COPY --from=sdk pyproject.toml ./sdk/
COPY --from=sdk plantcraft_sdk ./sdk/plantcraft_sdk
COPY --from=sdk processcraft_sdk ./sdk/processcraft_sdk
RUN find ./sdk -name __pycache__ -prune -exec rm -rf {} +
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# The plantcraft-sdk wheel from the tree, then the
# PlantCraft Alarms wheel (--no-deps: the index only provides its build backend, setuptools).
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip wheel --no-cache-dir --no-deps --wheel-dir /wheelhouse ./sdk . \
    && rm -rf build

FROM ${PYTHON_IMAGE} AS runtime

ARG VERSION=0.1.0
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="alarmcraft" \
      org.opencontainers.image.description="Rules that turn plant values and what the apps report into alarms, sent once to the right person, against ISA-18.2." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/PlantCraft/PlantCraft" \
      org.opencontainers.image.base.name="python:3.13.16-slim-trixie" \
      org.processcraft.app.id="alarmcraft" \
      org.processcraft.app.prefix="/alarm/" \
      org.processcraft.app.port="8110"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PLANTCRAFT_URL=http://processcraft:8060 \
    ALARMCRAFT_ROOT_PATH=/alarm \
    ALARMCRAFT_DATA_DIR=/data \
    ALARMCRAFT_UI_DIR=/app/ui \
    ALARMCRAFT_APP_DIR=/app \
    ALARMCRAFT_REVISION=${REVISION} \
    ALARMCRAFT_HOST=0.0.0.0 \
    ALARMCRAFT_PORT=8110 \
    FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /app
COPY --from=frontend /build/apps/app/frontend/dist /app/ui
COPY LICENSE ATTRIBUTION.md CHANGELOG.md app.toml /app/
COPY docs/help /app/docs/help

# Dependencies from the hash-checked wheelhouse, without network; then the SDK and PlantCraft Alarms.
# --no-deps everywhere: the lock is complete.
RUN --mount=type=bind,from=wheels,source=/wheelhouse,target=/wheelhouse \
    --mount=type=bind,source=deploy/requirements.lock,target=/tmp/requirements.lock \
    python -m pip install --no-cache-dir --root-user-action=ignore --no-index --find-links /wheelhouse \
        --require-hashes --no-deps -r /tmp/requirements.lock \
    && python -m pip install --no-cache-dir --root-user-action=ignore --no-index --no-deps \
        /wheelhouse/plantcraft_sdk-*-py3-none-any.whl /wheelhouse/alarmcraft-*.whl \
    && python -m pip check \
    && python -m compileall -q "$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/alarmcraft" \
    && python -m pip uninstall -y --root-user-action=ignore pip \
    && SBOM_CREATED="${CREATED}" python -m plantcraft_sdk.sbom --here "alarmcraft:${VERSION}" > /app/sbom.json \
    && rm -rf /root/.cache \
    && groupadd --gid 10009 alarmcraft \
    && useradd --no-create-home --uid 10009 --gid 10009 --home-dir /tmp --shell /usr/sbin/nologin alarmcraft \
    && mkdir -p /data \
    && chown 10009:10009 /data \
    && chmod 0750 /data

USER 10009:10009

EXPOSE 8110

HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8110/healthz', timeout=4)"]

CMD ["alarmcraft", "serve"]
